"""Business logic for admin-issued invite tokens (#257).

Delivery is a copyable invite link only -- no SMTP, no email sending. Token
storage is a deterministic sha256 digest, not a per-row-salted bcrypt hash,
because redemption looks a row up by token alone with no scoping identity
(user/email) known ahead of time.

Redeeming an invite creates the Member row for that email if none exists, or
links the existing one -- the same convergence point the #239 Member gate
uses (see app.auth.member_directory.ensure_member_for_email). The redemption
endpoints reuse the #239 decoy-response shape and the #255 constant-time
floor (app.core.middleware) rather than inventing new mechanisms: an invalid
token (unknown, expired, revoked, or already-redeemed) must be
indistinguishable from a valid one on both response shape and latency.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import webauthn
from fastapi import HTTPException, status
from sqlalchemy import select
from webauthn import options_to_json
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app import config
from app.auth.aaguid import label_from_aaguid
from app.auth.db_models import PasskeyCredential, User
from app.auth.invite_repository import AbstractInviteRepository, SqlInviteRepository
from app.auth.member_directory import member_directory_for
from app.auth.models import (
    InviteCreateRequest,
    InviteRedeemCompleteRequest,
    PasskeyRegisterCompleteResponse,
)
from app.auth.passkey_service import (
    _decode_challenge,
    _decoy_user_id,
    _encode_challenge,
    _to_registration_credential,
)
from app.core.security_logger import log_security_event
from app.db.unit_of_work import AbstractUnitOfWork

# Registration must request a discoverable (resident) credential -- issue
# #267 moved passkey login onto discoverable credentials exclusively
# (app.auth.passkey_service.login_passkey_begin no longer sends
# allowCredentials), so a credential minted via invite redemption has to be
# resident or it would be unusable for login afterwards. Both the real
# redemption path and its decoy below must request the identical shape, per
# the #239 convention this module already follows for the challenge itself.
_DISCOVERABLE_CREDENTIAL = AuthenticatorSelectionCriteria(
    resident_key=ResidentKeyRequirement.REQUIRED,
    user_verification=UserVerificationRequirement.REQUIRED,
)

# How long a minted invite stays redeemable.
INVITE_EXPIRY_HOURS = 72

# Generic, indistinguishable failure -- must never leak *why* redemption
# failed (unknown token vs expired vs revoked vs already-redeemed vs bad
# credential), matching the #239/#255 convention in passkey_service.
_AUTH_FAILED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication failed"
)


def generate_invite_token() -> str:
    return secrets.token_urlsafe(32)


def hash_invite_token(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode()).hexdigest()


def invite_expiry() -> datetime:
    return datetime.now(UTC) + timedelta(hours=INVITE_EXPIRY_HOURS)


def invite_link(token: str) -> str:
    return f"{config.WEBAUTHN_ORIGIN}/invite/{token}"


def invite_status(
    record: dict[str, Any],
) -> Literal["pending", "redeemed", "expired", "revoked"]:
    if record.get("revoked_at") is not None:
        return "revoked"
    if record.get("redeemed_at") is not None:
        return "redeemed"
    expires_at = record["expires_at"]
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at < datetime.now(UTC):
        return "expired"
    return "pending"


def _is_usable(record: dict[str, Any]) -> bool:
    return invite_status(record) == "pending"


async def _email_has_user(email: str, uow: AbstractUnitOfWork) -> bool:
    result = await uow.session.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none() is not None


async def mint_invite(
    payload: InviteCreateRequest,
    issued_by: str,
    repo: AbstractInviteRepository,
    uow: AbstractUnitOfWork,
) -> dict[str, Any]:
    if await _email_has_user(payload.email, uow):
        # An invite must never be a way to attach a credential to a live
        # account: the link-holder would gain access and the account's owner
        # would never be told. Admin recovery tokens cover the legitimate
        # "this person needs to get back in" case, with the audit trail and
        # the deliberate admin action that implies.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "An account already exists for that email. Issue an admin "
                "recovery token instead of an invite."
            ),
        )

    plaintext = generate_invite_token()
    record = await repo.add(
        {
            "email": payload.email,
            "first_name": payload.first_name,
            "surname": payload.surname,
            "token_hash": hash_invite_token(plaintext),
            "expires_at": invite_expiry(),
            "issued_by": issued_by,
        }
    )
    return {**record, "token": plaintext, "link": invite_link(plaintext)}


def _decoy_response(token: str) -> dict:
    """Decoy for any unusable token (unknown/expired/revoked/redeemed),
    shaped exactly like the real begin response -- see passkey_service's
    `_decoy_register_response` for why the challenge must come from
    py_webauthn rather than being constructed here.

    user_id is derived via the shared `_decoy_user_id` helper (issue #300):
    invite_redeem_begin's real path returns the persisted User.id, stable for
    as long as the token stays unredeemed, while this decoy used to mint a
    fresh uuid4() per call -- the identical real-stable/decoy-random
    asymmetry that made register_passkey_begin's decoy an enumeration oracle
    (see passkey_service._decoy_user_id's docstring for the full reasoning).
    Keyed by the raw token, not a normalised form: unlike an email, a token
    is an opaque secret.token_urlsafe() value with no case-insensitive
    convention to respect, so normalising it would only create new
    collisions between otherwise-distinct tokens.

    user_name is derived from the same helper for the same reason. The real
    path returns the invitee's persisted email, which never moves for a given
    token; a fresh uuid4() local part here would leave the #300 oracle fully
    intact on this field after closing it on user_id, since a caller can
    compare either one across two calls. Both fields must be stable, or
    neither is.
    """
    decoy_id = _decoy_user_id(token)
    options = webauthn.generate_registration_options(
        rp_id=config.WEBAUTHN_RP_ID,
        rp_name="Kendo Dojo",
        user_id=decoy_id.encode("utf-8"),
        user_name=f"{decoy_id}@invite.invalid",
        authenticator_selection=_DISCOVERABLE_CREDENTIAL,
    )
    return {"publicKey": json.loads(options_to_json(options))}


async def _create_invited_user(email: str, uow: AbstractUnitOfWork) -> User | None:
    """Create the invited account, or None if the email already has one.

    An account can appear between minting and redemption, so refusing at mint
    time is not enough on its own. Returning None here makes the redemption
    path treat it like any other unusable invite.
    """
    if await _email_has_user(email, uow):
        return None
    user = User(email=email, role="member", is_active=True)
    uow.session.add(user)
    await uow.session.flush()
    return user


async def invite_redeem_begin(token: str, uow: AbstractUnitOfWork) -> dict:
    repo = SqlInviteRepository(uow.session)
    record = await repo.get_by_token_hash(hash_invite_token(token))
    if record is None or not _is_usable(record):
        return _decoy_response(token)

    user = await _create_invited_user(record["email"], uow)
    if user is None:
        return _decoy_response(token)

    directory = member_directory_for(uow)
    await directory.ensure_member_for_email(
        record["email"], user.id, record["first_name"], record["surname"]
    )

    options = webauthn.generate_registration_options(
        rp_id=config.WEBAUTHN_RP_ID,
        rp_name="Kendo Dojo",
        user_id=user.id.encode("utf-8"),
        user_name=user.email,
        authenticator_selection=_DISCOVERABLE_CREDENTIAL,
    )
    user.pending_challenge = _encode_challenge(options.challenge)
    user.challenge_issued_at = datetime.now(UTC)
    await uow.commit()

    return {"publicKey": json.loads(options_to_json(options))}


async def invite_redeem_complete(
    payload: InviteRedeemCompleteRequest, uow: AbstractUnitOfWork
) -> PasskeyRegisterCompleteResponse:
    repo = SqlInviteRepository(uow.session)
    record = await repo.get_by_token_hash(hash_invite_token(payload.token))
    if record is None or not _is_usable(record):
        log_security_event("invite_redeemed", "failure")
        raise _AUTH_FAILED

    result = await uow.session.execute(
        select(User).where(User.email == record["email"])
    )
    user = result.scalar_one_or_none()
    if user is None:
        log_security_event("invite_redeemed", "failure")
        raise _AUTH_FAILED

    # An invite may only ever establish the FIRST credential on the account it
    # created. If the account already has a passkey it is somebody's live
    # account, and adding another silently would hand the link-holder access
    # its owner never agreed to.
    existing = await uow.session.execute(
        select(PasskeyCredential).where(PasskeyCredential.user_id == user.id)
    )
    if existing.scalars().first() is not None:
        log_security_event("invite_redeemed", "failure", user_id=user.id)
        raise _AUTH_FAILED

    if not user.pending_challenge or not user.challenge_issued_at:
        log_security_event("invite_redeemed", "failure", user_id=user.id)
        raise _AUTH_FAILED
    age = datetime.now(UTC) - user.challenge_issued_at.replace(tzinfo=UTC)
    if age > timedelta(seconds=config.WEBAUTHN_CHALLENGE_TTL_SECONDS):
        log_security_event("invite_redeemed", "failure", user_id=user.id)
        raise _AUTH_FAILED
    expected_challenge = _decode_challenge(user.pending_challenge)

    try:
        verified = webauthn.verify_registration_response(
            credential=_to_registration_credential(payload.credential),
            expected_challenge=expected_challenge,
            expected_rp_id=config.WEBAUTHN_RP_ID,
            expected_origin=config.WEBAUTHN_ORIGIN,
            # Enforce the userVerification="required" that
            # _DISCOVERABLE_CREDENTIAL asks for; py_webauthn skips the uv
            # check entirely without this. See
            # app.auth.passkey_service.register_passkey_complete.
            require_user_verification=True,
        )
    except Exception as exc:
        log_security_event("invite_redeemed", "failure", user_id=user.id)
        raise _AUTH_FAILED from exc

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
    if await repo.mark_redeemed(record["id"]) is None:
        # A concurrent redemption claimed the invite first. The conditional
        # update is the only point at which that is knowable, so refuse here
        # and let the uncommitted passkey roll back with the transaction.
        log_security_event("invite_redeemed", "failure", user_id=user.id)
        raise _AUTH_FAILED
    await uow.commit()

    log_security_event("invite_redeemed", "success", user_id=user.id)
    return PasskeyRegisterCompleteResponse(
        sub=user.id,
        email=user.email,
        role=user.role,  # type: ignore[arg-type]
        is_active=user.is_active,
        theme=user.theme,  # type: ignore[arg-type]
        show_nudge=True,
    )
