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

Uses StubRepository pattern — NO real DB.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
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
    """In-memory stand-in for a SessionTemplate repository (issue #50 version)."""

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
    """
    In-memory stand-in for a SessionInstance repository (issue #50 version).

    Tracks instances by (template_id, date) to support idempotent generation.
    Supports list_in_range for date-bounded queries.
    """

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    def _existing_dates(self, template_id: str) -> set[str]:
        return {
            r["date"]
            for r in self._store.values()
            if r.get("template_id") == template_id
        }

    async def list(self) -> list[dict[str, Any]]:
        return list(self._store.values())

    async def list_upcoming(self, as_of: date | None = None) -> list[dict[str, Any]]:
        now = as_of or date.today()
        return [
            s
            for s in self._store.values()
            if not s.get("cancelled", False) and date.fromisoformat(s["date"]) >= now
        ]

    async def list_in_range(
        self, from_date: date, to_date: date
    ) -> list[dict[str, Any]]:
        return [
            s
            for s in self._store.values()
            if not s.get("cancelled", False)
            and from_date <= date.fromisoformat(s["date"]) <= to_date
        ]

    async def latest_date_for_template(self, template_id: str) -> date | None:
        dates = [
            date.fromisoformat(r["date"])
            for r in self._store.values()
            if r.get("template_id") == template_id and not r.get("cancelled", False)
        ]
        return max(dates) if dates else None

    async def get(self, instance_id: str) -> dict[str, Any] | None:
        return self._store.get(instance_id)

    async def add(self, data: dict[str, Any]) -> dict[str, Any]:
        new_id = str(uuid.uuid4())
        record = {
            "id": new_id,
            "cancelled": False,
            "location": None,
            "info": None,
            "coach_notes": None,
            "checkin_url": None,
            **data,
        }
        self._store[new_id] = record
        return record

    async def add_if_not_exists(self, data: dict[str, Any]) -> dict[str, Any] | None:
        """Add only if (template_id, date) is not already present. Returns None if skipped."""
        template_id = data.get("template_id")
        target_date = data.get("date")
        if template_id and target_date in self._existing_dates(template_id):
            return None
        return await self.add(data)

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
            assert (
                (b - a).days == 14
            ), f"Day-of-week {dow}: gap between {a} and {b} is {(b - a).days} days, expected 14"


# ---------------------------------------------------------------------------
# AC2 — generate_instances is idempotent
# ---------------------------------------------------------------------------


def test_generate_idempotent() -> None:
    """Calling generate_instances twice with the same template and horizon
    must produce no duplicate (template_id, date) pairs when persisted via
    add_if_not_exists."""
    import asyncio

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
    repo = StubSessionInstanceRepo()

    async def run():
        first_batch = generate_instances(template, horizon)
        for data in first_batch:
            await repo.add_if_not_exists(data)

        second_batch = generate_instances(template, horizon)
        for data in second_batch:
            await repo.add_if_not_exists(data)

    asyncio.run(run())

    all_instances = list(repo._store.values())
    dates = [r["date"] for r in all_instances]
    assert len(dates) == len(
        set(dates)
    ), f"Duplicate dates found after two generate calls: {sorted(dates)}"


# ---------------------------------------------------------------------------
# AC3 — rolling 3-month extension triggered when latest instance < 14 days away
# ---------------------------------------------------------------------------


async def test_rolling_extension_triggered(
    type_repo, template_repo, instance_repo
) -> None:
    """When the latest instance for a template is within 14 days of today,
    GET /sessions (or the generate endpoint) should auto-extend instances to
    3 months out.  After the call, at least one instance must exist beyond
    today + 14 days."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    type_id = list(type_repo._store.keys())[0]

    # Create a template with the new fields
    today = date.today()
    # start_date in the past so existing instances land near today
    start = today - timedelta(days=7)
    tmpl_payload = {
        "title": "Rolling Extension Test",
        "start_date": start.isoformat(),
        "segments": [
            {"start_time": "19:00", "duration_minutes": 90, "type_ids": [type_id]}
        ],
        "recurrence_days": [start.weekday()],
        "interval_weeks": 1,
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        tmpl_resp = await c.post("/sessions/templates", json=tmpl_payload)
    assert tmpl_resp.status_code == 201
    template_id = tmpl_resp.json()["id"]

    # Manually seed exactly ONE instance that falls within 14 days of today
    near_future = today + timedelta(days=7)
    await instance_repo.add(
        {
            "template_id": template_id,
            "title": "Rolling Extension Test",
            "date": near_future.isoformat(),
            "segments": [
                {
                    "start_time": "19:00",
                    "duration_minutes": 90,
                    "type_ids": [type_id],
                }
            ],
        }
    )

    # Hitting GET /sessions should trigger rolling extension
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/sessions")
    assert response.status_code == 200

    # After rolling extension, instances beyond today+14 must exist for this template
    three_months_out = today + timedelta(days=90)
    extended = [
        r
        for r in instance_repo._store.values()
        if r.get("template_id") == template_id
        and date.fromisoformat(r["date"]) > today + timedelta(days=14)
    ]
    assert (
        len(extended) > 0
    ), "Rolling extension did not generate instances beyond 14 days from today"


# ---------------------------------------------------------------------------
# AC4 — GET /sessions?from=&to= returns only sessions in range
# ---------------------------------------------------------------------------


async def test_list_sessions_with_date_range(type_repo, instance_repo) -> None:
    """GET /sessions?from=2025-01-01&to=2025-01-31 must return only instances
    whose date falls within [2025-01-01, 2025-01-31]."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    type_id = list(type_repo._store.keys())[0]

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

    Uses _MinimalInstanceRepo so the test exercises the router/model layer, not the stub."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    minimal_repo = _MinimalInstanceRepo()
    app.dependency_overrides[get_session_instance_repo] = lambda: minimal_repo
    type_id = list(type_repo._store.keys())[0]

    past_date = "2000-01-01"
    future_date = "2099-12-31"

    await minimal_repo.add(
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
    await minimal_repo.add(
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
        assert (
            "info" in session
        ), f"Field 'info' missing from session {session.get('id')}"
        assert (
            "coach_notes" in session
        ), f"Field 'coach_notes' missing from session {session.get('id')}"
        assert (
            "checkin_url" in session
        ), f"Field 'checkin_url' missing from session {session.get('id')}"


# ---------------------------------------------------------------------------
# AC6 — SessionInstance response includes new fields
# ---------------------------------------------------------------------------


class _MinimalInstanceRepo:
    """Minimal stub that stores only what is passed in — no injected new fields.
    Used to verify that the router/Pydantic models themselves expose the new fields."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    async def list(self) -> list[dict[str, Any]]:
        return list(self._store.values())

    async def list_upcoming(self, as_of: date | None = None) -> list[dict[str, Any]]:
        now = as_of or date.today()
        return [
            s
            for s in self._store.values()
            if not s.get("cancelled", False) and date.fromisoformat(s["date"]) >= now
        ]

    async def get(self, instance_id: str) -> dict[str, Any] | None:
        return self._store.get(instance_id)

    async def add(self, data: dict[str, Any]) -> dict[str, Any]:
        new_id = str(uuid.uuid4())
        # Only store what is passed — no new fields injected
        record = {"id": new_id, "cancelled": False, **data}
        self._store[new_id] = record
        return record

    async def cancel(self, instance_id: str) -> dict[str, Any] | None:
        record = self._store.get(instance_id)
        if record is None:
            return None
        record["cancelled"] = True
        return record


async def test_new_instance_fields(type_repo) -> None:
    """A created SessionInstance response must include location, info,
    coach_notes, and checkin_url fields (may be None).

    Uses a minimal stub that does NOT inject these fields, so the test
    exercises whether the router/Pydantic models emit them."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    minimal_repo = _MinimalInstanceRepo()
    app.dependency_overrides[get_session_instance_repo] = lambda: minimal_repo
    type_id = list(type_repo._store.keys())[0]

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
    assert (
        "coach_notes" in body
    ), "Field 'coach_notes' missing from SessionInstance response"
    assert (
        "checkin_url" in body
    ), "Field 'checkin_url' missing from SessionInstance response"


# ---------------------------------------------------------------------------
# AC7 — SessionTemplate response includes new fields
# ---------------------------------------------------------------------------


async def test_new_template_fields(type_repo, template_repo) -> None:
    """A created SessionTemplate response must include recurrence_days,
    interval_weeks, info, and coach_notes fields."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    type_id = list(type_repo._store.keys())[0]

    payload = {
        "title": "Multi-day Template",
        "start_date": "2026-01-06",
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

    assert (
        "recurrence_days" in body
    ), "Field 'recurrence_days' missing from template response"
    assert body["recurrence_days"] == [
        1,
        3,
    ], f"Expected recurrence_days=[1,3], got {body.get('recurrence_days')}"
    assert (
        "interval_weeks" in body
    ), "Field 'interval_weeks' missing from template response"
    assert (
        body["interval_weeks"] == 2
    ), f"Expected interval_weeks=2, got {body.get('interval_weeks')}"
    assert "info" in body, "Field 'info' missing from template response"
    assert "coach_notes" in body, "Field 'coach_notes' missing from template response"
