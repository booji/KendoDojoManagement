"""
Unit / integration tests for issue #193 — per-session check-in window
override.

Builds on issue #192 (dojo-wide defaults). Scope here:
  1. Two new NULLABLE SessionInstance columns:
     checkin_window_before_minutes / checkin_window_after_minutes.
     NULL means "use the live dojo default".
  2. Effective window resolved at check-in time as
     override-if-set-else-live-default, resolved INDEPENDENTLY for
     before and after.
  3. Changing the dojo default immediately affects all sessions without
     an explicit override.
  4. SessionInstanceUpdate gains two optional override minute inputs;
     validation: non-negative integer <= 1440; blank/None clears the
     override to NULL.

Uses the StubRepository pattern — NO real DB — mirroring
test_checkin_window_endpoint.py. The stub session repo's seeded dict can
carry `checkin_window_before_minutes` / `checkin_window_after_minutes`
keys (None by default, i.e. "no override").
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

import pytest
from freezegun import freeze_time
from httpx import ASGITransport, AsyncClient

from app.attendance.dependencies import (
    get_attendance_repo,
    get_session_instance_repo,
)
from app.auth.guards import REQUIRE_MEMBER
from app.auth.models import UserClaims
from app.main import app
from app.settings.dependencies import get_dojo_settings_repo

_DEFAULT_BEFORE_MINUTES = 60
_DEFAULT_AFTER_MINUTES = 120

_MEMBER = UserClaims(
    sub="00000000-0000-0000-0000-000000000002",
    email="member@dojo.test",
    role="member",
    is_active=True,
)


def _member_override():
    return _MEMBER


def _split_date_time(dt: datetime) -> tuple[str, str]:
    return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")


class StubSessionInstanceRepo:
    """In-memory stand-in for a SessionInstance repository, extended so
    seeded sessions can carry per-instance check-in window overrides."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

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

    def seed(
        self,
        cancelled: bool = False,
        start: datetime | None = None,
        end: datetime | None = None,
        checkin_window_before_minutes: int | None = None,
        checkin_window_after_minutes: int | None = None,
    ) -> dict[str, Any]:
        now = datetime.now()
        start = start if start is not None else now
        end = end if end is not None else now + timedelta(minutes=60)
        date_str, start_time = _split_date_time(start)
        _, end_time = _split_date_time(end)
        assert start.date() == end.date(), "test sessions must not cross midnight"

        new_id = str(uuid.uuid4())
        record = {
            "id": new_id,
            "date": date_str,
            "start_time": start_time,
            "end_time": end_time,
            "cancelled": cancelled,
            "checkin_window_before_minutes": checkin_window_before_minutes,
            "checkin_window_after_minutes": checkin_window_after_minutes,
        }
        self._store[new_id] = record
        return record


class StubAttendanceRepo:
    def __init__(self) -> None:
        self._store: list[dict[str, Any]] = []

    async def check_in(
        self, session_id: str, member_id: str, recorded_by: str
    ) -> dict[str, Any]:
        record = {
            "id": str(uuid.uuid4()),
            "session_id": session_id,
            "member_id": member_id,
            "checked_in_at": datetime.now().isoformat(),
            "recorded_by": recorded_by,
        }
        self._store.append(record)
        return record

    async def get_by_session_member(
        self, session_id: str, member_id: str
    ) -> dict[str, Any] | None:
        for r in self._store:
            if r["session_id"] == session_id and r.get("member_id") == member_id:
                return r
        return None


class StubDojoSettingsRepo:
    def __init__(
        self,
        before_minutes: int = _DEFAULT_BEFORE_MINUTES,
        after_minutes: int = _DEFAULT_AFTER_MINUTES,
    ) -> None:
        self._settings: dict[str, Any] = {
            "dojo_name": "My Dojo",
            "logo_url": None,
            "primary_colour": "#4F46E5",
            "checkin_window_before_minutes": before_minutes,
            "checkin_window_after_minutes": after_minutes,
        }

    async def get(self) -> dict[str, Any]:
        return dict(self._settings)

    async def update(self, data: dict[str, Any]) -> dict[str, Any]:
        self._settings.update(data)
        return dict(self._settings)


@pytest.fixture(autouse=True)
def frozen_clock():
    """Pin the wall clock to a fixed midday so sessions seeded relative to
    ``datetime.now()`` (e.g. now + 90 min for the too-early cases) never roll
    across midnight. Without this the suite is flaky when run within ~90 min of
    local midnight — the endpoint and the stub both read the same frozen now, so
    the window maths stays deterministic regardless of when the tests run (#208).
    """
    with freeze_time("2026-07-15 12:00:00"):
        yield


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def session_repo() -> StubSessionInstanceRepo:
    repo = StubSessionInstanceRepo()
    app.dependency_overrides[get_session_instance_repo] = lambda: repo
    return repo


@pytest.fixture()
def attendance_repo() -> StubAttendanceRepo:
    repo = StubAttendanceRepo()
    app.dependency_overrides[get_attendance_repo] = lambda: repo
    return repo


@pytest.fixture()
def settings_repo() -> StubDojoSettingsRepo:
    repo = StubDojoSettingsRepo()
    app.dependency_overrides[get_dojo_settings_repo] = lambda: repo
    return repo


async def _post_checkin(session_id: str) -> Any:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        return await c.post(f"/sessions/{session_id}/checkin")


# ---------------------------------------------------------------------------
# AC2 — override wins over dojo default (before)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_before_override_opens_checkin_when_dojo_default_would_be_too_early(
    session_repo: StubSessionInstanceRepo,
    attendance_repo: StubAttendanceRepo,
    settings_repo: StubDojoSettingsRepo,
) -> None:
    """Dojo default before-minutes is 60. Session starts in 90 minutes, so
    the dojo default would classify this as TOO_EARLY. A per-session
    override of 120 minutes should open check-in instead."""
    now = datetime.now()
    start = now + timedelta(minutes=90)
    session = session_repo.seed(
        cancelled=False,
        start=start,
        end=start + timedelta(minutes=60),
        checkin_window_before_minutes=120,
    )
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    response = await _post_checkin(session["id"])

    assert response.status_code == 200


# ---------------------------------------------------------------------------
# AC2 — override wins over dojo default (after)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_after_override_opens_checkin_when_dojo_default_would_be_closed(
    session_repo: StubSessionInstanceRepo,
    attendance_repo: StubAttendanceRepo,
    settings_repo: StubDojoSettingsRepo,
) -> None:
    """Dojo default after-minutes is 120. Session ended 150 minutes ago, so
    the dojo default would classify this as CLOSED. A per-session override
    of 200 minutes should open check-in instead."""
    now = datetime.now()
    end = now - timedelta(minutes=150)
    start = end - timedelta(minutes=60)
    session = session_repo.seed(
        cancelled=False,
        start=start,
        end=end,
        checkin_window_after_minutes=200,
    )
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    response = await _post_checkin(session["id"])

    assert response.status_code == 200


# ---------------------------------------------------------------------------
# AC2 — NULL override falls back to the live dojo default
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_null_override_falls_back_to_dojo_default_too_early(
    session_repo: StubSessionInstanceRepo,
    attendance_repo: StubAttendanceRepo,
    settings_repo: StubDojoSettingsRepo,
) -> None:
    """No override set (both fields NULL) — behaviour matches dojo default:
    a session starting beyond the default 60-minute before-window is
    TOO_EARLY."""
    now = datetime.now()
    start = now + timedelta(minutes=_DEFAULT_BEFORE_MINUTES + 30)
    session = session_repo.seed(
        cancelled=False, start=start, end=start + timedelta(minutes=60)
    )
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    response = await _post_checkin(session["id"])

    assert response.status_code == 403
    assert response.json()["detail"]["reason"] == "too_early"


# ---------------------------------------------------------------------------
# AC2 — independent resolution: before overridden, after NULL
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_before_overridden_after_null_resolves_independently(
    session_repo: StubSessionInstanceRepo,
    attendance_repo: StubAttendanceRepo,
    settings_repo: StubDojoSettingsRepo,
) -> None:
    """before is overridden to 120 (opens the window for a session starting
    in 90 min, which the dojo default of 60 would reject); after is left
    NULL so it must still use the live dojo default of 120. The session
    here is currently running (comfortably inside any after-window), so a
    200 here plus the two tests above collectively prove independent
    resolution."""
    now = datetime.now()
    start = now + timedelta(minutes=90)
    session = session_repo.seed(
        cancelled=False,
        start=start,
        end=start + timedelta(minutes=60),
        checkin_window_before_minutes=120,
        checkin_window_after_minutes=None,
    )
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    response = await _post_checkin(session["id"])

    assert response.status_code == 200


@pytest.mark.anyio
async def test_after_overridden_before_null_resolves_independently(
    session_repo: StubSessionInstanceRepo,
    attendance_repo: StubAttendanceRepo,
    settings_repo: StubDojoSettingsRepo,
) -> None:
    """after is overridden to 200 (opens the window for a session that
    ended 150 min ago, which the dojo default of 120 would reject); before
    is left NULL so it must still use the live dojo default of 60. A
    session starting far in the future (outside the 60-minute default
    before-window) proves `before` still falls back to the dojo default
    rather than being silently unbounded by the `after` override."""
    now = datetime.now()
    start = now + timedelta(minutes=_DEFAULT_BEFORE_MINUTES + 30)
    session = session_repo.seed(
        cancelled=False,
        start=start,
        end=start + timedelta(minutes=60),
        checkin_window_before_minutes=None,
        checkin_window_after_minutes=200,
    )
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    response = await _post_checkin(session["id"])

    assert response.status_code == 403
    assert response.json()["detail"]["reason"] == "too_early"


# ---------------------------------------------------------------------------
# AC3 — changing the dojo default immediately affects sessions without an
# explicit override
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_changing_dojo_default_affects_session_without_override(
    session_repo: StubSessionInstanceRepo,
    attendance_repo: StubAttendanceRepo,
    settings_repo: StubDojoSettingsRepo,
) -> None:
    """A session with no override is TOO_EARLY under the original 60-minute
    default. Raising the dojo default to 120 (without touching the
    session) must immediately let the same session check in."""
    now = datetime.now()
    start = now + timedelta(minutes=90)
    session = session_repo.seed(
        cancelled=False, start=start, end=start + timedelta(minutes=60)
    )
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    first = await _post_checkin(session["id"])
    assert first.status_code == 403
    assert first.json()["detail"]["reason"] == "too_early"

    await settings_repo.update({"checkin_window_before_minutes": 120})

    second = await _post_checkin(session["id"])
    assert second.status_code == 200


# ---------------------------------------------------------------------------
# AC4 — SessionInstanceUpdate validation
# ---------------------------------------------------------------------------


def test_session_instance_update_accepts_none_override_minutes() -> None:
    from app.sessions.models import SessionInstanceUpdate

    payload = SessionInstanceUpdate(
        checkin_window_before_minutes=None, checkin_window_after_minutes=None
    )
    assert payload.checkin_window_before_minutes is None
    assert payload.checkin_window_after_minutes is None


@pytest.mark.parametrize("value", [0, 30, 1440])
def test_session_instance_update_accepts_valid_override_minutes(value: int) -> None:
    from app.sessions.models import SessionInstanceUpdate

    payload = SessionInstanceUpdate(
        checkin_window_before_minutes=value, checkin_window_after_minutes=value
    )
    assert payload.checkin_window_before_minutes == value
    assert payload.checkin_window_after_minutes == value


@pytest.mark.parametrize("value", [-1, -100])
def test_session_instance_update_rejects_negative_override_minutes(
    value: int,
) -> None:
    from pydantic import ValidationError

    from app.sessions.models import SessionInstanceUpdate

    with pytest.raises(ValidationError):
        SessionInstanceUpdate(checkin_window_before_minutes=value)


@pytest.mark.parametrize("value", [1441, 5000])
def test_session_instance_update_rejects_over_max_override_minutes(
    value: int,
) -> None:
    from pydantic import ValidationError

    from app.sessions.models import SessionInstanceUpdate

    with pytest.raises(ValidationError):
        SessionInstanceUpdate(checkin_window_after_minutes=value)


# ---------------------------------------------------------------------------
# AC1/AC2 — real-DB round-trip: the override columns must survive the actual
# SqlSessionInstanceRepository used at check-in time, not just the stub. This
# guards the class of bug where the ORM has the columns but the dict handed to
# the check-in endpoint silently drops them (see issue #193 review).
# ---------------------------------------------------------------------------


@pytest.fixture()
async def db_session():
    """Clean in-memory SQLite AsyncSession with the full schema."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.db.base import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.anyio
async def test_sql_session_instance_repo_get_returns_override_minutes(
    db_session,
) -> None:
    """SqlSessionInstanceRepository.get() — the repo actually used by the
    check-in endpoint — must serialise both override columns so the endpoint
    can honour them. A NULL override stays None."""
    from app.attendance.repository import SqlSessionInstanceRepository
    from app.sessions.db_models import (
        SessionInstance,
        SessionInstanceSegment,
    )

    instance_id = str(uuid.uuid4())
    instance = SessionInstance(
        id=instance_id,
        title="Override session",
        date="2099-06-01",
        checkin_window_before_minutes=120,
        checkin_window_after_minutes=None,
    )
    instance.segments = [
        SessionInstanceSegment(
            id=str(uuid.uuid4()),
            start_time="19:00",
            duration_minutes=60,
            position=0,
        )
    ]
    db_session.add(instance)
    await db_session.flush()

    repo = SqlSessionInstanceRepository(db_session)
    record = await repo.get(instance_id)

    assert record is not None
    assert record["checkin_window_before_minutes"] == 120
    assert record["checkin_window_after_minutes"] is None
