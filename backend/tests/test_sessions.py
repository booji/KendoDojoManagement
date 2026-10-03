"""
Unit / integration tests for issue #4 — Session management.

NO real DB: the shared in-memory fakes stand in. Dependencies are overridden via
app.dependency_overrides to inject in-memory stubs.

Acceptance criteria exercised here:
  1. Session type table is seeded with "General Training" on first run
  2. Admin can create additional session types via POST /session-types
  3. Admin can create a recurring session template via POST /sessions/templates
  4. Session instances are generated from a template up to a configurable horizon
  5. Admin can create an ad-hoc session via POST /sessions
  6. Admin can cancel a single session instance without affecting its template
  7. GET /sessions returns upcoming sessions visible to authenticated users

Updated for issue #174 — sessions (instance and template) now carry a
`segments` array instead of a single session_type_id/start_time/duration.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.guards import REQUIRE_ADMIN, REQUIRE_MEMBER
from app.auth.models import UserClaims
from app.main import app
from app.sessions.dependencies import (
    get_session_instance_repo,
    get_session_template_repo,
    get_session_type_repo,
)
from tests.fake_repositories import (
    InMemorySessionInstanceRepository,
    InMemorySessionTemplateRepository,
    InMemorySessionTypeRepository,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ADMIN = UserClaims(
    sub="admin-uuid", email="admin@dojo.test", role="admin", is_active=True
)
_MEMBER = UserClaims(
    sub="member-uuid", email="member@dojo.test", role="member", is_active=True
)


def _admin_override():
    return _ADMIN


def _member_override():
    return _MEMBER


def _one_segment(type_id: str, **overrides: Any) -> dict[str, Any]:
    segment = {
        "start_time": "19:00",
        "duration_minutes": 90,
        "type_ids": [type_id],
    }
    segment.update(overrides)
    return segment


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def type_repo() -> InMemorySessionTypeRepository:
    repo = InMemorySessionTypeRepository([{"name": "General Training"}])
    app.dependency_overrides[get_session_type_repo] = lambda: repo
    return repo


@pytest.fixture()
def template_repo() -> InMemorySessionTemplateRepository:
    repo = InMemorySessionTemplateRepository()
    app.dependency_overrides[get_session_template_repo] = lambda: repo
    return repo


@pytest.fixture()
def instance_repo() -> InMemorySessionInstanceRepository:
    repo = InMemorySessionInstanceRepository()
    app.dependency_overrides[get_session_instance_repo] = lambda: repo
    return repo


# ---------------------------------------------------------------------------
# AC1 — Session type seeding: GET /session-types returns "General Training"
# ---------------------------------------------------------------------------


async def test_get_session_types_returns_general_training_by_default(type_repo) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/session-types")
    assert response.status_code == 200
    names = [st["name"] for st in response.json()]
    assert "General Training" in names


# ---------------------------------------------------------------------------
# AC2 — POST /session-types (admin only)
# ---------------------------------------------------------------------------


async def test_admin_can_create_session_type(type_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post("/session-types", json={"name": "Competition Prep"})
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Competition Prep"
    assert "id" in body


async def test_member_cannot_create_session_type(type_repo) -> None:
    """Members must receive 403 when attempting to create a session type."""
    from app.auth.token import encode_token

    member_claims = UserClaims(
        sub="member-uuid", email="m@dojo.test", role="member", is_active=True
    )
    token = encode_token(member_claims)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/session-types",
            json={"name": "Should Fail"},
            cookies={"access_token": token},
        )
    assert response.status_code == 403


async def test_create_session_type_missing_name_returns_422(type_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post("/session-types", json={})
    assert response.status_code == 422


async def test_create_duplicate_session_type_returns_409(type_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        await c.post("/session-types", json={"name": "Keiko"})
        response = await c.post("/session-types", json={"name": "Keiko"})
    assert response.status_code == 409


async def test_create_session_type_unauthenticated_returns_401(type_repo) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post("/session-types", json={"name": "Shinai Kata"})
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# AC3 — POST /sessions/templates (admin only)
# ---------------------------------------------------------------------------


async def test_admin_can_create_session_template(
    type_repo, template_repo, instance_repo
) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    type_id = (await type_repo.list())[0]["id"]
    payload = {
        "title": "Tuesday Evening Keiko",
        "start_date": "2026-05-06",
        "end_date": "2026-06-06",
        "recurrence": "weekly",
        "day_of_week": 1,  # Tuesday
        "segments": [_one_segment(type_id)],
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post("/sessions/templates", json=payload)
    assert response.status_code == 201
    body = response.json()
    assert "id" in body
    assert body["title"] == "Tuesday Evening Keiko"


async def test_member_cannot_create_session_template(template_repo) -> None:
    from app.auth.token import encode_token

    member_claims = UserClaims(
        sub="member-uuid", email="m@dojo.test", role="member", is_active=True
    )
    token = encode_token(member_claims)
    payload = {
        "title": "Attempt",
        "start_date": "2026-05-06",
        "end_date": "2026-06-06",
        "recurrence": "weekly",
        "day_of_week": 1,
        "segments": [_one_segment(str(uuid.uuid4()))],
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/sessions/templates", json=payload, cookies={"access_token": token}
        )
    assert response.status_code == 403


async def test_create_session_template_missing_fields_returns_422(
    template_repo,
) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post("/sessions/templates", json={"title": "Incomplete"})
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# AC4 — POST /sessions/templates/{id}/generate — generates instances up to horizon
# ---------------------------------------------------------------------------


async def test_generate_creates_instances_up_to_horizon(
    type_repo, template_repo, instance_repo
) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    type_id = (await type_repo.list())[0]["id"]

    # Create a template first. end_date is set just past start_date so
    # creation only auto-generates the first occurrence, leaving the
    # /generate call below something new to produce up to its own horizon
    # (issue #258: POST /sessions/templates now generates its own
    # start_date..end_date range on write; /generate covers any additional
    # horizon requested on top of that).
    template_payload = {
        "title": "Weekly Thursday",
        "start_date": "2026-05-07",
        "end_date": "2026-05-08",
        "recurrence": "weekly",
        "day_of_week": 3,
        "segments": [_one_segment(type_id)],
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        tmpl_resp = await c.post("/sessions/templates", json=template_payload)
    assert tmpl_resp.status_code == 201
    template_id = tmpl_resp.json()["id"]

    # Generate instances up to a horizon
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            f"/sessions/templates/{template_id}/generate",
            json={"horizon": "2026-05-28"},
        )
    assert response.status_code == 200
    instances = response.json()
    assert isinstance(instances, list)
    assert len(instances) >= 1
    # All generated instances must be dated on or before horizon
    for inst in instances:
        assert inst["date"] <= "2026-05-28"


async def test_generate_nonexistent_template_returns_404(
    template_repo, instance_repo
) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    fake_id = str(uuid.uuid4())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            f"/sessions/templates/{fake_id}/generate",
            json={"horizon": "2026-06-01"},
        )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# AC5 — POST /sessions (ad-hoc session, admin only)
# ---------------------------------------------------------------------------


async def test_admin_can_create_adhoc_session(type_repo, instance_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    type_id = (await type_repo.list())[0]["id"]
    payload = {
        "title": "Summer Session",
        "date": "2026-06-15",
        "segments": [_one_segment(type_id, start_time="10:00", duration_minutes=60)],
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post("/sessions", json=payload)
    assert response.status_code == 201
    body = response.json()
    assert "id" in body
    assert body["date"] == "2026-06-15"
    # #430: info / coach_notes cover both audiences; there is no third field.
    assert "notes" not in body


@pytest.mark.parametrize("bad", ["2026-02-31", "not-a-date", "20260615"])
async def test_create_adhoc_session_rejects_a_date_that_is_not_real(
    type_repo, instance_repo, bad
) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    type_id = (await type_repo.list())[0]["id"]
    payload = {"title": "Keiko", "date": bad, "segments": [_one_segment(type_id)]}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post("/sessions", json=payload)
    assert response.status_code == 422
    assert await instance_repo.list() == []


async def test_member_cannot_create_adhoc_session(type_repo, instance_repo) -> None:
    from app.auth.token import encode_token

    member_claims = UserClaims(
        sub="member-uuid", email="m@dojo.test", role="member", is_active=True
    )
    token = encode_token(member_claims)
    payload = {
        "title": "Attempt",
        "date": "2026-06-15",
        "segments": [
            _one_segment(str(uuid.uuid4()), start_time="10:00", duration_minutes=60)
        ],
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/sessions", json=payload, cookies={"access_token": token}
        )
    assert response.status_code == 403


async def test_create_adhoc_session_missing_date_returns_422(instance_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/sessions",
            json={
                "title": "Missing Date",
                "segments": [_one_segment(str(uuid.uuid4()))],
            },
        )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# AC6 — POST /sessions/{id}/cancel — cancels instance, template unchanged
# ---------------------------------------------------------------------------


async def test_admin_can_cancel_session_instance(
    type_repo, template_repo, instance_repo
) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    type_id = (await type_repo.list())[0]["id"]

    # Create an ad-hoc session to cancel
    create_payload = {
        "title": "Cancel Me",
        "date": "2026-07-01",
        "segments": [_one_segment(type_id)],
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        create_resp = await c.post("/sessions", json=create_payload)
    assert create_resp.status_code == 201
    instance_id = create_resp.json()["id"]

    # Cancel it
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        cancel_resp = await c.post(f"/sessions/{instance_id}/cancel")
    assert cancel_resp.status_code == 200
    body = cancel_resp.json()
    assert body["cancelled"] is True
    assert body["id"] == instance_id


async def test_cancelling_instance_does_not_affect_template(
    type_repo, template_repo, instance_repo
) -> None:
    """After cancelling an instance, the template still exists and is unmodified."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    type_id = (await type_repo.list())[0]["id"]

    # Create template. end_date is just past start_date so creation only
    # auto-generates the first occurrence, leaving the /generate call below
    # something new to produce.
    tmpl_payload = {
        "title": "Persistent Template",
        "start_date": "2026-08-06",
        "end_date": "2026-08-07",
        "recurrence": "weekly",
        "day_of_week": 3,
        "segments": [_one_segment(type_id)],
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        tmpl_resp = await c.post("/sessions/templates", json=tmpl_payload)
    assert tmpl_resp.status_code == 201
    template_id = tmpl_resp.json()["id"]

    # Generate one instance
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        gen_resp = await c.post(
            f"/sessions/templates/{template_id}/generate",
            json={"horizon": "2026-08-13"},
        )
    assert gen_resp.status_code == 200
    instances = gen_resp.json()
    assert len(instances) >= 1
    instance_id = instances[0]["id"]

    # Cancel the instance
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        await c.post(f"/sessions/{instance_id}/cancel")

    # Template must still be retrievable and unmodified
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        tmpl_get_resp = await c.get(f"/sessions/templates/{template_id}")
    assert tmpl_get_resp.status_code == 200
    assert tmpl_get_resp.json()["id"] == template_id


async def test_cancel_nonexistent_instance_returns_404(instance_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    fake_id = str(uuid.uuid4())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(f"/sessions/{fake_id}/cancel")
    assert response.status_code == 404


async def test_member_cannot_cancel_session_instance(type_repo, instance_repo) -> None:
    from app.auth.token import encode_token

    # Create an instance first using admin override
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    type_id = (await type_repo.list())[0]["id"]
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        create_resp = await c.post(
            "/sessions",
            json={
                "title": "Member Cancel Attempt",
                "date": "2026-09-01",
                "segments": [_one_segment(type_id)],
            },
        )
    assert create_resp.status_code == 201
    instance_id = create_resp.json()["id"]

    # Now attempt cancel as member (remove admin override, use real member token)
    del app.dependency_overrides[REQUIRE_ADMIN]
    member_claims = UserClaims(
        sub="member-uuid", email="m@dojo.test", role="member", is_active=True
    )
    token = encode_token(member_claims)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            f"/sessions/{instance_id}/cancel",
            cookies={"access_token": token},
        )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# AC7 — GET /sessions returns upcoming sessions for authenticated users
# ---------------------------------------------------------------------------


async def test_get_sessions_returns_upcoming_for_member(
    type_repo, instance_repo
) -> None:
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    # Seed a future session directly in the stub
    future_date = "2099-01-01"
    await instance_repo.add(
        {
            "title": "Future Session",
            "date": future_date,
            "segments": [_one_segment((await type_repo.list())[0]["id"])],
        }
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/sessions")
    assert response.status_code == 200
    sessions = response.json()
    assert isinstance(sessions, list)
    assert any(s["date"] == future_date for s in sessions)


async def test_get_sessions_unauthenticated_returns_401(instance_repo) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/sessions")
    assert response.status_code == 401


async def test_get_sessions_excludes_cancelled(type_repo, instance_repo) -> None:
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    type_id = (await type_repo.list())[0]["id"]

    # Add a future session then cancel it
    inst = await instance_repo.add(
        {
            "title": "To Be Cancelled",
            "date": "2099-02-01",
            "segments": [_one_segment(type_id)],
        }
    )
    await instance_repo.cancel(inst["id"])

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/sessions")
    assert response.status_code == 200
    sessions = response.json()
    ids = [s["id"] for s in sessions]
    assert inst["id"] not in ids
