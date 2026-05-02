"""
Tests for issue #52 — iCal feed endpoint + checkin_url persistence.
Also covers pure unit tests for build_ical (issue #56).

Acceptance criteria:
  1. GET /sessions/ical returns 200 text/calendar without authentication
  2. Feed includes VEVENT blocks with title, date/time, duration, location, info
  3. coach_notes is never included in iCal output
  4. UIDs are stable (UUID of the session instance)
  5. generate_checkin_token persists the URL to SessionInstance.checkin_url using PUBLIC_ORIGIN
  6. All new behaviour covered by tests

Uses StubRepository pattern — NO real DB. Dependencies are overridden via
app.dependency_overrides to inject in-memory stubs.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.attendance.dependencies import (
    get_checkin_token_repo,
)
from app.attendance.dependencies import (
    get_session_instance_repo as get_attendance_session_instance_repo,
)
from app.auth.guards import REQUIRE_ADMIN
from app.auth.models import UserClaims
from app.main import app
from app.sessions.dependencies import get_session_instance_repo, get_session_type_repo

# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

_ADMIN = UserClaims(
    sub="admin-uuid", email="admin@dojo.test", role="admin", is_active=True
)


def _admin_override():
    return _ADMIN


# ---------------------------------------------------------------------------
# Stub repositories
# ---------------------------------------------------------------------------


class StubSessionInstanceRepo:
    """In-memory stand-in for a SessionInstance repository (sessions domain)."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    async def list_upcoming(self, as_of: date | None = None) -> list[dict[str, Any]]:
        now = as_of or date.today()
        return [
            s
            for s in self._store.values()
            if not s.get("cancelled", False) and date.fromisoformat(s["date"]) >= now
        ]

    async def list(self) -> list[dict[str, Any]]:
        return list(self._store.values())

    async def get(self, instance_id: str) -> dict[str, Any] | None:
        return self._store.get(instance_id)

    async def add(self, data: dict[str, Any]) -> dict[str, Any]:
        new_id = str(uuid.uuid4())
        record = {"id": new_id, "cancelled": False, **data}
        self._store[new_id] = record
        return record

    async def update(
        self, instance_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        record = self._store.get(instance_id)
        if record is None:
            return None
        record.update(data)
        return record


class StubAttendanceSessionInstanceRepo:
    """In-memory stand-in for SessionInstance as seen by the attendance domain."""

    def __init__(self, session_store: dict[str, dict[str, Any]]) -> None:
        self._store = session_store

    async def get(self, instance_id: str) -> dict[str, Any] | None:
        return self._store.get(instance_id)

    async def update(
        self, instance_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        record = self._store.get(instance_id)
        if record is None:
            return None
        record.update(data)
        return record


class StubSessionTypeRepository:
    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    def seed(self, type_id: str, name: str) -> dict[str, Any]:
        record = {"id": type_id, "name": name}
        self._store[type_id] = record
        return record

    async def list(self) -> list[dict[str, Any]]:
        return list(self._store.values())

    async def add(self, name: str) -> dict[str, Any]:
        new_id = str(uuid.uuid4())
        return self.seed(new_id, name)

    async def get_by_name(self, name: str) -> dict[str, Any] | None:
        return next((t for t in self._store.values() if t["name"] == name), None)

    async def update(self, type_id: str, colour: str | None) -> dict[str, Any] | None:
        record = self._store.get(type_id)
        if record is None:
            return None
        record["colour"] = colour
        return record


class StubCheckinTokenRepo:
    """In-memory stand-in for a CheckinToken repository."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    async def create(self, session_id: str, expires_at: Any) -> dict[str, Any]:
        import secrets

        token = secrets.token_urlsafe(16)
        record = {
            "token": token,
            "session_id": session_id,
            "expires_at": str(expires_at),
        }
        self._store[token] = record
        return record

    async def get(self, token: str) -> dict[str, Any] | None:
        return self._store.get(token)

    async def redeem(self, token: str) -> dict[str, Any] | None:
        record = self._store.get(token)
        if record is None:
            return None
        if record.get("used_at") is not None:
            raise ValueError("Token already used")
        record["used_at"] = "used"
        return record


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def instance_repo() -> StubSessionInstanceRepo:
    repo = StubSessionInstanceRepo()
    app.dependency_overrides[get_session_instance_repo] = lambda: repo
    return repo


@pytest.fixture()
def type_repo() -> StubSessionTypeRepository:
    repo = StubSessionTypeRepository()
    app.dependency_overrides[get_session_type_repo] = lambda: repo
    return repo


@pytest.fixture()
def checkin_token_repo() -> StubCheckinTokenRepo:
    repo = StubCheckinTokenRepo()
    app.dependency_overrides[get_checkin_token_repo] = lambda: repo
    return repo


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


async def _seed_instance(
    instance_repo: StubSessionInstanceRepo,
    *,
    title: str = "Weekly Keiko",
    session_type_id: str | None = None,
    instance_date: str = "2099-06-02",
    start_time: str = "19:00",
    duration_minutes: int = 90,
    location: str | None = "Main Hall",
    info: str | None = "Bring your shinai",
    coach_notes: str | None = None,
    cancelled: bool = False,
) -> dict[str, Any]:
    return await instance_repo.add(
        {
            "session_type_id": session_type_id or str(uuid.uuid4()),
            "title": title,
            "date": instance_date,
            "start_time": start_time,
            "duration_minutes": duration_minutes,
            "template_id": str(uuid.uuid4()),
            "location": location,
            "info": info,
            "coach_notes": coach_notes,
            "cancelled": cancelled,
            "checkin_url": None,
        }
    )


# ---------------------------------------------------------------------------
# AC1 — GET /sessions/ical returns 200 text/calendar without authentication
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_ical_endpoint_returns_200_no_auth(instance_repo) -> None:
    """GET /sessions/ical must return 200 with content-type text/calendar
    without requiring any authentication."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/sessions/ical")
    assert response.status_code == 200
    assert "text/calendar" in response.headers.get("content-type", "")


@pytest.mark.anyio
async def test_ical_endpoint_returns_valid_ical_structure(instance_repo, type_repo) -> None:
    """GET /sessions/ical must return a valid iCal document beginning with BEGIN:VCALENDAR."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/sessions/ical")
    assert response.status_code == 200
    body = response.text
    assert body.startswith("BEGIN:VCALENDAR")
    assert "END:VCALENDAR" in body
    assert "PRODID:-//KendoDojoManagement//EN" in body


# ---------------------------------------------------------------------------
# AC2 — Feed includes VEVENT blocks with title, date/time, duration, location, info
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_ical_feed_includes_vevent_with_summary(instance_repo, type_repo) -> None:
    """Each session instance must appear as a VEVENT with SUMMARY set to its session type name."""
    t = type_repo.seed(str(uuid.uuid4()), "Men Waza Practice")
    await _seed_instance(instance_repo, session_type_id=t["id"])
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/sessions/ical")
    body = response.text
    assert "BEGIN:VEVENT" in body
    assert "SUMMARY:Men Waza Practice" in body


@pytest.mark.anyio
async def test_ical_feed_includes_dtstart_and_dtend(instance_repo, type_repo) -> None:
    """VEVENT must include DTSTART and DTEND derived from date, start_time,
    and duration_minutes."""
    await _seed_instance(
        instance_repo,
        instance_date="2099-06-02",
        start_time="19:00",
        duration_minutes=90,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/sessions/ical")
    body = response.text
    # DTSTART should encode 2099-06-02 19:00 in iCal format
    assert "DTSTART" in body
    assert "20990602" in body
    # DTEND should encode 2099-06-02 20:30 (start + 90 min)
    assert "DTEND" in body


@pytest.mark.anyio
async def test_ical_feed_includes_location(instance_repo, type_repo) -> None:
    """VEVENT must include LOCATION when set on the instance."""
    await _seed_instance(instance_repo, location="Dojo East Wing")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/sessions/ical")
    body = response.text
    assert "LOCATION:Dojo East Wing" in body


@pytest.mark.anyio
async def test_ical_feed_includes_description_from_info(instance_repo, type_repo) -> None:
    """VEVENT must include DESCRIPTION set to the info field."""
    await _seed_instance(instance_repo, info="Practice focus: kote strikes")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/sessions/ical")
    body = response.text
    assert "DESCRIPTION:Practice focus: kote strikes" in body


@pytest.mark.anyio
async def test_ical_feed_omits_location_when_null(instance_repo, type_repo) -> None:
    """VEVENT must not include a LOCATION line when location is None."""
    await _seed_instance(instance_repo, location=None)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/sessions/ical")
    assert response.status_code == 200
    body = response.text
    assert "BEGIN:VEVENT" in body
    assert "LOCATION" not in body


@pytest.mark.anyio
async def test_ical_feed_omits_description_when_info_null(instance_repo, type_repo) -> None:
    """VEVENT must not include a DESCRIPTION line when info is None."""
    await _seed_instance(instance_repo, info=None)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/sessions/ical")
    assert response.status_code == 200
    body = response.text
    assert "BEGIN:VEVENT" in body
    assert "DESCRIPTION" not in body


# ---------------------------------------------------------------------------
# AC3 — coach_notes is never included in iCal output
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_ical_feed_never_includes_coach_notes(instance_repo, type_repo) -> None:
    """iCal feed must never expose coach_notes regardless of the stored value."""
    await _seed_instance(
        instance_repo,
        coach_notes="SECRET: work on nuki-waza",
        info="General training",
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/sessions/ical")
    assert response.status_code == 200
    body = response.text
    assert "BEGIN:VEVENT" in body
    assert "SECRET" not in body
    assert "nuki-waza" not in body
    assert "coach_notes" not in body.lower()


# ---------------------------------------------------------------------------
# AC4 — UIDs are stable (UUID of the session instance)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_ical_vevent_uid_equals_instance_uuid(instance_repo, type_repo) -> None:
    """Each VEVENT UID must equal the session instance UUID."""
    inst = await _seed_instance(instance_repo)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/sessions/ical")
    body = response.text
    assert f"UID:{inst['id']}" in body


@pytest.mark.anyio
async def test_ical_vevent_uid_stable_across_requests(instance_repo, type_repo) -> None:
    """VEVENT UIDs must remain identical across two consecutive requests."""
    inst = await _seed_instance(instance_repo)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r1 = await c.get("/sessions/ical")
        r2 = await c.get("/sessions/ical")
    assert f"UID:{inst['id']}" in r1.text
    assert f"UID:{inst['id']}" in r2.text


# ---------------------------------------------------------------------------
# AC5 — generate_checkin_token persists URL to SessionInstance.checkin_url
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_generate_checkin_token_persists_checkin_url(
    instance_repo, checkin_token_repo, monkeypatch
) -> None:
    """POST /sessions/{id}/checkin-token must store a checkin URL in
    SessionInstance.checkin_url, built from PUBLIC_ORIGIN."""
    monkeypatch.setenv("PUBLIC_ORIGIN", "https://dojo.example.com")
    # Wire up attendance-domain session repo to share the same store
    app.dependency_overrides[get_attendance_session_instance_repo] = (
        lambda: StubAttendanceSessionInstanceRepo(instance_repo._store)
    )
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    inst = await _seed_instance(instance_repo)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get(f"/sessions/{inst['id']}/checkin-token")

    assert response.status_code == 200
    token_data = response.json()
    token_value = token_data["token"]

    # The session instance checkin_url must now be set
    updated_inst = await instance_repo.get(inst["id"])
    assert updated_inst is not None
    assert updated_inst.get("checkin_url") is not None
    expected_url = f"https://dojo.example.com/checkin/{token_value}"
    assert updated_inst["checkin_url"] == expected_url


@pytest.mark.anyio
async def test_generate_checkin_token_uses_webauthn_origin_fallback(
    instance_repo, checkin_token_repo, monkeypatch
) -> None:
    """When PUBLIC_ORIGIN is absent, WEBAUTHN_ORIGIN is used as the fallback
    for building the checkin URL."""
    monkeypatch.delenv("PUBLIC_ORIGIN", raising=False)
    monkeypatch.setenv("WEBAUTHN_ORIGIN", "https://fallback.dojo.test")
    app.dependency_overrides[get_attendance_session_instance_repo] = (
        lambda: StubAttendanceSessionInstanceRepo(instance_repo._store)
    )
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    inst = await _seed_instance(instance_repo)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get(f"/sessions/{inst['id']}/checkin-token")

    assert response.status_code == 200
    token_data = response.json()
    token_value = token_data["token"]

    updated_inst = await instance_repo.get(inst["id"])
    assert updated_inst is not None
    assert updated_inst.get("checkin_url") is not None
    assert updated_inst["checkin_url"].startswith("https://fallback.dojo.test/checkin/")
    assert token_value in updated_inst["checkin_url"]


# ---------------------------------------------------------------------------
# AC2 extra — multiple instances all produce VEVENTs
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_ical_feed_includes_all_upcoming_sessions(
    instance_repo, type_repo
) -> None:
    """Every upcoming non-cancelled instance appears as its own VEVENT."""
    ta = type_repo.seed(str(uuid.uuid4()), "Session A")
    tb = type_repo.seed(str(uuid.uuid4()), "Session B")
    tc = type_repo.seed(str(uuid.uuid4()), "Cancelled Session")
    await _seed_instance(
        instance_repo, session_type_id=ta["id"], instance_date="2099-06-02"
    )
    await _seed_instance(
        instance_repo, session_type_id=tb["id"], instance_date="2099-06-09"
    )
    # Cancelled — must NOT appear
    await _seed_instance(
        instance_repo,
        session_type_id=tc["id"],
        instance_date="2099-06-16",
        cancelled=True,
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/sessions/ical")
    body = response.text
    assert "SUMMARY:Session A" in body
    assert "SUMMARY:Session B" in body
    assert "SUMMARY:Cancelled Session" not in body
    assert body.count("BEGIN:VEVENT") == 2


# ---------------------------------------------------------------------------
# Unit tests for build_ical (issue #56 — added to close coverage gaps)
# These test the pure function directly without going through the HTTP layer.
# ---------------------------------------------------------------------------

from app.sessions.ical import build_ical  # noqa: E402


def test_build_ical_empty_list_returns_valid_vcalendar() -> None:
    """build_ical([]) must return a valid, non-empty iCal document with no VEVENTs."""
    result = build_ical([])
    assert result.startswith("BEGIN:VCALENDAR")
    assert "END:VCALENDAR" in result
    assert "BEGIN:VEVENT" not in result


def test_build_ical_uses_crlf_line_endings() -> None:
    """RFC 5545 §3.1 requires CRLF (\\r\\n) line endings throughout the output."""
    result = build_ical([])
    # Every line break must be \\r\\n
    assert "\r\n" in result
    # There must be no bare \\n (i.e. \\n not preceded by \\r)
    import re

    bare_lf_count = len(re.findall(r"(?<!\r)\n", result))
    assert bare_lf_count == 0, f"Found {bare_lf_count} bare \\n line endings"


def test_build_ical_excludes_cancelled_sessions() -> None:
    """build_ical strips sessions where cancelled=True even when passed directly."""
    sessions = [
        {
            "id": "uid-active",
            "title": "Active Session",
            "date": "2099-07-01",
            "start_time": "19:00",
            "duration_minutes": 60,
            "location": None,
            "info": None,
            "cancelled": False,
        },
        {
            "id": "uid-cancelled",
            "title": "Cancelled Session",
            "date": "2099-07-08",
            "start_time": "19:00",
            "duration_minutes": 60,
            "location": None,
            "info": None,
            "cancelled": True,
        },
    ]
    result = build_ical(sessions)
    assert "SUMMARY:Active Session" in result
    assert "SUMMARY:Cancelled Session" not in result
    assert result.count("BEGIN:VEVENT") == 1


def test_build_ical_strips_admin_only_fields() -> None:
    """build_ical must not include coach_notes or any other admin-only field
    even when the caller passes them in the session dict."""
    sessions = [
        {
            "id": "uid-secret",
            "title": "Tameshigiri Night",
            "date": "2099-07-15",
            "start_time": "18:00",
            "duration_minutes": 90,
            "location": "Dojo",
            "info": "Public info",
            "coach_notes": "SECRET coach guidance",
            "checkin_url": "https://secret.internal/checkin/tok",
            "cancelled": False,
        }
    ]
    result = build_ical(sessions)
    assert "SECRET" not in result
    assert "coach_notes" not in result.lower()
    assert "checkin_url" not in result.lower()
    # Public fields should be present
    assert "SUMMARY:Tameshigiri Night" in result
    assert "DESCRIPTION:Public info" in result


def test_build_ical_dtend_calculated_from_duration() -> None:
    """DTEND must equal DTSTART + duration_minutes."""
    sessions = [
        {
            "id": "uid-dur",
            "title": "Duration Test",
            "date": "2099-08-01",
            "start_time": "18:00",
            "duration_minutes": 90,
            "location": None,
            "info": None,
            "cancelled": False,
        }
    ]
    result = build_ical(sessions)
    # DTSTART: 2099-08-01 18:00  → 20990801T180000
    # DTEND:   2099-08-01 19:30  → 20990801T193000
    assert "DTSTART:20990801T180000" in result
    assert "DTEND:20990801T193000" in result


def test_build_ical_vevent_ends_with_end_vevent() -> None:
    """Each VEVENT block must be terminated with END:VEVENT."""
    sessions = [
        {
            "id": "uid-term",
            "title": "Termination Check",
            "date": "2099-09-01",
            "start_time": "10:00",
            "duration_minutes": 60,
            "location": None,
            "info": None,
            "cancelled": False,
        }
    ]
    result = build_ical(sessions)
    assert "END:VEVENT" in result


def test_build_ical_escapes_crlf_injection_in_summary() -> None:
    """Newlines in free-text fields must not inject new iCal property lines."""
    sessions = [
        {
            "id": "uid-inject",
            "title": "Training\r\nSTATUS:CONFIRMED\r\nATTACH:http://evil.example/",
            "date": "2099-10-01",
            "start_time": "19:00",
            "duration_minutes": 90,
            "location": "Dojo\nINJECTED:yes",
            "info": "Normal info\r\nX-INJECTED:yes",
            "cancelled": False,
        }
    ]
    result = build_ical(sessions)
    # Real CRLF line breaks must only occur between iCal property lines —
    # none of the injected text should produce a standalone CRLF-prefixed property.
    lines = result.split("\r\n")
    assert not any(ln.startswith("STATUS:") for ln in lines)
    assert not any(ln.startswith("ATTACH:") for ln in lines)
    assert not any(ln.startswith("INJECTED:") for ln in lines)
    assert not any(ln.startswith("X-INJECTED:") for ln in lines)
