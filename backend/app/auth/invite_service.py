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
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import webauthn
from fastapi import HTTPException, status
from sqlalchemy import select
from webauthn import options_to_json

from app import config
from app.auth.aaguid import label_from_aaguid
from app.auth.db_models import PasskeyCredential, User
from app.auth.invite_repository import AbstractInviteRepository, SqlInviteRepository
from app.auth.member_directory import member_directory_for
from app.auth.models import (
    InviteRedeemCompleteRequest,
    PasskeyRegisterCompleteResponse,
)
from app.auth.passkey_service import (
    _decode_challenge,
    _encode_challenge,
    _to_registration_credential,
)
from app.core.security_logger import log_security_event
from app.db.unit_of_work import AbstractUnitOfWork

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


async def mint_invite(
    email: str, issued_by: str, repo: AbstractInviteRepository
) -> dict[str, Any]:
    plaintext = generate_invite_token()
    record = await repo.add(
        {
            "email": email,
            "token_hash": hash_invite_token(plaintext),
            "expires_at": invite_expiry(),
            "issued_by": issued_by,
        }
    )
    return {**record, "token": plaintext, "link": invite_link(plaintext)}


def _decoy_response() -> dict:
    """Decoy for any unusable token (unknown/expired/revoked/redeemed),
    shaped exactly like the real begin response -- see passkey_service's
    `_decoy_register_response` for why the challenge must come from
    py_webauthn rather than being constructed here."""
    options = webauthn.generate_registration_options(
        rp_id=config.WEBAUTHN_RP_ID,
        rp_name="Kendo Dojo",
        user_id=str(uuid.uuid4()).encode("utf-8"),
        user_name=f"{uuid.uuid4()}@invite.invalid",
    )
    return {"publicKey": json.loads(options_to_json(options))}


async def _get_or_create_invited_user(email: str, uow: AbstractUnitOfWork) -> User:
    result = await uow.session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(email=email, role="member", is_active=True)
        uow.session.add(user)
        await uow.session.flush()
    return user


async def invite_redeem_begin(token: str, uow: AbstractUnitOfWork) -> dict:
    repo = SqlInviteRepository(uow.session)
    record = await repo.get_by_token_hash(hash_invite_token(token))
    if record is None or not _is_usable(record):
        return _decoy_response()

    directory = member_directory_for(uow)
    user = await _get_or_create_invited_user(record["email"], uow)
    await directory.ensure_member_for_email(record["email"], user.id)

    options = webauthn.generate_registration_options(
        rp_id=config.WEBAUTHN_RP_ID,
        rp_name="Kendo Dojo",
        user_id=user.id.encode("utf-8"),
        user_name=user.email,
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
    await repo.mark_redeemed(record["id"])
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
