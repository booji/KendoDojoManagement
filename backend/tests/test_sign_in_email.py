"""The address an Account signs in with is its Member's email (#432).

There used to be two copies — `users.email` and `members.email` — and they
drifted: an admin changed a Member's email on MemberDetailPage and the Account
went on signing in with the old one. Now there is one copy, so the admin's
edit is the sign-in change.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert, select

from app.auth.db_models import Account, PasskeyCredential
from app.auth.guards import REQUIRE_ADMIN
from app.auth.models import AccountClaims
from app.main import app
from tests.account_support import seed_account

_CREDENTIAL_ID = b"sign-in-email-credential"
_CREDENTIAL_B64 = "c2lnbi1pbi1lbWFpbC1jcmVkZW50aWFs"
_ADMIN = AccountClaims(
    sub=str(uuid.uuid4()), email="sensei@dojo.test", role="admin", is_active=True
)


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


async def _sign_in(c: AsyncClient, email: str):
    begin = await c.post("/auth/login/passkey/begin", json={"email": email})
    assert begin.status_code == 200  # same shape whether or not email is known
    verified = MagicMock(credential_id=_CREDENTIAL_ID, new_sign_count=1)
    with patch("webauthn.verify_authentication_response", return_value=verified):
        return await c.post(
            "/auth/login/passkey/complete",
            json={
                "email": email,
                "credential": {
                    "id": _CREDENTIAL_B64,
                    "rawId": _CREDENTIAL_B64,
                    "response": {
                        "clientDataJSON": "dGVzdA",
                        "authenticatorData": "dGVzdA",
                        "signature": "dGVzdA",
                    },
                    "type": "public-key",
                },
            },
        )


async def _account_with_passkey(session, email: str) -> tuple[str, str]:
    """(account id, member id) for a signed-up Member with this email."""
    user_id = await seed_account(session, email)
    await session.execute(
        insert(PasskeyCredential).values(
            id=str(uuid.uuid4()),
            user_id=user_id,
            credential_id=_CREDENTIAL_ID,
            public_key=b"public-key",
            sign_count=0,
            created_at=datetime.now(UTC),
        )
    )
    member_id = (
        await session.execute(select(Account.member_id).where(Account.id == user_id))
    ).scalar_one()
    return user_id, member_id


async def test_an_admin_email_change_moves_sign_in_to_the_new_address(
    db_client,
) -> None:
    old, new = (
        f"old-{uuid.uuid4().hex[:6]}@dojo.test",
        f"new-{uuid.uuid4().hex[:6]}@dojo.test",
    )
    user_id, member_id = await _account_with_passkey(db_client, old)
    app.dependency_overrides[REQUIRE_ADMIN] = lambda: _ADMIN

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        edited = await c.put(f"/members/{member_id}", json={"email": new})
        assert edited.status_code == 200, edited.text

        assert (await _sign_in(c, old)).status_code == 401
        signed_in = await _sign_in(c, new)
        assert signed_in.status_code == 200, signed_in.text
        me = (await c.get("/auth/me")).json()

    assert (me["sub"], me["email"]) == (user_id, new)


async def test_an_admin_entered_email_is_stored_as_sign_in_will_look_it_up(
    db_client,
) -> None:
    """#432 review: sign-in normalises the address it is given (the domain is
    lower-cased), so the Member's copy must be stored the same way or the
    admin's edit locks the member out."""
    local = f"ken-{uuid.uuid4().hex[:6]}"
    _, member_id = await _account_with_passkey(db_client, f"{local}@dojo.test")
    app.dependency_overrides[REQUIRE_ADMIN] = lambda: _ADMIN

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        edited = await c.put(
            f"/members/{member_id}", json={"email": f"{local}@DOJO.Test"}
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["email"] == f"{local}@dojo.test"

        assert (await _sign_in(c, f"{local}@dojo.test")).status_code == 200
