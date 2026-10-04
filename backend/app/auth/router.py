import os
import uuid
from typing import Annotated, Any, Literal

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.auth.accounts import account_for_email, account_for_member, sign_in_email
from app.auth.attempt_repository import AbstractAttemptRepository
from app.auth.db_models import Account
from app.auth.dependencies import (
    get_admin_token_repo,
    get_attempt_repo,
    get_invite_repo,
    get_passkey_repo,
    get_recovery_repo,
)
from app.auth.guards import REQUIRE_ADMIN, REQUIRE_MEMBER, require_passkey_enrolment
from app.auth.invite_repository import AbstractInviteRepository
from app.auth.invite_service import (
    invite_redeem_begin,
    invite_redeem_complete,
    invite_status,
    mint_invite,
)
from app.auth.member_directory import member_directory_for
from app.auth.models import (
    AccountClaims,
    InviteCreateRequest,
    InviteListItem,
    InviteMintResponse,
    InviteRedeemBeginRequest,
    InviteRedeemCompleteRequest,
    LenientEmail,
    PasskeyAddCompleteRequest,
    PasskeyBeginRequest,
    PasskeyLoginCompleteRequest,
    PasskeyRegisterCompleteRequest,
    PasskeyRegisterCompleteResponse,
)
from app.auth.passkey_repository import AbstractPasskeyRepository
from app.auth.passkey_service import (
    add_passkey_begin,
    add_passkey_complete,
    login_passkey_begin,
    login_passkey_complete,
    register_passkey_begin,
    register_passkey_complete,
)
from app.auth.rate_limiter import (
    PER_IP_LIMIT,
    limiter,
)
from app.auth.recovery_repository import (
    AbstractAdminTokenRepository,
    AbstractRecoveryRepository,
)
from app.auth.recovery_service import (
    admin_token_expiry,
    check_admin_token,
    generate_admin_token_plaintext,
    generate_recovery_codes,
    hash_admin_token,
    hash_codes,
    is_admin_token_valid,
)
from app.auth.session_cookie import (
    clear_session_cookie,
    set_session_cookie,
    set_theme_cookie,
)
from app.auth.token import encode_recovery_token, encode_token
from app.core.request_ip import client_ip
from app.core.security_logger import log_security_event
from app.db.unit_of_work import AbstractUnitOfWork
from app.dependencies import get_uow

router = APIRouter(prefix="/auth", tags=["auth"])

_ALLOW_TEST_AUTH = os.getenv("ALLOW_TEST_AUTH", "false").lower() == "true"


@router.post("/logout", status_code=200)
async def logout(response: Response) -> dict:
    clear_session_cookie(response)
    return {"detail": "logged out"}


@router.get("/me", response_model=AccountClaims)
async def me(
    claims: Annotated[AccountClaims, Depends(REQUIRE_MEMBER)],
) -> AccountClaims:
    return claims


@router.get("/admin-only", response_model=AccountClaims)
async def admin_only(
    claims: Annotated[AccountClaims, Depends(REQUIRE_ADMIN)],
) -> AccountClaims:
    return claims


@router.post("/register/passkey/begin")
@limiter.limit(PER_IP_LIMIT)
async def passkey_register_begin(
    request: Request,
    payload: PasskeyBeginRequest,
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> dict:
    return await register_passkey_begin(payload.email, uow)


@router.post("/register/passkey/complete", status_code=201)
@limiter.limit(PER_IP_LIMIT)
async def passkey_register_complete(
    request: Request,
    payload: PasskeyRegisterCompleteRequest,
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> PasskeyRegisterCompleteResponse:
    return await register_passkey_complete(payload, uow)


async def _enrolment_email(account: Account, uow: AbstractUnitOfWork) -> str:
    email = await sign_in_email(uow.session, account.id)
    if email is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return email


# Adding a passkey to the caller's own Account (#443). Unlike the ceremony
# above, the Account comes from the session or recovery token, never from a
# submitted email.
@router.post("/passkeys/register/begin")
@limiter.limit(PER_IP_LIMIT)
async def passkey_add_begin(
    request: Request,
    account: Annotated[Account, Depends(require_passkey_enrolment)],
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> dict:
    return await add_passkey_begin(account, await _enrolment_email(account, uow), uow)


@router.post("/passkeys/register/complete", status_code=201)
@limiter.limit(PER_IP_LIMIT)
async def passkey_add_complete(
    request: Request,
    payload: PasskeyAddCompleteRequest,
    account: Annotated[Account, Depends(require_passkey_enrolment)],
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> PasskeyRegisterCompleteResponse:
    email = await _enrolment_email(account, uow)
    return await add_passkey_complete(account, email, payload.credential, uow)


@router.get("/security-status")
async def security_status(
    claims: Annotated[AccountClaims, Depends(REQUIRE_MEMBER)],
    repo: Annotated[AbstractPasskeyRepository, Depends(get_passkey_repo)],
) -> dict[str, int]:
    count = await repo.count_for_user(claims.sub)
    return {"passkey_count": count}


@router.post("/login/passkey/begin")
@limiter.limit(PER_IP_LIMIT)
async def passkey_login_begin(
    request: Request,
    payload: PasskeyBeginRequest,
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> dict:
    return await login_passkey_begin(payload.email, uow)


@router.post("/login/passkey/complete")
@limiter.limit(PER_IP_LIMIT)
async def passkey_login_complete(
    request: Request,
    payload: PasskeyLoginCompleteRequest,
    response: Response,
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> dict:
    try:
        token_response = await login_passkey_complete(payload, uow)
    except Exception:
        log_security_event("login_passkey", "failure")
        raise
    set_session_cookie(response, token_response.access_token)
    # Seed the readable theme cookie at login, not just on the preferences
    # endpoints: on a client that has never seen this user it is the only thing
    # that stops the shell painting the wrong theme and flipping (#324).
    set_theme_cookie(response, token_response.theme)
    return {"detail": "logged in"}


class _LabelUpdate(BaseModel):
    label: str = Field(..., min_length=1, max_length=255)


def _passkey_to_response(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": record["id"],
        "label": record["label"],
        "aaguid": record.get("aaguid"),
        "created_at": record["created_at"],
        "last_used_at": record.get("last_used_at"),
    }


@router.get("/passkeys")
async def list_passkeys(
    claims: Annotated[AccountClaims, Depends(REQUIRE_MEMBER)],
    repo: Annotated[AbstractPasskeyRepository, Depends(get_passkey_repo)],
) -> list[dict[str, Any]]:
    records = await repo.list_for_user(claims.sub)
    return [_passkey_to_response(r) for r in records]


@router.patch("/passkeys/{passkey_id}")
async def update_passkey_label(
    passkey_id: str,
    payload: _LabelUpdate,
    claims: Annotated[AccountClaims, Depends(REQUIRE_MEMBER)],
    repo: Annotated[AbstractPasskeyRepository, Depends(get_passkey_repo)],
) -> dict[str, Any]:
    record = await repo.get(passkey_id)
    if record is None or record["user_id"] != claims.sub:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    updated = await repo.update_label(passkey_id, claims.sub, payload.label)
    return _passkey_to_response(updated)  # type: ignore[arg-type]


@router.delete("/passkeys/{passkey_id}", status_code=204)
async def delete_passkey(
    passkey_id: str,
    claims: Annotated[AccountClaims, Depends(REQUIRE_MEMBER)],
    repo: Annotated[AbstractPasskeyRepository, Depends(get_passkey_repo)],
    recovery_repo: Annotated[AbstractRecoveryRepository, Depends(get_recovery_repo)],
) -> None:
    record = await repo.get(passkey_id)
    if record is None or record["user_id"] != claims.sub:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    count = await repo.count_for_user(claims.sub)
    if count <= 1:
        unused = await recovery_repo.count_unused(claims.sub)
        if unused == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete your only passkey without recovery codes",
            )
    await repo.delete(passkey_id, claims.sub)
    log_security_event("passkey_deleted", "success", user_id=claims.sub)


@router.post("/recovery/codes/generate", status_code=200)
async def generate_codes(
    claims: Annotated[AccountClaims, Depends(REQUIRE_MEMBER)],
    recovery_repo: Annotated[AbstractRecoveryRepository, Depends(get_recovery_repo)],
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> dict[str, Any]:
    if await recovery_repo.has_active_set(claims.sub):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Recovery codes already exist. Use regenerate to replace them.",
        )
    codes = generate_recovery_codes()
    hashes = hash_codes(codes)
    set_id = str(uuid.uuid4())
    await recovery_repo.create_codes(claims.sub, hashes, set_id)
    await uow.commit()
    return {"codes": codes}


@router.post("/recovery/codes/regenerate", status_code=200)
async def regenerate_codes(
    claims: Annotated[AccountClaims, Depends(REQUIRE_MEMBER)],
    recovery_repo: Annotated[AbstractRecoveryRepository, Depends(get_recovery_repo)],
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> dict[str, Any]:
    await recovery_repo.invalidate_all(claims.sub)
    codes = generate_recovery_codes()
    hashes = hash_codes(codes)
    set_id = str(uuid.uuid4())
    await recovery_repo.create_codes(claims.sub, hashes, set_id)
    await uow.commit()
    return {"codes": codes}


@router.get("/recovery/codes/status", status_code=200)
async def recovery_codes_status(
    claims: Annotated[AccountClaims, Depends(REQUIRE_MEMBER)],
    recovery_repo: Annotated[AbstractRecoveryRepository, Depends(get_recovery_repo)],
) -> dict[str, Any]:
    unused_count = await recovery_repo.count_unused(claims.sub)
    has_set = await recovery_repo.has_active_set(claims.sub)
    return {"unused_count": unused_count, "has_set": has_set}


class _RedeemRequest(BaseModel):
    email: LenientEmail
    code: str = Field(..., min_length=1, max_length=128)


@router.post("/recovery/redeem", status_code=200)
@limiter.limit(PER_IP_LIMIT)
async def redeem_recovery_code(
    request: Request,
    payload: _RedeemRequest,
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
    recovery_repo: Annotated[AbstractRecoveryRepository, Depends(get_recovery_repo)],
    attempt_repo: Annotated[AbstractAttemptRepository, Depends(get_attempt_repo)],
    admin_token_repo: Annotated[
        AbstractAdminTokenRepository, Depends(get_admin_token_repo)
    ],
) -> dict[str, str]:
    ip = client_ip(request)

    user = await account_for_email(uow.session, payload.email)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    failures = await attempt_repo.count_failures_since_last_success(user.id)
    if failures >= 5:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS)

    # Try recovery codes first
    codes = await recovery_repo.get_unused_codes_with_hash(user.id)
    matched_id: str | None = None
    for record in codes:
        if bcrypt.checkpw(payload.code.encode(), record["code_hash"].encode()):
            matched_id = record["id"]
            break

    if matched_id is not None:
        await recovery_repo.mark_used(matched_id)
        await attempt_repo.log_attempt(user.id, ip, success=True)
        await uow.commit()
        log_security_event("recovery_redeem", "success", user_id=user.id)
        token = encode_recovery_token(user_id=user.id, email=payload.email)
        return {"access_token": token, "token_type": "bearer"}

    # Try admin tokens
    admin_tokens = await admin_token_repo.get_unused_admin_tokens_for_user(user.id)
    matched_admin_id: str | None = None
    for record in admin_tokens:
        if check_admin_token(payload.code, record["token_hash"]):
            if is_admin_token_valid(record):
                matched_admin_id = record["id"]
            break

    if matched_admin_id is not None:
        await admin_token_repo.mark_admin_token_used(matched_admin_id)
        await attempt_repo.log_attempt(user.id, ip, success=True)
        await uow.commit()
        log_security_event("recovery_redeem", "success", user_id=user.id)
        token = encode_recovery_token(user_id=user.id, email=payload.email)
        return {"access_token": token, "token_type": "bearer"}

    await attempt_repo.log_attempt(user.id, ip, success=False)
    await uow.commit()
    log_security_event("recovery_redeem", "failure", user_id=user.id)
    if failures + 1 >= 5:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS)
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)


class _AdminTokenRequest(BaseModel):
    # The Member the admin is looking at (#445); the token is for their
    # Account.
    member_id: uuid.UUID


@router.post("/recovery/admin-token", status_code=200)
async def generate_admin_token(
    payload: _AdminTokenRequest,
    claims: Annotated[AccountClaims, Depends(REQUIRE_ADMIN)],
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
    admin_token_repo: Annotated[
        AbstractAdminTokenRepository, Depends(get_admin_token_repo)
    ],
) -> dict[str, str]:
    # A Member who never registered has no Account, and nothing to recover;
    # redemption refuses an inactive one, so a token for it would be a dud.
    user = await account_for_member(uow.session, str(payload.member_id))
    if user is None or not user.is_active:
        log_security_event(
            "admin_token_generated",
            "failure",
            user_id=claims.sub,
            detail={"target_member_id": str(payload.member_id)},
        )
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="There is no account to recover for this member",
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This member's account is deactivated, "
                "so a recovery token could not be used"
            ),
        )

    plaintext = generate_admin_token_plaintext()
    token_hash = hash_admin_token(plaintext)
    expires_at = admin_token_expiry()

    await admin_token_repo.create_admin_token(
        user_id=user.id,
        created_by_id=claims.sub,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    await uow.commit()
    log_security_event(
        "admin_token_generated",
        "success",
        user_id=claims.sub,
        detail={"target_user_id": user.id},
    )
    return {"token": plaintext}


# ---------------------------------------------------------------------------
# Admin-issued invite tokens (#257)
# ---------------------------------------------------------------------------


@router.post("/admin/invites", status_code=201, response_model=InviteMintResponse)
async def mint_invite_route(
    payload: InviteCreateRequest,
    claims: Annotated[AccountClaims, Depends(REQUIRE_ADMIN)],
    repo: Annotated[AbstractInviteRepository, Depends(get_invite_repo)],
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> InviteMintResponse:
    result = await mint_invite(payload, claims.sub, repo, uow)
    await uow.commit()
    log_security_event("invite_minted", "success", user_id=claims.sub)
    return InviteMintResponse(**result)


@router.get("/admin/invites", response_model=list[InviteListItem])
async def list_invites_route(
    claims: Annotated[AccountClaims, Depends(REQUIRE_ADMIN)],
    repo: Annotated[AbstractInviteRepository, Depends(get_invite_repo)],
) -> list[InviteListItem]:
    records = await repo.list()
    return [
        InviteListItem(**{**record, "status": invite_status(record)})
        for record in records
    ]


@router.post("/admin/invites/{invite_id}/revoke")
async def revoke_invite_route(
    invite_id: str,
    claims: Annotated[AccountClaims, Depends(REQUIRE_ADMIN)],
    repo: Annotated[AbstractInviteRepository, Depends(get_invite_repo)],
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> dict[str, Any]:
    existing = await repo.get(invite_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    updated = await repo.mark_revoked(invite_id)
    await uow.commit()
    log_security_event("invite_revoked", "success", user_id=claims.sub)
    return {"id": updated["id"], "status": invite_status(updated)}  # type: ignore[index]


@router.post("/invites/redeem/begin")
@limiter.limit(PER_IP_LIMIT)
async def invite_redeem_begin_route(
    request: Request,
    payload: InviteRedeemBeginRequest,
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> dict:
    return await invite_redeem_begin(payload.token, uow)


@router.post("/invites/redeem/complete", status_code=201)
@limiter.limit(PER_IP_LIMIT)
async def invite_redeem_complete_route(
    request: Request,
    payload: InviteRedeemCompleteRequest,
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> PasskeyRegisterCompleteResponse:
    return await invite_redeem_complete(payload, uow)


# ---------------------------------------------------------------------------
# Test-only credential-free login
#
# This endpoint mints an admin session cookie for any email with no credential
# whatsoever. It exists so the Playwright suite can get an authenticated
# browser without a WebAuthn ceremony.
#
# It is registered *conditionally* rather than gated inside the handler: if the
# route does not exist in a production build, no env var, config mistake or
# future refactor of the handler body can turn it back into an auth bypass.
# ---------------------------------------------------------------------------

if _ALLOW_TEST_AUTH:

    class _TestLoginRequest(BaseModel):
        email: LenientEmail
        role: Literal["admin", "member"] = "admin"
        # e2e helpers forge tokens before any row exists; passing the forged
        # subject makes the Account it names real, so the two agree.
        sub: str | None = None
        first_name: str = "Test"
        surname: str = "User"

    @router.post("/login/test", status_code=200)
    async def test_login(
        payload: _TestLoginRequest,
        response: Response,
        uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
    ) -> dict:
        """Create-or-get a Member and its Account, and return a JWT cookie.

        Test builds only. Every Account belongs to a Member (#432), so the
        Member is created too when the email has none.
        """
        user = await account_for_email(uow.session, payload.email)
        if user is None:
            member_id = await member_directory_for(uow).ensure_member(
                payload.email, payload.first_name, payload.surname
            )
            user = Account(
                id=payload.sub or str(uuid.uuid4()),
                member_id=member_id,
                role=payload.role,
                is_active=True,
            )
            uow.session.add(user)
            await uow.session.flush()
        await uow.commit()
        token = encode_token(
            AccountClaims(
                sub=user.id,
                email=payload.email,
                role=user.role,
                is_active=user.is_active,
            )
        )
        set_session_cookie(response, token)
        set_theme_cookie(response, user.theme)
        return {"detail": "logged in", "sub": user.id}
