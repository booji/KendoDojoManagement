from datetime import datetime
from typing import Annotated, Literal

import email_validator as _ev
from pydantic import BaseModel, BeforeValidator, Field


def _validate_email(v: object) -> str:
    if not isinstance(v, str):
        raise ValueError("email must be a string")
    result = _ev.validate_email(v, check_deliverability=False, test_environment=True)
    return result.normalized


LenientEmail = Annotated[str, BeforeValidator(_validate_email)]


class UserClaims(BaseModel):
    sub: str  # user UUID
    email: str
    role: Literal["admin", "member"]
    is_active: bool
    theme: Literal["light", "dark", "system"] = "system"
    recovery_session: bool = False


class ThemeUpdate(BaseModel):
    theme: Literal["light", "dark", "system"]


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"


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


class PasskeyRegisterCompleteResponse(UserClaims):
    show_nudge: bool


# --- Invites (#257) ---------------------------------------------------------


class InviteCreateRequest(BaseModel):
    email: LenientEmail
    first_name: str = Field(..., min_length=1, max_length=100)
    surname: str = Field(..., min_length=1, max_length=100)


class InviteMintResponse(BaseModel):
    """Returned exactly once, at mint time -- the only place the plaintext
    invite token is ever exposed."""

    id: str
    email: str
    token: str
    link: str
    expires_at: datetime


class InviteListItem(BaseModel):
    id: str
    email: str
    first_name: str
    surname: str
    status: Literal["pending", "redeemed", "expired", "revoked"]
    issued_by: str | None
    expires_at: datetime
    redeemed_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class InviteRedeemBeginRequest(BaseModel):
    token: str = Field(..., min_length=1)


class InviteRedeemCompleteRequest(BaseModel):
    token: str = Field(..., min_length=1)
    credential: PasskeyCredentialResponse
