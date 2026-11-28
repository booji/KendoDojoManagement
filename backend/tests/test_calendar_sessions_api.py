"""
Backend unit tests for issue #55 — Calendar view API.

Tests that GET /sessions?from=&to= returns sessions in the requested date range
with the correct shape, and that admins see cancelled sessions while members do not.

Uses StubRepository pattern — NO real DB.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.guards import REQUIRE_MEMBER
from app.auth.schemas import AccountClaims
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
# Auth helpers
# ---------------------------------------------------------------------------

_ADMIN = AccountClaims(sub="admin-uuid", email="admin@dojo.test", role="admin")
_MEMBER = AccountClaims(sub="member-uuid", email="member@dojo.test", role="member")


def _admin_override():
    return _ADMIN


def _member_override():
    return _MEMBER


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def type_repo() -> InMemorySessionTypeRepository:
    repo = InMemorySessionTypeRepository()
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
# Helper: seed a session instance
# ---------------------------------------------------------------------------

_TYPE_ID = str(uuid.uuid4())


async def _seed_session(
    repo: InMemorySessionInstanceRepository,
    session_date: str,
    *,
    cancelled: bool = False,
    title: str | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "title": title or "Keiko",
        "date": session_date,
        "segments": [
            {
                "start_time": "19:00",
                "duration_minutes": 90,
                "type_ids": [_TYPE_ID],
            }
        ],
    }
    record = await repo.add(data)
    if cancelled:
        record = await repo.cancel(record["id"])
        assert record is not None
    return record


# ---------------------------------------------------------------------------
# AC9 — GET /sessions?from=&to= returns sessions in range with correct shape
# ---------------------------------------------------------------------------


async def test_range_query_returns_sessions_within_date_range(
    type_repo, template_repo, instance_repo
) -> None:
    """Sessions within the requested range are returned; outside-range sessions are not."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    inside = await _seed_session(instance_repo, "2099-06-15")
    await _seed_session(instance_repo, "2099-05-01")  # before range
    await _seed_session(instance_repo, "2099-07-01")  # after range

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get(
            "/sessions", params={"from": "2099-06-01", "to": "2099-06-30"}
        )

    assert response.status_code == 200
    sessions = response.json()
    ids = [s["id"] for s in sessions]
    assert inside["id"] in ids
    # outside-range sessions must not appear
    assert all("2099-06-01" <= s["date"] <= "2099-06-30" for s in sessions), (
        f"Some sessions outside range: {[s['date'] for s in sessions]}"
    )


async def test_range_query_response_has_required_fields(
    type_repo, template_repo, instance_repo
) -> None:
    """Each session in the range response has id, date, start_time, duration_minutes,
    cancelled, and segments fields."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    await _seed_session(instance_repo, "2099-06-10")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get(
            "/sessions", params={"from": "2099-06-01", "to": "2099-06-30"}
        )

    assert response.status_code == 200
    sessions = response.json()
    assert len(sessions) >= 1
    for s in sessions:
        assert "id" in s, f"Missing 'id' in {s}"
        assert "date" in s, f"Missing 'date' in {s}"
        assert "start_time" in s, f"Missing 'start_time' in {s}"
        assert "duration_minutes" in s, f"Missing 'duration_minutes' in {s}"
        assert "cancelled" in s, f"Missing 'cancelled' in {s}"
        assert "segments" in s, f"Missing 'segments' in {s}"


async def test_range_query_unauthenticated_returns_401(
    type_repo, template_repo, instance_repo
) -> None:
    """Unauthenticated requests to GET /sessions?from=&to= return 401."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get(
            "/sessions", params={"from": "2099-06-01", "to": "2099-06-30"}
        )

    assert response.status_code == 401


async def test_admin_range_query_includes_cancelled_sessions(
    type_repo, template_repo, instance_repo
) -> None:
    """Admin GET /sessions?from=&to= response includes cancelled sessions."""
    app.dependency_overrides[REQUIRE_MEMBER] = _admin_override

    active = await _seed_session(instance_repo, "2099-06-10")
    cancelled = await _seed_session(instance_repo, "2099-06-15", cancelled=True)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get(
            "/sessions", params={"from": "2099-06-01", "to": "2099-06-30"}
        )

    assert response.status_code == 200
    sessions = response.json()
    ids = [s["id"] for s in sessions]
    assert active["id"] in ids, "Active session missing from admin response"
    assert cancelled["id"] in ids, "Cancelled session missing from admin response"

    # Confirm cancelled flag is set correctly
    cancelled_in_response = next(s for s in sessions if s["id"] == cancelled["id"])
    assert cancelled_in_response["cancelled"] is True


async def test_member_range_query_excludes_cancelled_sessions(
    type_repo, template_repo, instance_repo
) -> None:
    """Member GET /sessions?from=&to= response excludes cancelled sessions."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    active = await _seed_session(instance_repo, "2099-06-10")
    cancelled = await _seed_session(instance_repo, "2099-06-15", cancelled=True)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get(
            "/sessions", params={"from": "2099-06-01", "to": "2099-06-30"}
        )

    assert response.status_code == 200
    sessions = response.json()
    ids = [s["id"] for s in sessions]
    assert active["id"] in ids, "Active session missing from member response"
    assert cancelled["id"] not in ids, "Cancelled session must not appear for members"
