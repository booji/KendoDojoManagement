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


# What an Auth Session is for (#486): signing in, or a recovery token good
# only for enrolling one passkey.
AuthSessionKind = Literal["sign_in", "recovery"]


class AccountClaims(BaseModel):
    sub: str  # Account id
    email: str
    role: Literal["admin", "member"]
    is_active: bool
    recovery_session: bool = False


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    # The user's saved theme, carried out of the login ceremony so the caller
    # can seed the readable theme cookie without a second query (#324).
    theme: str = "system"


class PasskeyBeginRequest(BaseModel):
    email: LenientEmail


class SetupBeginRequest(PasskeyBeginRequest):
    """The first-admin claim names a kendoka, not just an address (#432):
    the claim creates their Member and Account together."""

    first_name: str = Field(..., min_length=1, max_length=100)
    surname: str = Field(..., min_length=1, max_length=100)


class PasskeyCredentialResponse(BaseModel):
    id: str
    rawId: str
    response: dict
    type: str


class PasskeyRegisterCompleteRequest(BaseModel):
    email: LenientEmail
    credential: PasskeyCredentialResponse


class PasskeyAddCompleteRequest(BaseModel):
    """No email: the Account comes from the caller's session (#443)."""

    credential: PasskeyCredentialResponse


class PasskeyLoginCompleteRequest(BaseModel):
    email: LenientEmail
    credential: PasskeyCredentialResponse


class PasskeyRegisterCompleteResponse(AccountClaims):
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
