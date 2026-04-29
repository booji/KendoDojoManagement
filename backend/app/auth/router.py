import uuid
from typing import Annotated, Any

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update

from app import config
from app.auth.attempt_repository import AbstractAttemptRepository
from app.auth.db_models import User
from app.auth.dependencies import (
    get_admin_token_repo,
    get_attempt_repo,
    get_passkey_repo,
    get_recovery_repo,
)
from app.auth.guards import REQUIRE_ADMIN, REQUIRE_MEMBER
from app.auth.models import (
    LenientEmail,
    LoginRequest,
    PasskeyBeginRequest,
    PasskeyLoginCompleteRequest,
    PasskeyRegisterCompleteRequest,
    PasskeyRegisterCompleteResponse,
    RegisterRequest,
    ThemeUpdate,
    UserClaims,
)
from app.auth.passkey_repository import AbstractPasskeyRepository
from app.auth.passkey_service import (
    login_passkey_begin,
    login_passkey_complete,
    register_passkey_begin,
    register_passkey_complete,
)
from app.auth.rate_limiter import (
    PER_IP_LIMIT,
    check_lockout,
    clear_lockout,
    limiter,
    record_failure,
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
from app.auth.service import register_user
from app.auth.token import encode_recovery_token
from app.db.unit_of_work import AbstractUnitOfWork
from app.dependencies import get_uow

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register/password", response_model=UserClaims, status_code=201)
async def register_password(
    payload: RegisterRequest,
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> UserClaims:
    return await register_user(payload, uow)


@router.post("/login/password", status_code=200)
@limiter.limit(PER_IP_LIMIT)
async def login_password(
    request: Request,
    payload: LoginRequest,
    response: Response,
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> dict:
    # Look up the user first so we can apply per-account lockout
    result = await uow.session.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    if user is not None:
        # Check lockout before verifying password
        if await check_lockout(user.id, uow.session):
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail="Account temporarily locked. Try again later.",
            )

    # Delegate to service for credential verification
    from app.auth.password import verify_password
    from app.auth.token import encode_token

    if user is None or not verify_password(payload.password, user.hashed_password):
        if user is not None:
            await record_failure(user.id, uow.session)
            await uow.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account deactivated",
        )

    # Successful login — clear any lockout state
    await clear_lockout(user.id, uow.session)
    await uow.commit()

    claims = UserClaims(
        sub=user.id,
        email=user.email,
        role=user.role,  # type: ignore[arg-type]
        is_active=user.is_active,
        theme=user.theme,  # type: ignore[arg-type]
    )
    from app.auth.models import TokenResponse

    token_response = TokenResponse(access_token=encode_token(claims))

    response.set_cookie(
        key="access_token",
        value=token_response.access_token,
        httponly=True,
        samesite="strict",
        secure=config.COOKIE_SECURE,
        max_age=60 * int(config.JWT_EXPIRE_MINUTES),
    )
    return {"detail": "logged in"}


@router.post("/logout", status_code=200)
async def logout(response: Response) -> dict:
    response.delete_cookie("access_token")
    return {"detail": "logged out"}


@router.get("/me", response_model=UserClaims)
async def me(
    claims: Annotated[UserClaims, Depends(REQUIRE_MEMBER)],
) -> UserClaims:
    return claims


@router.patch("/me/theme", response_model=UserClaims)
async def update_theme(
    payload: ThemeUpdate,
    claims: Annotated[UserClaims, Depends(REQUIRE_MEMBER)],
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> UserClaims:
    await uow.session.execute(
        update(User).where(User.id == claims.sub).values(theme=payload.theme)
    )
    await uow.commit()
    return UserClaims(
        sub=claims.sub,
        email=claims.email,
        role=claims.role,
        is_active=claims.is_active,
        theme=payload.theme,
    )


@router.get("/admin-only", response_model=UserClaims)
async def admin_only(
    claims: Annotated[UserClaims, Depends(REQUIRE_ADMIN)],
) -> UserClaims:
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


@router.get("/security-status")
async def security_status(
    claims: Annotated[UserClaims, Depends(REQUIRE_MEMBER)],
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
    token_response = await login_passkey_complete(payload, uow)
    response.set_cookie(
        key="access_token",
        value=token_response.access_token,
        httponly=True,
        samesite="strict",
        secure=config.COOKIE_SECURE,
        max_age=60 * int(config.JWT_EXPIRE_MINUTES),
    )
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
    claims: Annotated[UserClaims, Depends(REQUIRE_MEMBER)],
    repo: Annotated[AbstractPasskeyRepository, Depends(get_passkey_repo)],
) -> list[dict[str, Any]]:
    records = await repo.list_for_user(claims.sub)
    return [_passkey_to_response(r) for r in records]


@router.patch("/passkeys/{passkey_id}")
async def update_passkey_label(
    passkey_id: str,
    payload: _LabelUpdate,
    claims: Annotated[UserClaims, Depends(REQUIRE_MEMBER)],
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
    claims: Annotated[UserClaims, Depends(REQUIRE_MEMBER)],
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


@router.post("/recovery/codes/generate", status_code=200)
async def generate_codes(
    claims: Annotated[UserClaims, Depends(REQUIRE_MEMBER)],
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
    claims: Annotated[UserClaims, Depends(REQUIRE_MEMBER)],
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
    claims: Annotated[UserClaims, Depends(REQUIRE_MEMBER)],
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
    ip = request.client.host if request.client else "unknown"

    result = await uow.session.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()
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
        token = encode_recovery_token(user_id=user.id, email=user.email)
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
        token = encode_recovery_token(user_id=user.id, email=user.email)
        return {"access_token": token, "token_type": "bearer"}

    await attempt_repo.log_attempt(user.id, ip, success=False)
    await uow.commit()
    if failures + 1 >= 5:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS)
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)


class _AdminTokenRequest(BaseModel):
    user_id: str = Field(..., min_length=1)


@router.post("/recovery/admin-token", status_code=200)
async def generate_admin_token(
    payload: _AdminTokenRequest,
    claims: Annotated[UserClaims, Depends(REQUIRE_ADMIN)],
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
    admin_token_repo: Annotated[
        AbstractAdminTokenRepository, Depends(get_admin_token_repo)
    ],
) -> dict[str, str]:
    result = await uow.session.execute(select(User).where(User.id == payload.user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    plaintext = generate_admin_token_plaintext()
    token_hash = hash_admin_token(plaintext)
    expires_at = admin_token_expiry()

    await admin_token_repo.create_admin_token(
        user_id=payload.user_id,
        created_by_id=claims.sub,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    await uow.commit()
    return {"token": plaintext}
