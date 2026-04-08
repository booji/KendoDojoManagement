"""
Unit / integration tests for issue #9 — Attendance / Check-in.

Uses StubRepository pattern — NO real DB. Dependencies are overridden via
app.dependency_overrides to inject in-memory stubs.

Acceptance criteria exercised here:
  2. POST /sessions/{id}/checkin checks in the authenticated member
  3. A member cannot check in to a cancelled session
  4. GET /sessions/{id}/checkin-token generates a short-lived token (admin only)
  5. POST /checkin/{token} resolves token and checks in the authenticated member
  6. Expired or invalid token returns an appropriate error
  7. Admin can see a live list via GET /sessions/{id}/attendance
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.attendance.dependencies import (
    get_attendance_repo,
    get_checkin_token_repo,
    get_session_instance_repo,
)
from app.auth.guards import REQUIRE_ADMIN, REQUIRE_MEMBER
from app.auth.models import UserClaims
from app.auth.token import encode_token
from app.main import app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ADMIN = UserClaims(sub="admin-uuid", email="admin@dojo.test", role="admin", is_active=True)
_MEMBER = UserClaims(sub="member-uuid", email="member@dojo.test", role="member", is_active=True)


def _admin_override():
    return _ADMIN


def _member_override():
    return _MEMBER


def _member_token() -> str:
    return encode_token(_MEMBER)


def _admin_token() -> str:
    return encode_token(_ADMIN)


# ---------------------------------------------------------------------------
# Stub repositories
# ---------------------------------------------------------------------------


class StubSessionInstanceRepo:
    """In-memory stand-in for a SessionInstance repository (attendance context)."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    async def get(self, instance_id: str) -> dict[str, Any] | None:
        return self._store.get(instance_id)

    def seed(self, cancelled: bool = False) -> dict[str, Any]:
        new_id = str(uuid.uuid4())
        record = {
            "id": new_id,
            "date": "2099-06-01",
            "cancelled": cancelled,
        }
        self._store[new_id] = record
        return record


class StubAttendanceRepo:
    """In-memory stand-in for an Attendance repository."""

    def __init__(self) -> None:
        self._store: list[dict[str, Any]] = []

    async def check_in(
        self,
        session_id: str,
        member_id: str,
        recorded_by: str,
    ) -> dict[str, Any]:
        record = {
            "id": str(uuid.uuid4()),
            "session_id": session_id,
            "member_id": member_id,
            "checked_in_at": datetime.now(UTC).isoformat(),
            "recorded_by": recorded_by,
        }
        self._store.append(record)
        return record

    async def list_for_session(self, session_id: str) -> list[dict[str, Any]]:
        return [r for r in self._store if r["session_id"] == session_id]

    async def get_by_session_member(
        self, session_id: str, member_id: str
    ) -> dict[str, Any] | None:
        for r in self._store:
            if r["session_id"] == session_id and r["member_id"] == member_id:
                return r
        return None


class StubCheckinTokenRepo:
    """In-memory stand-in for a CheckinToken repository."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    async def create(self, session_id: str, expires_at: datetime) -> dict[str, Any]:
        token = str(uuid.uuid4())
        record = {
            "token": token,
            "session_id": session_id,
            "expires_at": expires_at.isoformat(),
        }
        self._store[token] = record
        return record

    async def get(self, token: str) -> dict[str, Any] | None:
        return self._store.get(token)

    def seed_expired(self, session_id: str) -> dict[str, Any]:
        """Seed an already-expired token for testing."""
        token = str(uuid.uuid4())
        record = {
            "token": token,
            "session_id": session_id,
            "expires_at": (datetime.now(UTC) - timedelta(minutes=5)).isoformat(),
        }
        self._store[token] = record
        return record


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
def token_repo() -> StubCheckinTokenRepo:
    repo = StubCheckinTokenRepo()
    app.dependency_overrides[get_checkin_token_repo] = lambda: repo
    return repo


# ---------------------------------------------------------------------------
# AC2 — POST /sessions/{id}/checkin
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_member_can_checkin_to_session(
    session_repo: StubSessionInstanceRepo,
    attendance_repo: StubAttendanceRepo,
) -> None:
    session = session_repo.seed(cancelled=False)
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.post(f"/sessions/{session['id']}/checkin")

    assert response.status_code == 200
    body = response.json()
    assert "id" in body
    assert body["session_id"] == session["id"]
    assert body["member_id"] == _MEMBER.sub
    assert "checked_in_at" in body
    assert body["recorded_by"] == "self"


@pytest.mark.anyio
async def test_unauthenticated_checkin_returns_401(
    session_repo: StubSessionInstanceRepo,
    attendance_repo: StubAttendanceRepo,
) -> None:
    session = session_repo.seed(cancelled=False)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.post(f"/sessions/{session['id']}/checkin")

    assert response.status_code == 401


@pytest.mark.anyio
async def test_checkin_nonexistent_session_returns_404(
    session_repo: StubSessionInstanceRepo,
    attendance_repo: StubAttendanceRepo,
) -> None:
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    fake_id = str(uuid.uuid4())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.post(f"/sessions/{fake_id}/checkin")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# AC3 — Cannot check in to a cancelled session
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_member_cannot_checkin_to_cancelled_session(
    session_repo: StubSessionInstanceRepo,
    attendance_repo: StubAttendanceRepo,
) -> None:
    session = session_repo.seed(cancelled=True)
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.post(f"/sessions/{session['id']}/checkin")

    assert response.status_code == 409


# ---------------------------------------------------------------------------
# AC4 — GET /sessions/{id}/checkin-token (admin only)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_admin_can_generate_checkin_token(
    session_repo: StubSessionInstanceRepo,
    token_repo: StubCheckinTokenRepo,
) -> None:
    session = session_repo.seed(cancelled=False)
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get(f"/sessions/{session['id']}/checkin-token")

    assert response.status_code == 200
    body = response.json()
    assert "token" in body
    assert isinstance(body["token"], str)
    assert "expires_at" in body


@pytest.mark.anyio
async def test_member_cannot_generate_checkin_token(
    session_repo: StubSessionInstanceRepo,
    token_repo: StubCheckinTokenRepo,
) -> None:
    session = session_repo.seed(cancelled=False)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get(
            f"/sessions/{session['id']}/checkin-token",
            cookies={"access_token": _member_token()},
        )

    assert response.status_code == 403


@pytest.mark.anyio
async def test_generate_token_for_nonexistent_session(
    session_repo: StubSessionInstanceRepo,
    token_repo: StubCheckinTokenRepo,
) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    fake_id = str(uuid.uuid4())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get(f"/sessions/{fake_id}/checkin-token")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# AC5 — POST /checkin/{token}
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_member_can_checkin_via_token(
    session_repo: StubSessionInstanceRepo,
    attendance_repo: StubAttendanceRepo,
    token_repo: StubCheckinTokenRepo,
) -> None:
    session = session_repo.seed(cancelled=False)
    expires_at = datetime.now(UTC) + timedelta(minutes=15)
    token_record = await token_repo.create(session["id"], expires_at)
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.post(f"/checkin/{token_record['token']}")

    assert response.status_code == 200
    body = response.json()
    assert "id" in body
    assert body["session_id"] == session["id"]
    assert body["member_id"] == _MEMBER.sub
    assert "checked_in_at" in body


@pytest.mark.anyio
async def test_unauthenticated_token_checkin_returns_401(
    session_repo: StubSessionInstanceRepo,
    attendance_repo: StubAttendanceRepo,
    token_repo: StubCheckinTokenRepo,
) -> None:
    session = session_repo.seed(cancelled=False)
    expires_at = datetime.now(UTC) + timedelta(minutes=15)
    token_record = await token_repo.create(session["id"], expires_at)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.post(f"/checkin/{token_record['token']}")

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# AC6 — Expired / invalid token
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_expired_token_returns_410(
    session_repo: StubSessionInstanceRepo,
    attendance_repo: StubAttendanceRepo,
    token_repo: StubCheckinTokenRepo,
) -> None:
    session = session_repo.seed(cancelled=False)
    expired = token_repo.seed_expired(session["id"])
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.post(f"/checkin/{expired['token']}")

    assert response.status_code == 410


@pytest.mark.anyio
async def test_invalid_token_returns_404(
    session_repo: StubSessionInstanceRepo,
    attendance_repo: StubAttendanceRepo,
    token_repo: StubCheckinTokenRepo,
) -> None:
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.post("/checkin/this-token-does-not-exist")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# AC7 — GET /sessions/{id}/attendance (admin only)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_admin_can_list_session_attendance(
    session_repo: StubSessionInstanceRepo,
    attendance_repo: StubAttendanceRepo,
) -> None:
    session = session_repo.seed(cancelled=False)
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    # Seed two check-ins directly via the stub repo
    await attendance_repo.check_in(session["id"], "member-1", "self")
    await attendance_repo.check_in(session["id"], "member-2", "self")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get(f"/sessions/{session['id']}/attendance")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert len(body) == 2
    member_ids = {r["member_id"] for r in body}
    assert "member-1" in member_ids
    assert "member-2" in member_ids


@pytest.mark.anyio
async def test_member_cannot_list_attendance(
    session_repo: StubSessionInstanceRepo,
    attendance_repo: StubAttendanceRepo,
) -> None:
    session = session_repo.seed(cancelled=False)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get(
            f"/sessions/{session['id']}/attendance",
            cookies={"access_token": _member_token()},
        )

    assert response.status_code == 403
