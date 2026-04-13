import base64
import json
from datetime import UTC, datetime, timedelta

import webauthn
from fastapi import HTTPException, status
from sqlalchemy import func, select
from webauthn import options_to_json
from webauthn.helpers.structs import (
    AuthenticationCredential,
    AuthenticatorAssertionResponse,
    AuthenticatorAttestationResponse,
    PublicKeyCredentialDescriptor,
    RegistrationCredential,
)

from app import config
from app.auth.aaguid import label_from_aaguid
from app.auth.db_models import PasskeyCredential, User
from app.auth.models import (
    PasskeyCredentialResponse,
    PasskeyLoginCompleteRequest,
    PasskeyRegisterCompleteRequest,
    TokenResponse,
    UserClaims,
)
from app.auth.token import encode_token
from app.db.unit_of_work import AbstractUnitOfWork

_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
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


async def _get_or_create_user(email: str, uow: AbstractUnitOfWork) -> User:
    result = await uow.session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None:
        count_result = await uow.session.execute(
            select(func.count()).select_from(User)
        )
        is_first_user = count_result.scalar_one() == 0
        role = "admin" if is_first_user else "member"
        user = User(
            email=email,
            hashed_password="",
            role=role,
            is_active=True,
        )
        uow.session.add(user)
        await uow.session.flush()
    return user


async def register_passkey_begin(email: str, uow: AbstractUnitOfWork) -> dict:
    user = await _get_or_create_user(email, uow)

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


async def register_passkey_complete(
    payload: PasskeyRegisterCompleteRequest, uow: AbstractUnitOfWork
) -> UserClaims:
    result = await uow.session.execute(
        select(User).where(User.email == payload.email)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise _NOT_FOUND

    if not user.pending_challenge or not user.challenge_issued_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No registration in progress",
        )
    age = datetime.now(UTC) - user.challenge_issued_at.replace(tzinfo=UTC)
    if age > timedelta(seconds=config.WEBAUTHN_CHALLENGE_TTL_SECONDS):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Registration challenge expired",
        )
    expected_challenge = _decode_challenge(user.pending_challenge)

    verified = webauthn.verify_registration_response(
        credential=_to_registration_credential(payload.credential),
        expected_challenge=expected_challenge,
        expected_rp_id=config.WEBAUTHN_RP_ID,
        expected_origin=config.WEBAUTHN_ORIGIN,
    )

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

    return UserClaims(
        sub=user.id,
        email=user.email,
        role=user.role,  # type: ignore[arg-type]
        is_active=user.is_active,
        theme=user.theme,  # type: ignore[arg-type]
    )


async def login_passkey_begin(email: str, uow: AbstractUnitOfWork) -> dict:
    result = await uow.session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None:
        raise _NOT_FOUND

    cred_result = await uow.session.execute(
        select(PasskeyCredential).where(PasskeyCredential.user_id == user.id)
    )
    credentials = cred_result.scalars().all()

    options = webauthn.generate_authentication_options(
        rp_id=config.WEBAUTHN_RP_ID,
        allow_credentials=[
            PublicKeyCredentialDescriptor(id=cred.credential_id)
            for cred in credentials
        ],
    )

    user.pending_challenge = _encode_challenge(options.challenge)
    user.challenge_issued_at = datetime.now(UTC)
    await uow.commit()

    return {"publicKey": json.loads(options_to_json(options))}


async def login_passkey_complete(
    payload: PasskeyLoginCompleteRequest, uow: AbstractUnitOfWork
) -> TokenResponse:
    result = await uow.session.execute(
        select(User).where(User.email == payload.email)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise _NOT_FOUND
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account deactivated",
        )

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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credential not found",
        )

    if not user.pending_challenge or not user.challenge_issued_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No login in progress",
        )
    age = datetime.now(UTC) - user.challenge_issued_at.replace(tzinfo=UTC)
    if age > timedelta(seconds=config.WEBAUTHN_CHALLENGE_TTL_SECONDS):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Login challenge expired",
        )
    expected_challenge = _decode_challenge(user.pending_challenge)

    verified = webauthn.verify_authentication_response(
        credential=_to_authentication_credential(payload.credential),
        expected_challenge=expected_challenge,
        expected_rp_id=config.WEBAUTHN_RP_ID,
        expected_origin=config.WEBAUTHN_ORIGIN,
        credential_public_key=stored_cred.public_key,
        credential_current_sign_count=stored_cred.sign_count,
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
    return TokenResponse(access_token=encode_token(claims))
