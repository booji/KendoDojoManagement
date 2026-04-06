from typing import Annotated, Literal

import email_validator as _ev
from pydantic import BaseModel, BeforeValidator


def _validate_email(v: object) -> str:
    if not isinstance(v, str):
        raise ValueError("email must be a string")
    result = _ev.validate_email(
        v, check_deliverability=False, test_environment=True
    )
    return result.normalized


LenientEmail = Annotated[str, BeforeValidator(_validate_email)]


class UserClaims(BaseModel):
    sub: str  # user UUID
    email: str
    role: Literal["admin", "member"]
    is_active: bool
    theme: Literal["light", "dark", "system"] = "system"


class ThemeUpdate(BaseModel):
    theme: Literal["light", "dark", "system"]


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"


class RegisterRequest(BaseModel):
    email: LenientEmail
    password: str


class LoginRequest(BaseModel):
    email: LenientEmail
    password: str


class PasskeyBeginRequest(BaseModel):
    email: LenientEmail


class PasskeyCredentialResponse(BaseModel):
    id: str
    rawId: str
    response: dict
    type: str


class PasskeyRegisterCompleteRequest(BaseModel):
    email: LenientEmail
    credential: PasskeyCredentialResponse


class PasskeyLoginCompleteRequest(BaseModel):
    email: LenientEmail
    credential: PasskeyCredentialResponse
