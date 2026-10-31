"""The last Admin who may sign in cannot be archived or suspended (#484).

Archiving or suspending a Member bars their Account from signing in, so doing
it to the last Admin would leave the dojo with nobody able to administer it,
and recovery refuses barred Members too.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.db_models import Account
from app.auth.guards import REQUIRE_ADMIN
from app.auth.models import AccountClaims
from app.main import app
from tests.account_support import seed_account


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


async def _sole_admin(session: AsyncSession, email: str) -> str:
    """Seed an Admin and make them the only one; the id of their Member."""
    # Inside the test's savepoint, so the demotion is rolled back afterwards.
    await session.execute(
        update(Account).where(Account.role == "admin").values(role="member")
    )
    account_id = await seed_account(session, email, role="admin")
    return (
        await session.execute(select(Account.member_id).where(Account.id == account_id))
    ).scalar_one()


async def _set_status(member_id: str, membership_status: str):
    app.dependency_overrides[REQUIRE_ADMIN] = lambda: AccountClaims(
        sub="acting-admin", email="acting@dojo.test", role="admin"
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        return await c.put(
            f"/members/{member_id}", json={"membership_status": membership_status}
        )


@pytest.mark.parametrize("membership_status", ["archived", "suspended"])
async def test_the_last_admin_cannot_be_barred_from_signing_in(
    db_client: AsyncSession, membership_status: str
) -> None:
    member_id = await _sole_admin(db_client, "only-admin@dojo.test")

    response = await _set_status(member_id, membership_status)

    assert response.status_code == 409
    assert response.json()["detail"] == "Cannot archive or suspend the last admin"


async def test_an_admin_who_is_not_the_last_can_be_archived(
    db_client: AsyncSession,
) -> None:
    member_id = await _sole_admin(db_client, "first-admin@dojo.test")
    await seed_account(db_client, "second-admin@dojo.test", role="admin")

    response = await _set_status(member_id, "archived")

    assert response.status_code == 200
    assert response.json()["membership_status"] == "archived"
