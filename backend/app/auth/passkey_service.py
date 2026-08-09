import base64
import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta
from hashlib import sha256

import webauthn
from fastapi import HTTPException, status
from sqlalchemy import func, select
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
from app.auth.aaguid import label_from_aaguid
from app.auth.db_models import PasskeyCredential, User
from app.auth.member_directory import MemberDirectory, member_directory_for
from app.auth.models import (
    PasskeyCredentialResponse,
    PasskeyLoginCompleteRequest,
    PasskeyRegisterCompleteRequest,
    PasskeyRegisterCompleteResponse,
    TokenResponse,
    UserClaims,
)
from app.auth.token import encode_token
from app.core.security_logger import log_security_event
from app.db.unit_of_work import AbstractUnitOfWork

# Generic, indistinguishable failure for both begin-completion decoy paths and
# genuine "wrong credential" paths -- must never leak which case occurred.
_AUTH_FAILED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication failed"
)


def _decode_challenge(challenge_str: str) -> bytes:
    padded = challenge_str + "=" * (4 - len(challenge_str) % 4)
    return base64.urlsafe_b64decode(padded)


def _encode_challenge(challenge: bytes) -> str:
    return base64.urlsafe_b64encode(challenge).rstrip(b"=").decode()


def _to_registration_credential(
    cred: PasskeyCredentialResponse,
) -> RegistrationCredential:
    resp = cred.response
    return RegistrationCredential(
        id=cred.id,
        raw_id=_decode_challenge(cred.rawId),
        response=AuthenticatorAttestationResponse(
            client_data_json=_decode_challenge(resp["clientDataJSON"]),
            attestation_object=_decode_challenge(resp["attestationObject"]),
        ),
    )


def _to_authentication_credential(
    cred: PasskeyCredentialResponse,
) -> AuthenticationCredential:
    resp = cred.response
    user_handle_str = resp.get("userHandle")
    return AuthenticationCredential(
        id=cred.id,
        raw_id=_decode_challenge(cred.rawId),
        response=AuthenticatorAssertionResponse(
            client_data_json=_decode_challenge(resp["clientDataJSON"]),
            authenticator_data=_decode_challenge(resp["authenticatorData"]),
            signature=_decode_challenge(resp["signature"]),
            user_handle=(
                _decode_challenge(user_handle_str) if user_handle_str else None
            ),
        ),
    )


def _authentication_options_response(options) -> dict:
    """Serialise generate_authentication_options() output, dropping
    allowCredentials.

    py_webauthn 3.0.0 always emits an `allowCredentials` key -- an empty
    list when the argument is omitted, same as when it is passed as `[]` --
    it never leaves the key out on its own. Real logins now rely entirely on
    discoverable credentials (see login_passkey_begin), so the field would
    otherwise sit at `[]` on every path and add nothing; stripping it here,
    in the one place both the real and decoy paths funnel through, is what
    makes the two responses byte-identical (issue #267). Do this in one
    shared helper rather than in both callers, so there is only one place
    that can drift.
    """
    public_key = json.loads(options_to_json(options))
    public_key.pop("allowCredentials", None)
    return {"publicKey": public_key}


def _decoy_user_id(identifier: str) -> str:
    """Derive a decoy publicKey.user.id that is stable for a given identifier
    under a fixed server secret, and changes if the secret changes (issue
    #300).

    The real begin paths (register_passkey_begin, invite_service's
    invite_redeem_begin) return a persisted primary key as user.id -- stable
    forever for a given email/token, by construction. An earlier revision of
    both decoy paths minted a fresh uuid4() per call instead, which was
    itself the enumeration oracle: two POSTs plus one field comparison told a
    caller "unstable id -> unknown identifier" with no timing analysis
    needed, because a real account's id never moves and a decoy's always did.

    Deriving the id from the identifier ALONE (e.g. sha256(email)) would trade
    one oracle for another -- see _decoy_login_response's docstring for the
    same lesson learned the hard way with the challenge field: anyone could
    precompute the decoy id for an email/token they merely guessed, and a
    match would confirm the guess without ever calling the API. HMAC-ing the
    identifier with a value only this server holds (config.JWT_SECRET, read
    at call time -- not imported at module load, so tests can monkeypatch it)
    is what makes the id BOTH stable across repeat calls AND unpredictable to
    anyone who doesn't hold that secret. The bug being fixed is the
    asymmetry between the two paths, not the choice of "stable" or "random"
    in isolation -- so this is the one place both callers route through, to
    keep them from drifting apart again.

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


def _decoy_login_response() -> dict:
    """Decoy for an unknown email, shaped exactly like a real begin response.

    The challenge is deliberately NOT passed: letting py_webauthn generate
    it is what guarantees the decoy matches the real path in both width and
    distribution. Supplying our own invited two separate tells -- an earlier
    revision derived it deterministically from the email (identical bytes
    across two calls classified any address in one round trip), and a later
    one used 32 random bytes against py_webauthn's 64-byte default, which
    was visible as a 43- vs 86-character challenge. Nothing verifies a decoy
    challenge server-side, so there is no reason to construct one.
    """
    options = webauthn.generate_authentication_options(
        rp_id=config.WEBAUTHN_RP_ID,
        # Must match the real path's level exactly -- a decoy advertising a
        # different userVerification is a #239-style shape tell. See
        # login_passkey_begin for why "required" rather than the default.
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    return _authentication_options_response(options)


def _decoy_register_response(email: str) -> dict:
    # Normalised the same way a case/whitespace variant of a known email
    # would be treated -- strip + casefold. `email` has already been through
    # LenientEmail's validation (app.auth.models), which normalises the
    # domain but deliberately leaves local-part case alone (RFC 5321 permits
    # a case-sensitive local part). Re-normalising here is defense-in-depth
    # so that "A@b.com" and "a@b.com" derive the SAME decoy id -- otherwise
    # the two would silently diverge from how a human expects "the same
    # email" to behave, without ever showing up as inconsistent between the
    # real and decoy paths (both would just independently be case-sensitive).
    decoy_id = _decoy_user_id(email.strip().casefold())
    options = webauthn.generate_registration_options(
        rp_id=config.WEBAUTHN_RP_ID,
        rp_name="Kendo Dojo",
        # Real path passes a UUID string; match that width so the encoded
        # user id is not itself a decoy tell. Challenge omitted, as above.
        # Stable per-email via _decoy_user_id -- see its docstring for why
        # (issue #300): a fresh uuid4() per call was itself an enumeration
        # oracle, since the real path's id never moves for a given email.
        user_id=decoy_id.encode("utf-8"),
        user_name=email,
        # user_display_name mirrors user_name on both paths: the caller
        # already knows the email they typed (attacker-controlled on both
        # sides), so reusing it here adds a human-readable label without
        # opening a new width channel. See register_passkey_begin for why
        # the real path does the same rather than looking up a member name.
        user_display_name=email,
        # Registration must request a discoverable (resident) credential:
        # login no longer sends allowCredentials (see login_passkey_begin),
        # so it depends on the authenticator surfacing the credential itself
        # via the browser's account picker. The decoy MUST request the same
        # shape as the real path -- see register_passkey_begin -- or this
        # field becomes a new #239-style tell.
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
    )
    return {"publicKey": json.loads(options_to_json(options))}


async def _is_bootstrap(uow: AbstractUnitOfWork) -> bool:
    """True when no fully-registered user exists yet.

    Counts PasskeyCredential rows, not User rows, matching the convention in
    app/routers/setup.py. A User row is inserted before the interactive
    WebAuthn ceremony completes, so counting users would let a single
    abandoned first-run ceremony leave a phantom user behind, flip this to
    False forever, and permanently brick setup (no Member row exists yet, so
    every retry would get a decoy).
    """
    passkey_count = await uow.session.execute(
        select(func.count()).select_from(PasskeyCredential)
    )
    return passkey_count.scalar_one() == 0


async def _get_or_create_user(
    email: str, uow: AbstractUnitOfWork, is_first_user: bool
) -> User:
    result = await uow.session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None:
        role = "admin" if is_first_user else "member"
        user = User(
            email=email,
            role=role,
            is_active=True,
        )
        uow.session.add(user)
        await uow.session.flush()
    return user


async def register_passkey_begin(
    email: str,
    uow: AbstractUnitOfWork,
    member_directory: MemberDirectory | None = None,
) -> dict:
    directory = member_directory or member_directory_for(uow)

    is_bootstrap = await _is_bootstrap(uow)
    if not is_bootstrap and not await directory.has_member(email):
        return _decoy_register_response(email)

    user = await _get_or_create_user(email, uow, is_bootstrap)
    await directory.link_user(email, user.id)

    options = webauthn.generate_registration_options(
        rp_id=config.WEBAUTHN_RP_ID,
        rp_name="Kendo Dojo",
        user_id=user.id.encode("utf-8"),
        user_name=user.email,
        # No Member row is guaranteed reachable here without an extra query
        # (bootstrap registers with no Member at all), and the decoy path
        # below would need a same-width value to match -- there is no member
        # name available to a decoy for an email that doesn't exist. Reusing
        # the email keeps both paths trivially equal-width; see
        # _decoy_register_response.
        user_display_name=user.email,
        # See _decoy_register_response: this MUST match the decoy's
        # authenticator_selection exactly, both to preserve the #239
        # shape guarantee and because login now depends on a discoverable
        # credential existing (no allowCredentials -- see login_passkey_begin).
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
    )

    user.pending_challenge = _encode_challenge(options.challenge)
    user.challenge_issued_at = datetime.now(UTC)
    await uow.commit()

    return {"publicKey": json.loads(options_to_json(options))}


async def register_passkey_complete(
    payload: PasskeyRegisterCompleteRequest, uow: AbstractUnitOfWork
) -> PasskeyRegisterCompleteResponse:
    result = await uow.session.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()
    if user is None:
        log_security_event("passkey_registered", "failure")
        raise _AUTH_FAILED

    # These must not be distinguishable from the unknown-email case above: a
    # 400 here would only ever be reachable for an email that already cleared
    # the Member gate, and accounts sit in the "no pending challenge" state
    # most of the time -- making 400-vs-401 a high-hit-rate enumeration
    # oracle. The specific reason still goes to the security log.
    if not user.pending_challenge or not user.challenge_issued_at:
        log_security_event("passkey_registered", "failure", user_id=user.id)
        raise _AUTH_FAILED
    age = datetime.now(UTC) - user.challenge_issued_at.replace(tzinfo=UTC)
    if age > timedelta(seconds=config.WEBAUTHN_CHALLENGE_TTL_SECONDS):
        log_security_event("passkey_registered", "failure", user_id=user.id)
        raise _AUTH_FAILED
    expected_challenge = _decode_challenge(user.pending_challenge)

    try:
        verified = webauthn.verify_registration_response(
            credential=_to_registration_credential(payload.credential),
            expected_challenge=expected_challenge,
            expected_rp_id=config.WEBAUTHN_RP_ID,
            expected_origin=config.WEBAUTHN_ORIGIN,
            # Enforce, do not merely request. py_webauthn defaults this to
            # False and only checks authenticator-data's uv bit when it is
            # True, so without it the userVerification="required" advertised
            # by register_passkey_begin is decorative: a caller driving the
            # API directly could enrol a credential that performed no user
            # verification at all.
            require_user_verification=True,
        )
    except Exception as exc:
        log_security_event("passkey_registered", "failure", user_id=user.id)
        raise _AUTH_FAILED from exc

    existing_count_result = await uow.session.execute(
        select(func.count())
        .select_from(PasskeyCredential)
        .where(PasskeyCredential.user_id == user.id)
    )
    existing_count = existing_count_result.scalar_one()
    show_nudge = existing_count == 0

    aaguid_raw = verified.aaguid
    aaguid_str = str(aaguid_raw) if aaguid_raw is not None else None
    passkey = PasskeyCredential(
        user_id=user.id,
        credential_id=verified.credential_id,
        public_key=verified.credential_public_key,
        sign_count=verified.sign_count,
        aaguid=aaguid_str,
        label=label_from_aaguid(aaguid_str),
    )
    uow.session.add(passkey)
    user.pending_challenge = None
    await uow.commit()

    log_security_event("passkey_registered", "success", user_id=user.id)
    return PasskeyRegisterCompleteResponse(
        sub=user.id,
        email=user.email,
        role=user.role,  # type: ignore[arg-type]
        is_active=user.is_active,
        theme=user.theme,  # type: ignore[arg-type]
        show_nudge=show_nudge,
    )


async def login_passkey_begin(email: str, uow: AbstractUnitOfWork) -> dict:
    result = await uow.session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None:
        return _decoy_login_response()

    # allow_credentials is deliberately not passed (issue #267). It used to
    # list one PublicKeyCredentialDescriptor per registered passkey, which
    # made the response body grow with N -- an enumeration oracle by size
    # alone, no timing analysis needed, sitting right next to the always-
    # empty list _decoy_login_response returned for unknown emails.
    # Registration now requires a discoverable (resident) credential (see
    # register_passkey_begin), so the authenticator itself can surface the
    # right credential via the browser's account picker; the server does not
    # need to name candidates up front. Do not "fix" this back to a
    # per-credential list -- that reintroduces the oracle this issue closed.
    #
    # user_verification is "required" rather than py_webauthn's "preferred"
    # default because login_passkey_complete now enforces the uv flag: a
    # merely-preferred level lets a conforming authenticator skip UV and then
    # be rejected at verification, which would look like a broken login.
    # _decoy_login_response passes the identical level.
    options = webauthn.generate_authentication_options(
        rp_id=config.WEBAUTHN_RP_ID,
        user_verification=UserVerificationRequirement.REQUIRED,
    )

    user.pending_challenge = _encode_challenge(options.challenge)
    user.challenge_issued_at = datetime.now(UTC)
    await uow.commit()

    return _authentication_options_response(options)


async def login_passkey_complete(
    payload: PasskeyLoginCompleteRequest, uow: AbstractUnitOfWork
) -> TokenResponse:
    result = await uow.session.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()
    if user is None:
        raise _AUTH_FAILED

    # NOTE: the is_active check deliberately happens *after* signature
    # verification below, not here. Rejecting an inactive account before the
    # credential is checked lets anyone distinguish "deactivated member" from
    # "unknown email" with a single request carrying a junk credential.
    # Account status is only disclosed to someone who has already proved
    # possession of a registered passkey.

    # Decode credential_id from the request to find the matching stored credential
    cred_id_b64 = payload.credential.id
    cred_id_bytes = _decode_challenge(cred_id_b64)

    cred_result = await uow.session.execute(
        select(PasskeyCredential).where(
            PasskeyCredential.user_id == user.id,
            PasskeyCredential.credential_id == cred_id_bytes,
        )
    )
    stored_cred = cred_result.scalar_one_or_none()
    if stored_cred is None:
        raise _AUTH_FAILED

    if not user.pending_challenge or not user.challenge_issued_at:
        raise _AUTH_FAILED
    age = datetime.now(UTC) - user.challenge_issued_at.replace(tzinfo=UTC)
    if age > timedelta(seconds=config.WEBAUTHN_CHALLENGE_TTL_SECONDS):
        raise _AUTH_FAILED
    expected_challenge = _decode_challenge(user.pending_challenge)

    try:
        verified = webauthn.verify_authentication_response(
            credential=_to_authentication_credential(payload.credential),
            expected_challenge=expected_challenge,
            expected_rp_id=config.WEBAUTHN_RP_ID,
            expected_origin=config.WEBAUTHN_ORIGIN,
            credential_public_key=stored_cred.public_key,
            credential_current_sign_count=stored_cred.sign_count,
            # See register_passkey_complete: this is what actually checks the
            # uv flag that login_passkey_begin asks for.
            require_user_verification=True,
        )
    except Exception as exc:
        raise _AUTH_FAILED from exc

    # Credential possession is now proven, so disclosing account status here
    # tells the caller nothing they could not already infer about their own
    # account. See the note above where this check used to live.
    if not user.is_active:
        user.pending_challenge = None
        await uow.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account deactivated",
        )

    stored_cred.sign_count = verified.new_sign_count
    stored_cred.last_used_at = datetime.now(UTC)
    user.pending_challenge = None
    await uow.commit()

    claims = UserClaims(
        sub=user.id,
        email=user.email,
        role=user.role,  # type: ignore[arg-type]
        is_active=user.is_active,
        theme=user.theme,  # type: ignore[arg-type]
    )
    log_security_event("login_passkey", "success", user_id=user.id)
    return TokenResponse(access_token=encode_token(claims))
