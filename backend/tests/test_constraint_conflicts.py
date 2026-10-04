"""A request the #431 constraints refuse is a 409, never a 500.

Runs against PostgreSQL (db_client): what is under test is the database's
refusal reaching the client as a conflict.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.guards import REQUIRE_ADMIN
from app.auth.models import AccountClaims
from app.main import app

_ADMIN = AccountClaims(
    sub=str(uuid.uuid4()), email="a@dojo.test", role="admin", is_active=True
)


@pytest.fixture(autouse=True)
def admin():
    app.dependency_overrides[REQUIRE_ADMIN] = lambda: _ADMIN
    yield
    app.dependency_overrides.clear()


async def _post_twice(path: str, body: dict) -> tuple[int, int, dict]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        first = await c.post(path, json=body)
        second = await c.post(path, json=body)
    return first.status_code, second.status_code, second.json()


async def test_a_federation_name_already_taken_is_a_conflict(db_client) -> None:
    name = f"Federation {uuid.uuid4().hex[:8]}"
    first, second, body = await _post_twice("/federations", {"name": name})

    assert first == 201
    assert second == 409
    assert "name" in body["detail"]


async def test_joining_a_federation_twice_is_a_conflict(db_client) -> None:
    from app.federations.db_models import Federation
    from app.members.db_models import Member

    member = Member(
        id=str(uuid.uuid4()),
        first_name="Ai",
        surname="Sato",
        join_date="2026-01-01",
        membership_status="active",
        is_coach=False,
        is_first_aider=False,
    )
    federation = Federation(id=str(uuid.uuid4()), name=f"F {uuid.uuid4().hex[:8]}")
    db_client.add_all([member, federation])
    await db_client.flush()

    first, second, body = await _post_twice(
        f"/members/{member.id}/federations",
        {"federation_id": federation.id, "member_number": "N-1"},
    )

    assert first == 201
    assert second == 409
    assert "federation" in body["detail"]


async def test_any_other_integrity_error_is_still_a_server_error(db_client) -> None:
    # A foreign-key violation is a bug, not a conflict: the handler must not
    # dress it up as a 409.
    from sqlalchemy.exc import IntegrityError

    from app.members.db_models import Member

    member = Member(
        id=str(uuid.uuid4()),
        first_name="Ai",
        surname="Sato",
        join_date="2026-01-01",
        membership_status="active",
        is_coach=False,
        is_first_aider=False,
    )
    db_client.add(member)
    await db_client.flush()

    with pytest.raises(IntegrityError, match="foreign key"):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test/api"
        ) as c:
            await c.post(
                f"/members/{member.id}/federations",
                json={"federation_id": str(uuid.uuid4()), "member_number": "N-1"},
            )
