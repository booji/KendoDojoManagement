"""
Unit / integration tests for issue #4 — Session management.

Uses StubRepository pattern — NO real DB. Dependencies are overridden via
app.dependency_overrides to inject in-memory stubs.

Acceptance criteria exercised here:
  1. Session type table is seeded with "General Training" on first run
  2. Admin can create additional session types via POST /session-types
  3. Admin can create a recurring session template via POST /sessions/templates
  4. Session instances are generated from a template up to a configurable horizon
  5. Admin can create an ad-hoc session via POST /sessions
  6. Admin can cancel a single session instance without affecting its template
  7. GET /sessions returns upcoming sessions visible to authenticated users
"""

from __future__ import annotations

import uuid
from datetime import date
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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ADMIN = UserClaims(sub="admin-uuid", email="admin@dojo.test", role="admin", is_active=True)
_MEMBER = UserClaims(sub="member-uuid", email="member@dojo.test", role="member", is_active=True)


def _admin_override():
    return _ADMIN


def _member_override():
    return _MEMBER


# ---------------------------------------------------------------------------
# Stub repositories
# ---------------------------------------------------------------------------


class StubSessionTypeRepo:
    """In-memory stand-in for a SessionType repository."""

    def __init__(self, seed: bool = True) -> None:
        self._store: dict[str, dict[str, Any]] = {}
        if seed:
            seeded_id = str(uuid.uuid4())
            self._store[seeded_id] = {"id": seeded_id, "name": "General Training"}

    async def list(self) -> list[dict[str, Any]]:
        return list(self._store.values())

    async def get_by_name(self, name: str) -> dict[str, Any] | None:
        for item in self._store.values():
            if item["name"] == name:
                return item
        return None

    async def add(self, name: str) -> dict[str, Any]:
        existing = await self.get_by_name(name)
        if existing:
            raise ValueError(f"Session type '{name}' already exists")
        new_id = str(uuid.uuid4())
        record = {"id": new_id, "name": name}
        self._store[new_id] = record
        return record


class StubSessionTemplateRepo:
    """In-memory stand-in for a SessionTemplate repository."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    async def list(self) -> list[dict[str, Any]]:
        return list(self._store.values())

    async def get(self, template_id: str) -> dict[str, Any] | None:
        return self._store.get(template_id)

    async def add(self, data: dict[str, Any]) -> dict[str, Any]:
        new_id = str(uuid.uuid4())
        record = {"id": new_id, **data}
        self._store[new_id] = record
        return record


class StubSessionInstanceRepo:
    """In-memory stand-in for a SessionInstance repository."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    async def list_upcoming(self, as_of: date | None = None) -> list[dict[str, Any]]:
        now = as_of or date.today()
        return [
            s for s in self._store.values()
            if not s.get("cancelled", False) and date.fromisoformat(s["date"]) >= now
        ]

    async def get(self, instance_id: str) -> dict[str, Any] | None:
        return self._store.get(instance_id)

    async def add(self, data: dict[str, Any]) -> dict[str, Any]:
        new_id = str(uuid.uuid4())
        record = {"id": new_id, "cancelled": False, **data}
        self._store[new_id] = record
        return record

    async def generate_from_template(
        self, template: dict[str, Any], horizon: date
    ) -> list[dict[str, Any]]:
        """Generate instances from template up to the horizon date."""
        # Simple weekly recurrence for stub purposes
        from datetime import timedelta

        instances = []
        start = date.fromisoformat(template["start_date"])
        current = start
        while current <= horizon:
            record = await self.add(
                {
                    "template_id": template["id"],
                    "session_type_id": template["session_type_id"],
                    "date": current.isoformat(),
                    "start_time": template.get("start_time", "19:00"),
                    "duration_minutes": template.get("duration_minutes", 90),
                }
            )
            instances.append(record)
            current += timedelta(weeks=1)
        return instances

    async def cancel(self, instance_id: str) -> dict[str, Any] | None:
        record = self._store.get(instance_id)
        if record is None:
            return None
        record["cancelled"] = True
        return record


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def type_repo() -> StubSessionTypeRepo:
    repo = StubSessionTypeRepo(seed=True)
    app.dependency_overrides[get_session_type_repo] = lambda: repo
    return repo


@pytest.fixture()
def template_repo() -> StubSessionTemplateRepo:
    repo = StubSessionTemplateRepo()
    app.dependency_overrides[get_session_template_repo] = lambda: repo
    return repo


@pytest.fixture()
def instance_repo() -> StubSessionInstanceRepo:
    repo = StubSessionInstanceRepo()
    app.dependency_overrides[get_session_instance_repo] = lambda: repo
    return repo


# ---------------------------------------------------------------------------
# AC1 — Session type seeding: GET /session-types returns "General Training"
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_session_types_returns_general_training_by_default(type_repo) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get("/session-types")
    assert response.status_code == 200
    names = [st["name"] for st in response.json()]
    assert "General Training" in names


# ---------------------------------------------------------------------------
# AC2 — POST /session-types (admin only)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_admin_can_create_session_type(type_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.post("/session-types", json={"name": "Competition Prep"})
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Competition Prep"
    assert "id" in body


@pytest.mark.anyio
async def test_member_cannot_create_session_type(type_repo) -> None:
    """Members must receive 403 when attempting to create a session type."""
    from app.auth.token import encode_token

    member_claims = UserClaims(
        sub="member-uuid", email="m@dojo.test", role="member", is_active=True
    )
    token = encode_token(member_claims)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.post(
            "/session-types",
            json={"name": "Should Fail"},
            cookies={"access_token": token},
        )
    assert response.status_code == 403


@pytest.mark.anyio
async def test_create_session_type_missing_name_returns_422(type_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.post("/session-types", json={})
    assert response.status_code == 422


@pytest.mark.anyio
async def test_create_duplicate_session_type_returns_409(type_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.post("/session-types", json={"name": "Keiko"})
        response = await c.post("/session-types", json={"name": "Keiko"})
    assert response.status_code == 409


@pytest.mark.anyio
async def test_create_session_type_unauthenticated_returns_401(type_repo) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.post("/session-types", json={"name": "Shinai Kata"})
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# AC3 — POST /sessions/templates (admin only)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_admin_can_create_session_template(type_repo, template_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    type_id = list(type_repo._store.keys())[0]
    payload = {
        "session_type_id": type_id,
        "title": "Tuesday Evening Keiko",
        "start_date": "2026-05-06",
        "start_time": "19:00",
        "duration_minutes": 90,
        "recurrence": "weekly",
        "day_of_week": 1,  # Tuesday
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.post("/sessions/templates", json=payload)
    assert response.status_code == 201
    body = response.json()
    assert "id" in body
    assert body["title"] == "Tuesday Evening Keiko"


@pytest.mark.anyio
async def test_member_cannot_create_session_template(template_repo) -> None:
    from app.auth.token import encode_token

    member_claims = UserClaims(
        sub="member-uuid", email="m@dojo.test", role="member", is_active=True
    )
    token = encode_token(member_claims)
    payload = {
        "session_type_id": str(uuid.uuid4()),
        "title": "Attempt",
        "start_date": "2026-05-06",
        "start_time": "19:00",
        "duration_minutes": 90,
        "recurrence": "weekly",
        "day_of_week": 1,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.post(
            "/sessions/templates", json=payload, cookies={"access_token": token}
        )
    assert response.status_code == 403


@pytest.mark.anyio
async def test_create_session_template_missing_fields_returns_422(template_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.post("/sessions/templates", json={"title": "Incomplete"})
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# AC4 — POST /sessions/templates/{id}/generate — generates instances up to horizon
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_generate_creates_instances_up_to_horizon(
    type_repo, template_repo, instance_repo
) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    type_id = list(type_repo._store.keys())[0]

    # Create a template first
    template_payload = {
        "session_type_id": type_id,
        "title": "Weekly Thursday",
        "start_date": "2026-05-07",
        "start_time": "18:30",
        "duration_minutes": 90,
        "recurrence": "weekly",
        "day_of_week": 3,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        tmpl_resp = await c.post("/sessions/templates", json=template_payload)
    assert tmpl_resp.status_code == 201
    template_id = tmpl_resp.json()["id"]

    # Generate instances up to a horizon
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
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


@pytest.mark.anyio
async def test_generate_nonexistent_template_returns_404(
    template_repo, instance_repo
) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    fake_id = str(uuid.uuid4())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.post(
            f"/sessions/templates/{fake_id}/generate",
            json={"horizon": "2026-06-01"},
        )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# AC5 — POST /sessions (ad-hoc session, admin only)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_admin_can_create_adhoc_session(type_repo, instance_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    type_id = list(type_repo._store.keys())[0]
    payload = {
        "session_type_id": type_id,
        "date": "2026-06-15",
        "start_time": "10:00",
        "duration_minutes": 60,
        "notes": "Special summer session",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.post("/sessions", json=payload)
    assert response.status_code == 201
    body = response.json()
    assert "id" in body
    assert body["date"] == "2026-06-15"


@pytest.mark.anyio
async def test_member_cannot_create_adhoc_session(type_repo, instance_repo) -> None:
    from app.auth.token import encode_token

    member_claims = UserClaims(
        sub="member-uuid", email="m@dojo.test", role="member", is_active=True
    )
    token = encode_token(member_claims)
    payload = {
        "session_type_id": str(uuid.uuid4()),
        "date": "2026-06-15",
        "start_time": "10:00",
        "duration_minutes": 60,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.post(
            "/sessions", json=payload, cookies={"access_token": token}
        )
    assert response.status_code == 403


@pytest.mark.anyio
async def test_create_adhoc_session_missing_date_returns_422(instance_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.post(
            "/sessions",
            json={"session_type_id": str(uuid.uuid4()), "start_time": "10:00"},
        )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# AC6 — POST /sessions/{id}/cancel — cancels instance, template unchanged
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_admin_can_cancel_session_instance(type_repo, template_repo, instance_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    type_id = list(type_repo._store.keys())[0]

    # Create an ad-hoc session to cancel
    create_payload = {
        "session_type_id": type_id,
        "date": "2026-07-01",
        "start_time": "19:00",
        "duration_minutes": 90,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        create_resp = await c.post("/sessions", json=create_payload)
    assert create_resp.status_code == 201
    instance_id = create_resp.json()["id"]

    # Cancel it
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        cancel_resp = await c.post(f"/sessions/{instance_id}/cancel")
    assert cancel_resp.status_code == 200
    body = cancel_resp.json()
    assert body["cancelled"] is True
    assert body["id"] == instance_id


@pytest.mark.anyio
async def test_cancelling_instance_does_not_affect_template(
    type_repo, template_repo, instance_repo
) -> None:
    """After cancelling an instance, the template still exists and is unmodified."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    type_id = list(type_repo._store.keys())[0]

    # Create template
    tmpl_payload = {
        "session_type_id": type_id,
        "title": "Persistent Template",
        "start_date": "2026-08-06",
        "start_time": "19:00",
        "duration_minutes": 90,
        "recurrence": "weekly",
        "day_of_week": 3,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        tmpl_resp = await c.post("/sessions/templates", json=tmpl_payload)
    assert tmpl_resp.status_code == 201
    template_id = tmpl_resp.json()["id"]

    # Generate one instance
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        gen_resp = await c.post(
            f"/sessions/templates/{template_id}/generate",
            json={"horizon": "2026-08-13"},
        )
    assert gen_resp.status_code == 200
    instances = gen_resp.json()
    assert len(instances) >= 1
    instance_id = instances[0]["id"]

    # Cancel the instance
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.post(f"/sessions/{instance_id}/cancel")

    # Template must still be retrievable and unmodified
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        tmpl_get_resp = await c.get(f"/sessions/templates/{template_id}")
    assert tmpl_get_resp.status_code == 200
    assert tmpl_get_resp.json()["id"] == template_id


@pytest.mark.anyio
async def test_cancel_nonexistent_instance_returns_404(instance_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    fake_id = str(uuid.uuid4())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.post(f"/sessions/{fake_id}/cancel")
    assert response.status_code == 404


@pytest.mark.anyio
async def test_member_cannot_cancel_session_instance(type_repo, instance_repo) -> None:
    from app.auth.token import encode_token

    # Create an instance first using admin override
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    type_id = list(type_repo._store.keys())[0]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        create_resp = await c.post(
            "/sessions",
            json={
                "session_type_id": type_id,
                "date": "2026-09-01",
                "start_time": "19:00",
                "duration_minutes": 90,
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
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.post(
            f"/sessions/{instance_id}/cancel",
            cookies={"access_token": token},
        )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# AC7 — GET /sessions returns upcoming sessions for authenticated users
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_sessions_returns_upcoming_for_member(type_repo, instance_repo) -> None:
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    # Seed a future session directly in the stub
    future_date = "2099-01-01"
    await instance_repo.add(
        {
            "session_type_id": list(type_repo._store.keys())[0],
            "date": future_date,
            "start_time": "19:00",
            "duration_minutes": 90,
        }
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get("/sessions")
    assert response.status_code == 200
    sessions = response.json()
    assert isinstance(sessions, list)
    assert any(s["date"] == future_date for s in sessions)


@pytest.mark.anyio
async def test_get_sessions_unauthenticated_returns_401(instance_repo) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get("/sessions")
    assert response.status_code == 401


@pytest.mark.anyio
async def test_get_sessions_excludes_cancelled(type_repo, instance_repo) -> None:
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    type_id = list(type_repo._store.keys())[0]

    # Add a future session then cancel it
    inst = await instance_repo.add(
        {
            "session_type_id": type_id,
            "date": "2099-02-01",
            "start_time": "19:00",
            "duration_minutes": 90,
        }
    )
    await instance_repo.cancel(inst["id"])

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get("/sessions")
    assert response.status_code == 200
    sessions = response.json()
    ids = [s["id"] for s in sessions]
    assert inst["id"] not in ids
