"""
Tests for issue #174 — session segment model (parent PRD #172).

The session module is moving from a single type/time/duration per session to
a SEGMENT model: a session (instance or template) has one or more
SessionSegment rows, each with start_time, duration_minutes, optional
coach_notes, an ordered list of type_ids, and a position for display order.

Session itself loses session_type_id / start_time / duration_minutes and
gains a REQUIRED title. The create/read API is nested replace-on-write:
the payload carries the session plus a `segments` array.

Acceptance criteria exercised here:
  2. Session has a required title; session-level type/time/duration columns gone
  3. Server rejects: a session with no segments; a segment with no type;
     a segment with duration <= 0
  3b. Server accepts overlapping segments and repeated types across segments
  1. A session can be created/read via the nested `segments` payload with one
     segment, and the read response carries the derived envelope time plus the
     segment with its ordered type_ids

Uses StubRepository pattern — NO real DB. This exercises the route layer,
which does not yet support segments — so these tests are expected to fail
(422/AssertionError) until the feature is implemented. They MUST NOT touch
production code.
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
    get_session_type_repo,
)

# ---------------------------------------------------------------------------
# Auth helpers
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
#
# These mimic the CURRENT (pre-segment) repository shape. They deliberately
# do NOT support segments — the goal of these tests is to drive the
# segment-aware service/router layer that does not exist yet.
# ---------------------------------------------------------------------------


class StubSessionTypeRepo:
    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}
        seeded_id = str(uuid.uuid4())
        self._store[seeded_id] = {"id": seeded_id, "name": "General Training"}
        seeded_id_2 = str(uuid.uuid4())
        self._store[seeded_id_2] = {"id": seeded_id_2, "name": "Kata Practice"}

    async def list(self) -> list[dict[str, Any]]:
        return list(self._store.values())

    async def get_by_name(self, name: str) -> dict[str, Any] | None:
        for item in self._store.values():
            if item["name"] == name:
                return item
        return None

    async def add(self, name: str) -> dict[str, Any]:
        new_id = str(uuid.uuid4())
        record = {"id": new_id, "name": name}
        self._store[new_id] = record
        return record


class StubSessionInstanceRepo:
    """In-memory stand-in for a SessionInstance repository.

    NOTE: this stub stores whatever dict the route/service hands it. It has
    no special segment-aware behaviour — any nested-segment persistence and
    derivation logic is expected to live in the service/router layer being
    tested, not here.
    """

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

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
        record = {"id": new_id, "cancelled": False, **data}
        self._store[new_id] = record
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
    repo = StubSessionTypeRepo()
    app.dependency_overrides[get_session_type_repo] = lambda: repo
    return repo


@pytest.fixture()
def instance_repo() -> StubSessionInstanceRepo:
    repo = StubSessionInstanceRepo()
    app.dependency_overrides[get_session_instance_repo] = lambda: repo
    return repo


# ---------------------------------------------------------------------------
# AC1 — nested segments payload create + read
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_session_with_one_segment_then_read_back(
    type_repo, instance_repo
) -> None:
    """A session created via the nested `segments` payload with a single
    segment must be readable afterwards, with the derived envelope time and
    the segment (with its ordered type_ids) present in the response."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    app.dependency_overrides[REQUIRE_MEMBER] = _admin_override
    type_ids = [t["id"] for t in await type_repo.list()]

    payload = {
        "title": "Tuesday Evening Keiko",
        "date": "2026-06-30",
        "segments": [
            {
                "start_time": "19:00",
                "duration_minutes": 90,
                "coach_notes": "Focus on kirikaeshi",
                "type_ids": [type_ids[0]],
            }
        ],
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        create_resp = await c.post("/sessions", json=payload)
    assert create_resp.status_code == 201
    created = create_resp.json()
    assert created["title"] == "Tuesday Evening Keiko"
    assert "session_type_id" not in created
    assert "start_time" in created  # derived envelope value, not raw column
    assert "duration_minutes" in created  # derived from envelope
    assert len(created["segments"]) == 1
    assert created["segments"][0]["type_ids"] == [type_ids[0]]

    session_id = created["id"]
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        read_resp = await c.get(f"/sessions/{session_id}")
    assert read_resp.status_code == 200
    body = read_resp.json()
    assert body["title"] == "Tuesday Evening Keiko"
    # Derived envelope must match the single segment exactly
    assert body["start_time"] == "19:00"
    assert body["duration_minutes"] == 90
    assert len(body["segments"]) == 1
    segment = body["segments"][0]
    assert segment["start_time"] == "19:00"
    assert segment["duration_minutes"] == 90
    assert segment["type_ids"] == [type_ids[0]]


# ---------------------------------------------------------------------------
# AC2 — title required; legacy type/time/duration columns gone from session
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_session_missing_title_returns_422(
    type_repo, instance_repo
) -> None:
    """A session payload without a title must be rejected with 422."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    type_ids = [t["id"] for t in await type_repo.list()]
    payload = {
        "date": "2026-06-30",
        "segments": [
            {
                "start_time": "19:00",
                "duration_minutes": 90,
                "type_ids": [type_ids[0]],
            }
        ],
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post("/sessions", json=payload)
    assert response.status_code == 422


@pytest.mark.anyio
async def test_session_read_response_has_no_legacy_type_column(
    type_repo, instance_repo
) -> None:
    """The session-level `session_type_id` column is gone; type information
    only exists inside segments now."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    type_ids = [t["id"] for t in await type_repo.list()]
    payload = {
        "title": "No Legacy Column Session",
        "date": "2026-07-01",
        "segments": [
            {
                "start_time": "10:00",
                "duration_minutes": 60,
                "type_ids": [type_ids[0]],
            }
        ],
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        create_resp = await c.post("/sessions", json=payload)
    assert create_resp.status_code == 201
    body = create_resp.json()
    assert "session_type_id" not in body


# ---------------------------------------------------------------------------
# AC3 — validation: zero segments, segment with zero types, duration <= 0
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_session_with_zero_segments_returns_422(
    type_repo, instance_repo
) -> None:
    """A session payload with an empty `segments` array must be rejected."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    payload = {
        "title": "No Segments",
        "date": "2026-07-02",
        "segments": [],
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post("/sessions", json=payload)
    assert response.status_code == 422


@pytest.mark.anyio
async def test_create_session_with_segment_missing_types_returns_422(
    type_repo, instance_repo
) -> None:
    """A segment with an empty `type_ids` list must be rejected."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    payload = {
        "title": "Segment Without Type",
        "date": "2026-07-03",
        "segments": [
            {
                "start_time": "19:00",
                "duration_minutes": 60,
                "type_ids": [],
            }
        ],
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post("/sessions", json=payload)
    assert response.status_code == 422


@pytest.mark.anyio
async def test_create_session_with_nonpositive_duration_returns_422(
    type_repo, instance_repo
) -> None:
    """A segment with duration_minutes <= 0 must be rejected."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    type_ids = [t["id"] for t in await type_repo.list()]
    payload = {
        "title": "Zero Duration Segment",
        "date": "2026-07-04",
        "segments": [
            {
                "start_time": "19:00",
                "duration_minutes": 0,
                "type_ids": [type_ids[0]],
            }
        ],
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post("/sessions", json=payload)
    assert response.status_code == 422


@pytest.mark.anyio
async def test_create_session_with_negative_duration_returns_422(
    type_repo, instance_repo
) -> None:
    """A segment with a negative duration_minutes must be rejected."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    type_ids = [t["id"] for t in await type_repo.list()]
    payload = {
        "title": "Negative Duration Segment",
        "date": "2026-07-05",
        "segments": [
            {
                "start_time": "19:00",
                "duration_minutes": -15,
                "type_ids": [type_ids[0]],
            }
        ],
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post("/sessions", json=payload)
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# AC3b — overlapping segments and repeated types must be ACCEPTED
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_session_with_overlapping_segments_is_accepted(
    type_repo, instance_repo
) -> None:
    """Overlapping segment times are a valid scenario (e.g. parallel
    activities) and must be accepted, not rejected."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    type_ids = [t["id"] for t in await type_repo.list()]
    payload = {
        "title": "Parallel Activities",
        "date": "2026-07-06",
        "segments": [
            {
                "start_time": "19:00",
                "duration_minutes": 60,
                "type_ids": [type_ids[0]],
            },
            {
                "start_time": "19:15",
                "duration_minutes": 30,
                "type_ids": [type_ids[1]],
            },
        ],
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post("/sessions", json=payload)
    assert response.status_code == 201
    body = response.json()
    assert len(body["segments"]) == 2
    # Derived envelope: 19:00 -> 20:00 (max of 19:00+60=20:00, 19:15+30=19:45)
    assert body["start_time"] == "19:00"
    assert body["duration_minutes"] == 60


@pytest.mark.anyio
async def test_create_session_with_same_type_in_multiple_segments_is_accepted(
    type_repo, instance_repo
) -> None:
    """The same session type may legitimately appear in more than one
    segment of the same session — this must be accepted."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    type_ids = [t["id"] for t in await type_repo.list()]
    repeated_type = type_ids[0]
    payload = {
        "title": "Repeated Type Across Segments",
        "date": "2026-07-07",
        "segments": [
            {
                "start_time": "18:00",
                "duration_minutes": 30,
                "type_ids": [repeated_type],
            },
            {
                "start_time": "18:30",
                "duration_minutes": 30,
                "type_ids": [repeated_type],
            },
        ],
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post("/sessions", json=payload)
    assert response.status_code == 201
    body = response.json()
    assert len(body["segments"]) == 2
    assert body["segments"][0]["type_ids"] == [repeated_type]
    assert body["segments"][1]["type_ids"] == [repeated_type]


@pytest.mark.anyio
async def test_member_cannot_create_session_with_segments(
    type_repo, instance_repo
) -> None:
    """Members must not be able to create sessions, segment-based or not."""
    from app.auth.token import encode_token

    token = encode_token(_MEMBER)
    type_ids = [t["id"] for t in await type_repo.list()]
    payload = {
        "title": "Member Attempt",
        "date": "2026-07-08",
        "segments": [
            {
                "start_time": "19:00",
                "duration_minutes": 60,
                "type_ids": [type_ids[0]],
            }
        ],
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/sessions", json=payload, cookies={"access_token": token}
        )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Issue #190 — per-segment `coach_notes` removed entirely (unit tests, no DB)
#
# `coach_notes` remains a SESSION-level field (template/instance); only the
# per-SEGMENT `coach_notes` is being removed. `title` and `note` on segments
# are unaffected.
# ---------------------------------------------------------------------------


def test_segment_read_model_dump_has_no_coach_notes() -> None:
    """SegmentRead no longer carries a `coach_notes` field at all."""
    from app.sessions.models import SegmentRead

    segment = SegmentRead(
        id="seg-1",
        start_time="19:00",
        duration_minutes=60,
        title="Warm-up",
        note="Bring your own bokuto",
        type_ids=["type-1"],
    )
    dumped = segment.model_dump()
    assert "coach_notes" not in dumped


def test_segment_read_ignores_extra_coach_notes_key() -> None:
    """Passing a stray `coach_notes=` to SegmentRead must not surface on the
    model — Pydantic's default `extra='ignore'` behaviour, since the field no
    longer exists on the schema."""
    from app.sessions.models import SegmentRead

    segment = SegmentRead(
        id="seg-1",
        start_time="19:00",
        duration_minutes=60,
        type_ids=["type-1"],
        coach_notes="Focus on kirikaeshi",
    )
    assert not hasattr(segment, "coach_notes")
    assert "coach_notes" not in segment.model_dump()


def test_segment_create_has_no_coach_notes_field() -> None:
    """SegmentCreate no longer declares a `coach_notes` field."""
    from app.sessions.models import SegmentCreate

    assert "coach_notes" not in SegmentCreate.model_fields


def test_segment_read_has_no_coach_notes_field() -> None:
    """SegmentRead no longer declares a `coach_notes` field."""
    from app.sessions.models import SegmentRead

    assert "coach_notes" not in SegmentRead.model_fields


def test_segment_create_ignores_extra_coach_notes_key() -> None:
    """Passing `coach_notes=` into SegmentCreate must not raise and must not
    surface as an attribute — the field is gone, so it is treated as an
    ignored extra key."""
    from app.sessions.models import SegmentCreate

    segment = SegmentCreate(
        start_time="19:00",
        duration_minutes=60,
        type_ids=["type-1"],
        coach_notes="Focus on kirikaeshi",
    )
    assert not hasattr(segment, "coach_notes")
    assert "coach_notes" not in segment.model_dump()


def test_segment_create_title_and_note_still_present_and_normalized() -> None:
    """Segment `title`/`note` are unaffected by the coach_notes removal —
    still present, still whitespace-trimmed/None-coerced as before."""
    from app.sessions.models import SegmentCreate

    segment = SegmentCreate(
        start_time="19:00",
        duration_minutes=60,
        type_ids=["type-1"],
        title="  Warm-up  ",
        note="   ",
    )
    assert segment.title == "Warm-up"
    assert segment.note is None


def test_segment_read_title_and_note_still_present() -> None:
    """Segment `title`/`note` remain on SegmentRead."""
    from app.sessions.models import SegmentRead

    assert "title" in SegmentRead.model_fields
    assert "note" in SegmentRead.model_fields
    segment = SegmentRead(
        start_time="19:00",
        duration_minutes=60,
        type_ids=["type-1"],
        title="Warm-up",
        note="Bring your own bokuto",
    )
    assert segment.title == "Warm-up"
    assert segment.note == "Bring your own bokuto"


def test_session_template_segment_db_model_has_no_coach_notes_column() -> None:
    """The template-segment DB model no longer has a coach_notes column."""
    from app.sessions.db_models import SessionTemplateSegment

    assert not hasattr(SessionTemplateSegment, "coach_notes")
    assert "coach_notes" not in SessionTemplateSegment.__table__.columns


def test_session_instance_segment_db_model_has_no_coach_notes_column() -> None:
    """The instance-segment DB model no longer has a coach_notes column."""
    from app.sessions.db_models import SessionInstanceSegment

    assert not hasattr(SessionInstanceSegment, "coach_notes")
    assert "coach_notes" not in SessionInstanceSegment.__table__.columns


def test_session_template_create_coach_notes_still_round_trips() -> None:
    """Session-level coach_notes on the template is untouched by this issue."""
    from app.sessions.models import SegmentCreate, SessionTemplateCreate

    template = SessionTemplateCreate(
        title="Tuesday Keiko",
        start_date="2026-06-30",
        coach_notes="Bring extra shinai",
        segments=[
            SegmentCreate(start_time="19:00", duration_minutes=60, type_ids=["type-1"])
        ],
    )
    assert template.coach_notes == "Bring extra shinai"


def test_session_template_read_coach_notes_still_round_trips() -> None:
    from app.sessions.models import SessionTemplateRead

    template = SessionTemplateRead(
        id="tmpl-1",
        title="Tuesday Keiko",
        start_date="2026-06-30",
        start_time="19:00",
        duration_minutes=60,
        recurrence="weekly",
        coach_notes="Bring extra shinai",
    )
    assert template.coach_notes == "Bring extra shinai"


def test_session_template_update_coach_notes_still_present() -> None:
    from app.sessions.models import SessionTemplateUpdate

    assert "coach_notes" in SessionTemplateUpdate.model_fields
    update = SessionTemplateUpdate(coach_notes="Updated note")
    assert update.coach_notes == "Updated note"


def test_session_instance_create_coach_notes_still_round_trips() -> None:
    from app.sessions.models import SegmentCreate, SessionInstanceCreate

    instance = SessionInstanceCreate(
        title="Tuesday Keiko",
        date="2026-06-30",
        coach_notes="Bring extra shinai",
        segments=[
            SegmentCreate(start_time="19:00", duration_minutes=60, type_ids=["type-1"])
        ],
    )
    assert instance.coach_notes == "Bring extra shinai"


def test_session_instance_read_coach_notes_still_round_trips() -> None:
    from app.sessions.models import SessionInstanceRead

    instance = SessionInstanceRead(
        id="inst-1",
        title="Tuesday Keiko",
        date="2026-06-30",
        start_time="19:00",
        duration_minutes=60,
        coach_notes="Bring extra shinai",
    )
    assert instance.coach_notes == "Bring extra shinai"


def test_session_instance_update_coach_notes_still_present() -> None:
    from app.sessions.models import SessionInstanceUpdate

    assert "coach_notes" in SessionInstanceUpdate.model_fields
    update = SessionInstanceUpdate(coach_notes="Updated note")
    assert update.coach_notes == "Updated note"
