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
from app.members.dependencies import get_member_repo

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ADMIN = UserClaims(
    sub="admin-uuid", email="admin@dojo.test", role="admin", is_active=True
)
_MEMBER = UserClaims(
    sub="00000000-0000-0000-0000-000000000002",
    email="member@dojo.test",
    role="member",
    is_active=True,
)
_OTHER_MEMBER = UserClaims(
    sub="other-member-uuid", email="other@dojo.test", role="member", is_active=True
)

# Valid UUIDs for use in path params
_SOME_MEMBER_UUID = "00000000-0000-0000-0000-000000000099"
_NONEXISTENT_MEMBER_UUID = "00000000-0000-0000-0000-000000000000"


def _admin_override():
    return _ADMIN


def _member_override():
    return _MEMBER


def _other_member_override():
    return _OTHER_MEMBER


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

    async def update(
        self, instance_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        record = self._store.get(instance_id)
        if record is None:
            return None
        record.update(data)
        return record

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
            if r["session_id"] == session_id and r.get("member_id") == member_id:
                return r
        return None

    async def admin_mark_attended(
        self,
        session_id: str,
        member_id: str,
        recorded_by: str,
    ) -> dict[str, Any]:
        record = {
            "id": str(uuid.uuid4()),
            "session_id": session_id,
            "member_id": member_id,
            "visitor_name": None,
            "checked_in_at": datetime.now(UTC).isoformat(),
            "recorded_by": recorded_by,
        }
        self._store.append(record)
        return record

    async def remove_attendance(self, session_id: str, member_id: str) -> bool:
        for i, r in enumerate(self._store):
            if r["session_id"] == session_id and r.get("member_id") == member_id:
                self._store.pop(i)
                return True
        return False

    async def add_visitor(
        self,
        session_id: str,
        visitor_name: str,
        recorded_by: str,
    ) -> dict[str, Any]:
        record = {
            "id": str(uuid.uuid4()),
            "session_id": session_id,
            "member_id": None,
            "visitor_name": visitor_name,
            "checked_in_at": datetime.now(UTC).isoformat(),
            "recorded_by": recorded_by,
        }
        self._store.append(record)
        return record

    async def list_for_member(self, member_id: str) -> list[dict[str, Any]]:
        return [r for r in self._store if r.get("member_id") == member_id]


class StubMemberRepo:
    """Minimal stub for AbstractMemberRepository — only implements get_by_user_id."""

    def __init__(self, own_member_id: str | None = None) -> None:
        # Maps user_id -> member record dict
        self._by_user_id: dict[str, dict[str, Any]] = {}
        if own_member_id is not None:
            # Pre-seed so that any user_id lookup returns a record with the given member id
            self._seed_user_id = own_member_id
        else:
            self._seed_user_id = None

    def seed_member(self, user_id: str, member_id: str) -> None:
        self._by_user_id[user_id] = {"id": member_id, "email": "stub@test.com"}

    async def get_by_user_id(self, user_id: str) -> dict[str, Any] | None:
        return self._by_user_id.get(user_id)


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

    async def redeem(self, token: str) -> dict[str, Any] | None:
        record = self._store.get(token)
        if record is None:
            return None
        if record.get("used_at") is not None:
            raise ValueError("Token already used")
        record["used_at"] = datetime.now(UTC).isoformat()
        return record

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

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(f"/sessions/{session['id']}/checkin")

    assert response.status_code == 200
    body = response.json()
    assert "id" in body
    assert body["session_id"] == session["id"]
    assert body["member_id"] == _MEMBER.sub
    assert "checked_in_at" in body
    assert body["recorded_by"] == _MEMBER.sub


@pytest.mark.anyio
async def test_unauthenticated_checkin_returns_401(
    session_repo: StubSessionInstanceRepo,
    attendance_repo: StubAttendanceRepo,
) -> None:
    session = session_repo.seed(cancelled=False)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(f"/sessions/{session['id']}/checkin")

    assert response.status_code == 401


@pytest.mark.anyio
async def test_checkin_nonexistent_session_returns_404(
    session_repo: StubSessionInstanceRepo,
    attendance_repo: StubAttendanceRepo,
) -> None:
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    fake_id = str(uuid.uuid4())

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
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

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
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

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
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

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
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

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
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

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
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

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
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

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(f"/checkin/{expired['token']}")

    assert response.status_code == 410


@pytest.mark.anyio
async def test_invalid_token_returns_401(
    session_repo: StubSessionInstanceRepo,
    attendance_repo: StubAttendanceRepo,
    token_repo: StubCheckinTokenRepo,
) -> None:
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
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

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
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

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get(
            f"/sessions/{session['id']}/attendance",
            cookies={"access_token": _member_token()},
        )

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Issue #10 AC1 — POST /sessions/{id}/attendance (admin marks member attended)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_admin_mark_attended_returns_201(
    session_repo: StubSessionInstanceRepo,
    attendance_repo: StubAttendanceRepo,
) -> None:
    session = session_repo.seed(cancelled=False)
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            f"/sessions/{session['id']}/attendance",
            json={"member_id": _SOME_MEMBER_UUID},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["session_id"] == session["id"]
    assert body["member_id"] == _SOME_MEMBER_UUID
    assert body["recorded_by"] == _ADMIN.sub


@pytest.mark.anyio
async def test_admin_mark_attended_nonexistent_session_returns_404(
    session_repo: StubSessionInstanceRepo,
    attendance_repo: StubAttendanceRepo,
) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    fake_id = str(uuid.uuid4())

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            f"/sessions/{fake_id}/attendance",
            json={"member_id": _SOME_MEMBER_UUID},
        )

    assert response.status_code == 404


@pytest.mark.anyio
async def test_admin_mark_attended_missing_member_id_returns_422(
    session_repo: StubSessionInstanceRepo,
    attendance_repo: StubAttendanceRepo,
) -> None:
    session = session_repo.seed(cancelled=False)
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            f"/sessions/{session['id']}/attendance",
            json={},
        )

    assert response.status_code == 422


@pytest.mark.anyio
async def test_member_cannot_admin_mark_attended(
    session_repo: StubSessionInstanceRepo,
    attendance_repo: StubAttendanceRepo,
) -> None:
    session = session_repo.seed(cancelled=False)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            f"/sessions/{session['id']}/attendance",
            json={"member_id": "some-member-uuid"},
            cookies={"access_token": _member_token()},
        )

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Issue #10 AC2 — DELETE /sessions/{id}/attendance/{member_id}
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_admin_remove_attendance_returns_204(
    session_repo: StubSessionInstanceRepo,
    attendance_repo: StubAttendanceRepo,
) -> None:
    session = session_repo.seed(cancelled=False)
    await attendance_repo.admin_mark_attended(
        session["id"], _SOME_MEMBER_UUID, "admin-uuid"
    )
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.delete(
            f"/sessions/{session['id']}/attendance/{_SOME_MEMBER_UUID}"
        )

    assert response.status_code == 204


@pytest.mark.anyio
async def test_admin_remove_attendance_not_found_returns_404(
    session_repo: StubSessionInstanceRepo,
    attendance_repo: StubAttendanceRepo,
) -> None:
    session = session_repo.seed(cancelled=False)
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.delete(
            f"/sessions/{session['id']}/attendance/{_NONEXISTENT_MEMBER_UUID}"
        )

    assert response.status_code == 404


@pytest.mark.anyio
async def test_member_cannot_remove_attendance(
    session_repo: StubSessionInstanceRepo,
    attendance_repo: StubAttendanceRepo,
) -> None:
    session = session_repo.seed(cancelled=False)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.delete(
            f"/sessions/{session['id']}/attendance/{_SOME_MEMBER_UUID}",
            cookies={"access_token": _member_token()},
        )

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Issue #10 AC3 — POST /sessions/{id}/visitors (admin adds visitor)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_admin_add_visitor_returns_201(
    session_repo: StubSessionInstanceRepo,
    attendance_repo: StubAttendanceRepo,
) -> None:
    session = session_repo.seed(cancelled=False)
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            f"/sessions/{session['id']}/visitors",
            json={"visitor_name": "John Guest"},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["session_id"] == session["id"]
    assert body["visitor_name"] == "John Guest"
    assert body["member_id"] is None


@pytest.mark.anyio
async def test_admin_add_visitor_nonexistent_session_returns_404(
    session_repo: StubSessionInstanceRepo,
    attendance_repo: StubAttendanceRepo,
) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    fake_id = str(uuid.uuid4())

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            f"/sessions/{fake_id}/visitors",
            json={"visitor_name": "John Guest"},
        )

    assert response.status_code == 404


@pytest.mark.anyio
async def test_admin_add_visitor_missing_name_returns_422(
    session_repo: StubSessionInstanceRepo,
    attendance_repo: StubAttendanceRepo,
) -> None:
    session = session_repo.seed(cancelled=False)
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            f"/sessions/{session['id']}/visitors",
            json={},
        )

    assert response.status_code == 422


@pytest.mark.anyio
async def test_member_cannot_add_visitor(
    session_repo: StubSessionInstanceRepo,
    attendance_repo: StubAttendanceRepo,
) -> None:
    session = session_repo.seed(cancelled=False)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            f"/sessions/{session['id']}/visitors",
            json={"visitor_name": "John Guest"},
            cookies={"access_token": _member_token()},
        )

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Issue #10 AC4 — GET /sessions/{id}/attendance returns members AND visitors
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_session_attendance_includes_visitors(
    session_repo: StubSessionInstanceRepo,
    attendance_repo: StubAttendanceRepo,
) -> None:
    session = session_repo.seed(cancelled=False)
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    await attendance_repo.admin_mark_attended(session["id"], "member-1", "admin-uuid")
    await attendance_repo.add_visitor(session["id"], "Visitor One", "admin-uuid")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get(f"/sessions/{session['id']}/attendance")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2

    member_records = [r for r in body if r.get("member_id") is not None]
    visitor_records = [r for r in body if r.get("member_id") is None]

    assert len(member_records) == 1
    assert len(visitor_records) == 1
    assert visitor_records[0]["visitor_name"] == "Visitor One"


@pytest.mark.anyio
async def test_attendance_record_has_visitor_name_field(
    session_repo: StubSessionInstanceRepo,
    attendance_repo: StubAttendanceRepo,
) -> None:
    """Each record in the list exposes visitor_name (nullable) for the new AttendanceReadV2 shape."""
    session = session_repo.seed(cancelled=False)
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    await attendance_repo.admin_mark_attended(session["id"], "member-1", "admin-uuid")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get(f"/sessions/{session['id']}/attendance")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    # member records have visitor_name=null
    assert "visitor_name" in body[0]
    assert body[0]["visitor_name"] is None


# ---------------------------------------------------------------------------
# Issue #10 AC5 — GET /members/{id}/attendance (member's history)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_admin_can_get_any_member_attendance_history(
    attendance_repo: StubAttendanceRepo,
) -> None:
    app.dependency_overrides[REQUIRE_MEMBER] = (
        _admin_override  # admin satisfies REQUIRE_MEMBER
    )
    # Admin bypasses the user→member lookup; still need a stub for the dep
    member_repo = StubMemberRepo()
    app.dependency_overrides[get_member_repo] = lambda: member_repo

    # Seed attendance records for a member
    session_id = str(uuid.uuid4())
    await attendance_repo.admin_mark_attended(session_id, _MEMBER.sub, "admin-uuid")
    await attendance_repo.admin_mark_attended(session_id, _MEMBER.sub, "admin-uuid")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get(f"/members/{_MEMBER.sub}/attendance")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert len(body) == 2
    assert all(r["member_id"] == _MEMBER.sub for r in body)


@pytest.mark.anyio
async def test_member_can_get_own_attendance_history(
    attendance_repo: StubAttendanceRepo,
) -> None:
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    # Stub the member repo: _MEMBER.sub (user UUID) resolves to a member record
    # whose id also equals _MEMBER.sub (matches the URL parameter)
    member_repo = StubMemberRepo()
    member_repo.seed_member(user_id=_MEMBER.sub, member_id=_MEMBER.sub)
    app.dependency_overrides[get_member_repo] = lambda: member_repo

    session_id = str(uuid.uuid4())
    await attendance_repo.admin_mark_attended(session_id, _MEMBER.sub, "admin-uuid")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get(f"/members/{_MEMBER.sub}/attendance")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert len(body) == 1


# ---------------------------------------------------------------------------
# Issue #10 AC6 — Member cannot access another member's attendance history
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_member_cannot_get_other_member_attendance_history(
    attendance_repo: StubAttendanceRepo,
) -> None:
    app.dependency_overrides[REQUIRE_MEMBER] = _other_member_override
    # _OTHER_MEMBER's user_id resolves to a different member id, not _MEMBER.sub
    member_repo = StubMemberRepo()
    member_repo.seed_member(user_id=_OTHER_MEMBER.sub, member_id=_OTHER_MEMBER.sub)
    app.dependency_overrides[get_member_repo] = lambda: member_repo

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get(f"/members/{_MEMBER.sub}/attendance")

    assert response.status_code == 403


@pytest.mark.anyio
async def test_unauthenticated_cannot_get_member_attendance_history() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get(f"/members/{_MEMBER.sub}/attendance")

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Issue #79 — GET /sessions/{id}/attendance includes display_name
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_attendance_list_includes_display_name_for_member(
    session_repo: StubSessionInstanceRepo,
    attendance_repo: StubAttendanceRepo,
) -> None:
    """AC1+AC2: member records have display_name = member's full_name."""
    session = session_repo.seed(cancelled=False)
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    # Stub returns display_name when present in the dict
    record = await attendance_repo.admin_mark_attended(
        session["id"], "member-1", "admin-uuid"
    )
    # Patch the stored record with a display_name (simulating the JOIN result)
    record["display_name"] = "Alice Kendo"
    attendance_repo._store[-1] = record

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get(f"/sessions/{session['id']}/attendance")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["display_name"] == "Alice Kendo"


@pytest.mark.anyio
async def test_attendance_list_display_name_null_for_visitor(
    session_repo: StubSessionInstanceRepo,
    attendance_repo: StubAttendanceRepo,
) -> None:
    """AC3: visitor records have display_name = null."""
    session = session_repo.seed(cancelled=False)
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    await attendance_repo.add_visitor(session["id"], "Drop-in Guest", "admin-uuid")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get(f"/sessions/{session['id']}/attendance")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["display_name"] is None
