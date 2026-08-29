"""
Failing tests for issue #50 — session recurrence overhaul.

Acceptance criteria covered:
  1. generate_instances handles recurrence_days=[1,3] and interval_weeks=2
  2. Calling generate_instances twice with the same template is idempotent
  3. Rolling 3-month extension is triggered when latest instance < 14 days away
  4. GET /sessions?from=YYYY-MM-DD&to=YYYY-MM-DD returns only sessions in range
  5. GET /sessions without params returns only upcoming sessions (existing behaviour)
  6. SessionInstance response includes location, info, coach_notes, checkin_url
  7. SessionTemplate response includes recurrence_days, interval_weeks, info, coach_notes

NO real DB: the shared in-memory fakes stand in for the repositories.
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
from app.sessions.service import generate_instances
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
# AC1 — generate_instances handles recurrence_days and interval_weeks
# ---------------------------------------------------------------------------


def test_generate_multi_day() -> None:
    """generate_instances with recurrence_days=[1,3] and interval_weeks=2 must
    produce instances only on Tuesdays (1) and Thursdays (3) with bi-weekly
    spacing between same-day occurrences."""
    template = {
        "id": str(uuid.uuid4()),
        "title": "Multi-day Template",
        "start_date": "2025-01-06",  # Monday 6 Jan 2025
        "segments": [
            {
                "start_time": "19:00",
                "duration_minutes": 90,
                "type_ids": [str(uuid.uuid4())],
            }
        ],
        "recurrence_days": [1, 3],  # Tuesday, Thursday
        "interval_weeks": 2,
    }
    horizon = date(2025, 2, 28)
    instances = generate_instances(template, horizon)

    assert len(instances) > 0, "Expected at least one generated instance"

    # All dates must be Tuesday (weekday==1) or Thursday (weekday==3)
    for inst in instances:
        d = date.fromisoformat(inst["date"])
        assert d.weekday() in {
            1,
            3,
        }, f"Instance on {inst['date']} is weekday {d.weekday()}, expected 1 or 3"

    # For each day-of-week, consecutive occurrences must be exactly 14 days apart

    sorted_dates = sorted(date.fromisoformat(i["date"]) for i in instances)
    by_dow: dict[int, list[date]] = {}
    for d in sorted_dates:
        by_dow.setdefault(d.weekday(), []).append(d)

    for dow, dates in by_dow.items():
        for a, b in zip(dates, dates[1:]):
            assert (b - a).days == 14, (
                f"Day-of-week {dow}: gap between {a} and {b} is {(b - a).days} days, expected 14"
            )


# ---------------------------------------------------------------------------
# AC2 — generate_instances is idempotent
# ---------------------------------------------------------------------------


async def test_generate_idempotent() -> None:
    """Generating twice against the same template and horizon must not produce
    a second instance on a date already generated.

    Idempotency belongs to the caller, not the repository: the router collects
    the dates already persisted for the template and passes them to
    generate_instances as existing_dates. This mirrors that, rather than
    leaning on an add_if_not_exists() method the repository interface has
    never declared.
    """
    template = {
        "id": str(uuid.uuid4()),
        "title": "Idempotent Template",
        "start_date": "2025-03-04",  # Tuesday
        "segments": [
            {
                "start_time": "19:00",
                "duration_minutes": 90,
                "type_ids": [str(uuid.uuid4())],
            }
        ],
        "recurrence_days": [1],  # Tuesday only
        "interval_weeks": 1,
    }
    horizon = date(2025, 3, 31)
    repo = InMemorySessionInstanceRepository()

    for _ in range(2):
        persisted = {r["date"] for r in await repo.list()}
        for data in generate_instances(template, horizon, persisted):
            await repo.add(data)

    dates = [r["date"] for r in await repo.list()]
    assert len(dates) == len(set(dates)), (
        f"Duplicate dates found after two generate calls: {sorted(dates)}"
    )


# ---------------------------------------------------------------------------
# AC3 — superseded by issue #258 (bounded recurrence): the rolling 3-month
# extension behaviour this suite used to cover was removed. See
# tests/test_session_template_end_date.py for the replacement contract
# (required end_date, POST/PATCH generate-on-write, POST .../extend).
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# AC4 — GET /sessions?from=&to= returns only sessions in range
# ---------------------------------------------------------------------------


async def test_list_sessions_with_date_range(type_repo, instance_repo) -> None:
    """GET /sessions?from=2025-01-01&to=2025-01-31 must return only instances
    whose date falls within [2025-01-01, 2025-01-31]."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    type_id = (await type_repo.list())[0]["id"]

    # Seed instances: one inside range, one before, one after
    def _segment() -> dict[str, Any]:
        return {"start_time": "19:00", "duration_minutes": 90, "type_ids": [type_id]}

    await instance_repo.add(
        {"title": "Keiko", "date": "2025-01-15", "segments": [_segment()]}
    )
    await instance_repo.add(
        {"title": "Keiko", "date": "2024-12-31", "segments": [_segment()]}
    )
    await instance_repo.add(
        {"title": "Keiko", "date": "2025-02-01", "segments": [_segment()]}
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get(
            "/sessions", params={"from": "2025-01-01", "to": "2025-01-31"}
        )

    assert response.status_code == 200
    sessions = response.json()
    dates = [s["date"] for s in sessions]

    assert "2025-01-15" in dates, "In-range date missing from response"
    assert "2024-12-31" not in dates, "Out-of-range (before) date present in response"
    assert "2025-02-01" not in dates, "Out-of-range (after) date present in response"


# ---------------------------------------------------------------------------
# AC5 — GET /sessions without params returns only upcoming sessions
# ---------------------------------------------------------------------------


async def test_list_sessions_no_params_returns_upcoming(type_repo) -> None:
    """GET /sessions without params must return only future (today or later) sessions
    AND each returned instance must include the new info/coach_notes/checkin_url fields
    (new fields required by issue #50).
    """
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    instance_repo = InMemorySessionInstanceRepository()
    app.dependency_overrides[get_session_instance_repo] = lambda: instance_repo
    type_id = (await type_repo.list())[0]["id"]

    past_date = "2000-01-01"
    future_date = "2099-12-31"

    await instance_repo.add(
        {
            "title": "Keiko",
            "date": past_date,
            "segments": [
                {
                    "start_time": "19:00",
                    "duration_minutes": 90,
                    "type_ids": [type_id],
                }
            ],
        }
    )
    await instance_repo.add(
        {
            "title": "Keiko",
            "date": future_date,
            "segments": [
                {
                    "start_time": "19:00",
                    "duration_minutes": 90,
                    "type_ids": [type_id],
                }
            ],
        }
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/sessions")

    assert response.status_code == 200
    sessions = response.json()
    dates = [s["date"] for s in sessions]

    assert future_date in dates, "Upcoming session missing from response"
    assert past_date not in dates, "Past session incorrectly included in response"

    # New fields required by issue #50 must appear on every returned instance
    for session in sessions:
        assert "info" in session, (
            f"Field 'info' missing from session {session.get('id')}"
        )
        assert "coach_notes" in session, (
            f"Field 'coach_notes' missing from session {session.get('id')}"
        )
        assert "checkin_url" in session, (
            f"Field 'checkin_url' missing from session {session.get('id')}"
        )


# ---------------------------------------------------------------------------
# AC6 — SessionInstance response includes new fields
# ---------------------------------------------------------------------------


async def test_new_instance_fields(type_repo) -> None:
    """A created SessionInstance response must include location, info,
    coach_notes, and checkin_url fields (may be None)."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    app.dependency_overrides[get_session_instance_repo] = lambda: (
        InMemorySessionInstanceRepository()
    )
    type_id = (await type_repo.list())[0]["id"]

    payload = {
        "title": "New Instance Fields",
        "date": "2099-06-15",
        "segments": [
            {"start_time": "19:00", "duration_minutes": 90, "type_ids": [type_id]}
        ],
    }

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post("/sessions", json=payload)

    assert response.status_code == 201
    body = response.json()

    assert "location" in body, "Field 'location' missing from SessionInstance response"
    assert "info" in body, "Field 'info' missing from SessionInstance response"
    assert "coach_notes" in body, (
        "Field 'coach_notes' missing from SessionInstance response"
    )
    assert "checkin_url" in body, (
        "Field 'checkin_url' missing from SessionInstance response"
    )


# ---------------------------------------------------------------------------
# AC7 — SessionTemplate response includes new fields
# ---------------------------------------------------------------------------


async def test_new_template_fields(type_repo, template_repo, instance_repo) -> None:
    """A created SessionTemplate response must include recurrence_days,
    interval_weeks, info, and coach_notes fields."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    type_id = (await type_repo.list())[0]["id"]

    payload = {
        "title": "Multi-day Template",
        "start_date": "2026-01-06",
        "end_date": "2026-03-06",
        "segments": [
            {"start_time": "19:00", "duration_minutes": 90, "type_ids": [type_id]}
        ],
        "recurrence_days": [1, 3],
        "interval_weeks": 2,
        "info": "Bring your bogu",
        "coach_notes": "Focus on men",
    }

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post("/sessions/templates", json=payload)

    assert response.status_code == 201
    body = response.json()

    assert "recurrence_days" in body, (
        "Field 'recurrence_days' missing from template response"
    )
    assert body["recurrence_days"] == [
        1,
        3,
    ], f"Expected recurrence_days=[1,3], got {body.get('recurrence_days')}"
    assert "interval_weeks" in body, (
        "Field 'interval_weeks' missing from template response"
    )
    assert body["interval_weeks"] == 2, (
        f"Expected interval_weeks=2, got {body.get('interval_weeks')}"
    )
    assert "info" in body, "Field 'info' missing from template response"
    assert "coach_notes" in body, "Field 'coach_notes' missing from template response"
