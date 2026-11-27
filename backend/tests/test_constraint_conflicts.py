"""A request the #431 constraints refuse is a 409, never a 500.

Runs against PostgreSQL (db_client): what is under test is the database's
refusal reaching the client as a conflict.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.guards import REQUIRE_ADMIN
from app.auth.schemas import AccountClaims
from app.main import app

_ADMIN = AccountClaims(sub=str(uuid.uuid4()), email="a@dojo.test", role="admin")


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


async def test_any_other_integrity_error_is_still_a_server_error() -> None:
    # A foreign-key violation is a bug, not a conflict: the handler must not
    # dress it up as a 409. Called directly: the unknown federation_id that
    # used to provoke one through the API is now refused first (#586).
    from sqlalchemy.exc import IntegrityError

    from app.main import _constraint_conflict_handler

    exc = IntegrityError(
        "INSERT INTO member_federations ...",
        {},
        Exception(
            'insert or update on table "member_federations" violates foreign key '
            'constraint "member_federations_federation_id_fkey"'
        ),
    )

    with pytest.raises(IntegrityError, match="foreign key"):
        await _constraint_conflict_handler(None, exc)  # type: ignore[arg-type]


async def test_joining_an_unknown_federation_is_a_422(db_client) -> None:
    # #586: it used to reach the foreign key and come back a 500. The
    # federation is named in the body, not the path, so it is a 422.
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

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            f"/members/{member.id}/federations",
            json={"federation_id": str(uuid.uuid4()), "member_number": "N-1"},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "Federation not found"


async def test_a_slot_two_concurrent_extends_both_generate_is_a_conflict() -> None:
    # #578: two extends of one series can both pass the check-then-insert;
    # the slot constraint refuses the second, and that must be a 409. Called
    # directly: a single request cannot lose the race.
    import json

    from sqlalchemy.exc import IntegrityError

    from app.main import _constraint_conflict_handler

    exc = IntegrityError(
        "INSERT INTO session_instances ...",
        {},
        Exception(
            "duplicate key value violates unique constraint "
            '"uq_session_instances_template_slot"'
        ),
    )

    response = await _constraint_conflict_handler(None, exc)  # type: ignore[arg-type]

    assert response.status_code == 409
    assert "series" in json.loads(response.body)["detail"]
