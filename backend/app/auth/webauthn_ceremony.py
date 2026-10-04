"""The one place a WebAuthn "begin" response is shaped (issue #354).

Three endpoints answer for any identifier, registered or not, and must be
indistinguishable whether or not the identifier is known::

    POST /auth/register/passkey/begin
    POST /auth/login/passkey/begin
    POST /auth/invites/redeem/begin

Four rules decide whether a decoy is distinguishable from the real thing:
the resident-key requirement, the user-verification level, the user-id byte
width and version nibbles, and where the challenge comes from. Until this
module existed those rules were chosen twice -- once in
`app.auth.passkey_service`, once in `app.auth.invite_service` -- and held in
step by matching comments plus one private import across the seam. That
convention failed three times, and each failure was an enumeration oracle:

* **#239** -- a decoy advertising different options than the real path.
* **#267** -- `allowCredentials` present on one path and absent on the other;
  now stripped in one place so the two are byte-identical.
* **#300** -- the real paths return a persisted primary key as `user.id`,
  stable forever, while both decoys minted a fresh `uuid4()` per call. Two
  POSTs and one field comparison classified any identifier, with no timing
  analysis at all.

So the real/decoy choice is an *internal branch* here rather than two call
sites that have to agree: `Subject | None`, where `None` means "no such
account". Both responses come out of the same `generate_*_options` call, so
none of the four rules can diverge without the change being visible in one
place. `tests/test_webauthn_ceremony_conventions.py` fails if a second
construction site appears.

A fifth rule joins them on the invite path: constant name width. The other
two paths echo an address the caller already typed, so their two outcomes
match for free. An invite decoy cannot -- it does not know the invitee's
address -- so `invite_begin` pads both of its outcomes to one width. See
there for what that costs and why it is invisible.

What this module deliberately does NOT do is pad the response. The
constant-time floor lives in `app.core.middleware.ConstantTimeAuthMiddleware`
because the unit-of-work is a `yield` dependency whose commit runs *after*
the service returns -- padding inside a service function measured the wrong
region and still leaked ~1.3ms. See that class and
`docs/auth-timing-calibration.md`.
"""

from __future__ import annotations

import base64
import hmac
import json
import uuid
from dataclasses import dataclass
from hashlib import sha256

import webauthn
from webauthn import options_to_json
from webauthn.helpers.structs import (
    AuthenticationCredential,
    AuthenticatorAssertionResponse,
    AuthenticatorAttestationResponse,
    AuthenticatorSelectionCriteria,
    RegistrationCredential,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app import config
from app.auth.models import PasskeyCredentialResponse

# Rule 1 and 2, in one object used by every registration ceremony, real and
# decoy alike.
#
# Registration must request a discoverable (resident) credential: login no
# longer sends `allowCredentials` (see `login_begin`), so it depends on the
# authenticator surfacing the credential itself via the browser's account
# picker. A credential minted without `resident_key=REQUIRED` would be
# unusable for login afterwards.
#
# `user_verification` is "required" rather than py_webauthn's "preferred"
# default because the complete paths enforce the uv flag
# (`require_user_verification=True`); a merely-preferred level lets a
# conforming authenticator skip UV and then be rejected at verification,
# which would look like a broken login.
_DISCOVERABLE_CREDENTIAL = AuthenticatorSelectionCriteria(
    resident_key=ResidentKeyRequirement.REQUIRED,
    user_verification=UserVerificationRequirement.REQUIRED,
)

# Rule 2 again for the authentication ceremony, which has no
# AuthenticatorSelectionCriteria to carry it. Named so the two uses are
# visibly the same decision.
_USER_VERIFICATION = _DISCOVERABLE_CREDENTIAL.user_verification


def decode_challenge(challenge_str: str) -> bytes:
    padded = challenge_str + "=" * (4 - len(challenge_str) % 4)
    return base64.urlsafe_b64decode(padded)


def _encode_challenge(challenge: bytes) -> str:
    return base64.urlsafe_b64encode(challenge).rstrip(b"=").decode()


def to_registration_credential(
    cred: PasskeyCredentialResponse,
) -> RegistrationCredential:
    resp = cred.response
    return RegistrationCredential(
        id=cred.id,
        raw_id=decode_challenge(cred.rawId),
        response=AuthenticatorAttestationResponse(
            client_data_json=decode_challenge(resp["clientDataJSON"]),
            attestation_object=decode_challenge(resp["attestationObject"]),
        ),
    )


def to_authentication_credential(
    cred: PasskeyCredentialResponse,
) -> AuthenticationCredential:
    resp = cred.response
    user_handle_str = resp.get("userHandle")
    return AuthenticationCredential(
        id=cred.id,
        raw_id=decode_challenge(cred.rawId),
        response=AuthenticatorAssertionResponse(
            client_data_json=decode_challenge(resp["clientDataJSON"]),
            authenticator_data=decode_challenge(resp["authenticatorData"]),
            signature=decode_challenge(resp["signature"]),
            user_handle=(
                decode_challenge(user_handle_str) if user_handle_str else None
            ),
        ),
    )


# RFC 5321 caps an address at 254 octets and email_validator enforces that
# (app.auth.models.LenientEmail), so every real invitee address fits inside
# this width with room to pad. Both invite outcomes are padded to it; see
# `invite_begin`.
_INVITE_NAME_OCTETS = 254


def _fixed_width(name: str) -> str:
    """Pad `name` with trailing spaces to exactly _INVITE_NAME_OCTETS UTF-8
    octets.

    Octets, not characters: an address may have a non-ASCII local part
    (email_validator allows SMTPUTF8 by default) and FastAPI serialises the
    response with `ensure_ascii=False`, so a multi-byte character costs more
    than one byte on the wire. Padding to a character count would leave the
    Content-Length varying with the address's encoding -- a quieter version
    of the very channel this closes.

    Spaces are the padding: `user.name` and `user.displayName` are handed
    straight to `navigator.credentials.create()` and never rendered by this
    app (see frontend/src/api/auth.ts), so the only place the padding could
    show is the authenticator's account picker, where trailing whitespace is
    invisible. Nothing here is stored server-side, and a validated address
    can contain neither a quote nor a backslash (email_validator rejects
    quoted local parts), so no JSON escaping can reintroduce a width delta.
    """
    # A byte slice can land mid-codepoint; drop the partial tail rather than
    # emit invalid UTF-8, then pad back to the full width.
    trimmed = name.encode("utf-8")[:_INVITE_NAME_OCTETS].decode(
        "utf-8", errors="ignore"
    )
    return trimmed + " " * (_INVITE_NAME_OCTETS - len(trimmed.encode("utf-8")))


def _decoy_user_id(identifier: str) -> str:
    """Derive a decoy publicKey.user.id that is stable for a given identifier
    under a fixed server secret, and changes if the secret changes (issue
    #300).

    The real begin paths return a persisted primary key as user.id -- stable
    forever for a given email/token, by construction. An earlier revision of
    both decoy paths minted a fresh uuid4() per call instead, which was
    itself the enumeration oracle: two POSTs plus one field comparison told a
    caller "unstable id -> unknown identifier" with no timing analysis
    needed, because a real account's id never moves and a decoy's always did.

    Deriving the id from the identifier ALONE (e.g. sha256(email)) would trade
    one oracle for another -- see `login_begin`'s docstring for the same
    lesson learned the hard way with the challenge field: anyone could
    precompute the decoy id for an email/token they merely guessed, and a
    match would confirm the guess without ever calling the API. HMAC-ing the
    identifier with a value only this server holds (config.JWT_SECRET, read
    at call time -- not imported at module load, so tests can monkeypatch it)
    is what makes the id BOTH stable across repeat calls AND unpredictable to
    anyone who doesn't hold that secret. The bug being fixed is the
    asymmetry between the two paths, not the choice of "stable" or "random"
    in isolation.

    b"decoy-user-id-v1" domain-separates this derivation from any other use
    of JWT_SECRET (token signing) so the two uses can never collide or be
    swapped for one another.

    Truncated to 16 bytes and formatted as a UUID string to match the byte
    width py_webauthn encodes a real UUID id at -- a decoy id of a different
    width would be a #239-style shape tell independent of the stability
    question this function exists to fix.

    version=4 is load-bearing, not cosmetic. Real ids come from uuid4()
    (app/db/base.py), so their version and variant nibbles are fixed by RFC
    4122; raw truncated HMAC bytes have effectively random ones. Formatting
    the digest without forcing those bits would let a caller classify an
    email from a SINGLE response -- parse the id and check version == 4,
    which a real account always satisfies and a raw digest satisfies about
    one time in sixteen -- trading the two-call stability oracle this
    function closes for a strictly easier one-call format oracle. Fixing
    six bits costs nothing: the remaining 122 stay HMAC-derived, which is
    the same entropy budget a genuine uuid4 has.
    """
    digest = hmac.new(
        key=config.JWT_SECRET.encode("utf-8"),
        msg=b"decoy-user-id-v1:" + identifier.encode("utf-8"),
        digestmod=sha256,
    ).digest()
    return str(uuid.UUID(bytes=digest[:16], version=4))


@dataclass(frozen=True)
class Subject:
    """The account a begin ceremony is really for.

    `None` in place of one means "no such account", which is the only input
    that selects a decoy. Holding the two fields together is what stops a
    caller supplying a real id with a decoy name, or vice versa.
    """

    user_id: str
    user_name: str


@dataclass(frozen=True)
class Ceremony:
    """A begin response plus the challenge to persist against the account.

    `challenge` is already in the form `Account.pending_challenge` stores and
    `decode_challenge` reads back, so no caller re-encodes it. Decoy callers
    discard it -- there is no account row to persist it against, and nothing
    verifies a decoy challenge server-side. The absent write is why the decoy
    path is faster than the real one, which is a latency channel rather than
    a shape one; app.core.middleware covers it.
    """

    response: dict
    challenge: str


def _registration_ceremony(subject: Subject) -> Ceremony:
    """Build a registration begin response -- the single site for all four
    shape rules on the register and invite-redeem paths.

    The challenge is deliberately NOT passed in: letting py_webauthn generate
    it is what guarantees every response matches every other in both width
    and distribution. See `login_begin` for the two tells that supplying one
    produced.

    `user_display_name` mirrors `user_name` rather than looking up a member
    name. No Member row is guaranteed reachable here without an extra query
    (bootstrap registers with no Member at all), and a decoy has no member
    name available for an identifier that does not exist -- so any other
    choice would open a width channel between the two paths.
    """
    options = webauthn.generate_registration_options(
        rp_id=config.WEBAUTHN_RP_ID,
        rp_name="Kendo Dojo",
        user_id=subject.user_id.encode("utf-8"),
        user_name=subject.user_name,
        user_display_name=subject.user_name,
        authenticator_selection=_DISCOVERABLE_CREDENTIAL,
    )
    return Ceremony(
        response={"publicKey": json.loads(options_to_json(options))},
        challenge=_encode_challenge(options.challenge),
    )


def register_begin(email: str, subject: Subject | None) -> Ceremony:
    """Registration begin for `email`; `subject=None` yields the decoy.

    The decoy identifier is normalised the same way a case/whitespace variant
    of a known email would be treated -- strip + casefold. `email` has
    already been through LenientEmail's validation (app.auth.models), which
    normalises the domain but deliberately leaves local-part case alone (RFC
    5321 permits a case-sensitive local part). Re-normalising here is
    defense-in-depth so that "A@b.com" and "a@b.com" derive the SAME decoy
    id -- otherwise the two would silently diverge from how a human expects
    "the same email" to behave, without ever showing up as inconsistent
    between the real and decoy paths (both would just independently be
    case-sensitive).

    The decoy's `user_name` is the email the caller typed. That is
    attacker-controlled on both sides -- they already know what they sent --
    so echoing it costs nothing and keeps the two paths trivially
    equal-width, the real path's `user_name` being the same address.
    """
    if subject is None:
        subject = Subject(
            user_id=_decoy_user_id(email.strip().casefold()),
            user_name=email,
        )
    return _registration_ceremony(subject)


def invite_begin(token: str, subject: Subject | None) -> Ceremony:
    """Invite-redemption begin for `token`; `subject=None` yields the decoy.

    Keyed by the raw token, not a normalised form: unlike an email, a token
    is an opaque secrets.token_urlsafe() value with no case-insensitive
    convention to respect, so normalising it would only create collisions
    between otherwise-distinct tokens.

    Unlike `register_begin`, the decoy cannot echo the identifier as
    `user_name`: the real path returns the invitee's persisted email, which
    the caller does not know and which never moves for a given token. A
    fresh uuid4() local part would leave the #300 oracle fully intact on this
    field after closing it on user_id, since a caller can compare either one
    across two calls. So the name is derived from the same stable id. Both
    fields must be stable, or neither is.

    Stability is not enough on its own, though, because a *stable* name of
    the wrong LENGTH is still a one-call oracle. A synthesised
    "<uuid>@invite.invalid" is a fixed 51 octets while a real invitee's
    address is whatever it is, and `user_name` is echoed into
    `user.displayName` too -- so before padding, every unusable token
    answered at one fixed size while a usable one answered at a size that
    tracked the invitee's address. Content-Length alone classified a token in
    a single call, and ConstantTimeAuthMiddleware pads latency, not size.

    Both outcomes are therefore padded to `_INVITE_NAME_OCTETS`, which is the
    only mechanism available here: the decoy cannot imitate a length it
    cannot know, so the real path has to stop varying. The alternative --
    giving the real path a constant *synthetic* name -- would have shown the
    invitee "<uuid>@invite.invalid" in their authenticator's account picker
    at every subsequent login, for the life of the credential. Padding keeps
    the real address as the label and puts the width delta in trailing
    whitespace instead, which nothing renders. See `_fixed_width`.

    Every redeem-begin response is now 1045 bytes on the wire, measured, for
    a usable token and an unusable one alike -- roughly 400 bytes more than
    before. Timing is unaffected: the real path stays about 2.9ms slower than
    the decoy raw, the same gap as before padding, and the middleware floor
    covers it.

    Scope of what this closes: invite tokens are secrets.token_urlsafe(32),
    so the channel never enumerated anything -- it told the holder of one
    specific link whether that link was still usable. Smaller than
    #239/#267/#300, and worth 400 bytes because the guarantee this module
    exists to make should not carry an asterisk on one of its three paths.
    """
    if subject is None:
        decoy_id = _decoy_user_id(token)
        subject = Subject(user_id=decoy_id, user_name=f"{decoy_id}@invite.invalid")
    return _registration_ceremony(
        Subject(
            user_id=subject.user_id,
            user_name=_fixed_width(subject.user_name),
        )
    )


def login_begin() -> Ceremony:
    """Authentication begin -- identical for a known and an unknown email.

    There is no real/decoy branch here at all, which is the strongest form
    of the guarantee the other two functions get from an internal one: the
    caller decides only whether to persist the challenge, never what the
    response looks like.

    `allow_credentials` is deliberately not passed (issue #267). It used to
    list one PublicKeyCredentialDescriptor per registered passkey, which made
    the response body grow with N -- an enumeration oracle by size alone, no
    timing analysis needed, sitting right next to the always-empty list the
    decoy returned for unknown emails. Registration now requires a
    discoverable credential (see `_DISCOVERABLE_CREDENTIAL`), so the
    authenticator itself surfaces the right credential via the browser's
    account picker and the server need not name candidates up front. Do not
    "fix" this back to a per-credential list -- that reintroduces the oracle
    #267 closed.

    py_webauthn 3.0.0 always emits an `allowCredentials` key -- an empty list
    when the argument is omitted, same as when it is passed as `[]` -- it
    never leaves the key out on its own, so it is popped here.

    The challenge is deliberately NOT passed. Supplying our own invited two
    separate tells: an earlier revision derived it deterministically from the
    email (identical bytes across two calls classified any address in one
    round trip), and a later one used 32 random bytes against py_webauthn's
    64-byte default, which was visible as a 43- vs 86-character challenge.
    Nothing verifies a decoy challenge server-side, so there is no reason to
    construct one.
    """
    options = webauthn.generate_authentication_options(
        rp_id=config.WEBAUTHN_RP_ID,
        user_verification=_USER_VERIFICATION,
    )
    public_key = json.loads(options_to_json(options))
    public_key.pop("allowCredentials", None)
    return Ceremony(
        response={"publicKey": public_key},
        challenge=_encode_challenge(options.challenge),
    )
