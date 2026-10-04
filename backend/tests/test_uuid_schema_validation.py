"""
Tests for issue #131 — uuid.UUID in Pydantic schemas and router path params.

All tests in this file are expected to FAIL until the implementation is done:
- MarkAttendedRequest.member_id must use uuid.UUID (not str)
- All router path params for UUID IDs must use uuid.UUID

Currently the path params and schema field use `str`, so:
- Malformed UUIDs in path params return non-422 status codes (the handler runs)
- MarkAttendedRequest accepts any string for member_id instead of raising ValidationError

All repo dependencies are stubbed so these tests are pure Tier 1 (no DB).
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.attendance.dependencies import (
    get_attendance_repo,
)
from app.attendance.dependencies import (
    get_session_instance_repo as get_att_session_instance_repo,
)
from app.auth.guards import REQUIRE_ADMIN, REQUIRE_MEMBER
from app.auth.models import AccountClaims
from app.dependencies import get_uow
from app.grades.dependencies import get_grade_repo
from app.main import app
from app.members.dependencies import get_member_repo
from app.sessions.dependencies import (
    get_session_instance_repo,
    get_session_template_repo,
    get_session_type_repo,
)
from tests.fake_repositories import (
    InMemoryAttendanceRepository,
    InMemoryMemberRepository,
    InMemorySessionInstanceRepository,
    InMemorySessionTemplateRepository,
    InMemorySessionTypeRepository,
)

# ---------------------------------------------------------------------------
# Shared auth overrides
# ---------------------------------------------------------------------------

_ADMIN = AccountClaims(
    sub="00000000-0000-0000-0000-000000000001",
    email="admin@dojo.test",
    role="admin",
    is_active=True,
)
_MEMBER = AccountClaims(
    sub="00000000-0000-0000-0000-000000000002",
    email="member@dojo.test",
    role="member",
    is_active=True,
)

_BAD_UUID = "not-a-uuid"


# ---------------------------------------------------------------------------
# No-op stub repos (pure Python, no DB)
# ---------------------------------------------------------------------------


class _NoOpGradeRepo:
    async def get_current_grade(self, member_id: str) -> str | None:
        return None

    async def add_promotion(self, **kwargs: Any) -> dict[str, Any]:
        return {}

    async def get_history(self, member_id: str) -> list[dict[str, Any]]:
        return []


class _NoOpUoW:
    session = None

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _stub_all_repos():
    """Stub every repository and UoW so tests never touch the DB."""
    app.dependency_overrides[get_uow] = lambda: _NoOpUoW()
    app.dependency_overrides[get_member_repo] = lambda: InMemoryMemberRepository()
    app.dependency_overrides[get_grade_repo] = lambda: _NoOpGradeRepo()
    app.dependency_overrides[get_session_instance_repo] = lambda: (
        InMemorySessionInstanceRepository()
    )
    app.dependency_overrides[get_session_template_repo] = lambda: (
        InMemorySessionTemplateRepository()
    )
    app.dependency_overrides[get_session_type_repo] = lambda: (
        InMemorySessionTypeRepository()
    )
    app.dependency_overrides[get_attendance_repo] = lambda: (
        InMemoryAttendanceRepository()
    )
    app.dependency_overrides[get_att_session_instance_repo] = lambda: (
        InMemorySessionInstanceRepository()
    )
    yield
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Pydantic schema — MarkAttendedRequest.member_id must reject non-UUID strings
# ---------------------------------------------------------------------------


def test_mark_attended_request_rejects_non_uuid_member_id() -> None:
    """MarkAttendedRequest.member_id typed as uuid.UUID must raise ValidationError
    when given a plain non-UUID string.  Currently it is `str`, so this passes —
    the test fails (no exception raised) until the fix is applied."""
    from app.attendance.models import MarkAttendedRequest

    with pytest.raises(ValidationError):
        MarkAttendedRequest(member_id="not-a-uuid")


# ---------------------------------------------------------------------------
# Router path params — malformed UUID must return 422
# ---------------------------------------------------------------------------


async def test_get_member_bad_uuid_returns_422() -> None:
    """GET /members/not-a-uuid should return 422 when member_id is uuid.UUID."""
    app.dependency_overrides[REQUIRE_MEMBER] = lambda: _MEMBER

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get(f"/members/{_BAD_UUID}")

    assert response.status_code == 422


async def test_put_member_bad_uuid_returns_422() -> None:
    """PUT /members/not-a-uuid should return 422 when member_id is uuid.UUID."""
    app.dependency_overrides[REQUIRE_ADMIN] = lambda: _ADMIN

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(f"/members/{_BAD_UUID}", json={})

    assert response.status_code == 422


async def test_get_member_grades_bad_uuid_returns_422() -> None:
    """GET /members/not-a-uuid/grades should return 422 when member_id is uuid.UUID."""
    app.dependency_overrides[REQUIRE_MEMBER] = lambda: _MEMBER

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get(f"/members/{_BAD_UUID}/grades")

    assert response.status_code == 422


async def test_post_member_grades_bad_uuid_returns_422() -> None:
    """POST /members/not-a-uuid/grades should return 422 when member_id is uuid.UUID."""
    app.dependency_overrides[REQUIRE_ADMIN] = lambda: _ADMIN

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            f"/members/{_BAD_UUID}/grades", json={"grade": "SHODAN"}
        )

    assert response.status_code == 422


async def test_get_session_bad_uuid_returns_422() -> None:
    """GET /sessions/not-a-uuid should return 422 when instance_id is uuid.UUID."""
    app.dependency_overrides[REQUIRE_MEMBER] = lambda: _MEMBER

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get(f"/sessions/{_BAD_UUID}")

    assert response.status_code == 422


async def test_post_session_cancel_bad_uuid_returns_422() -> None:
    """POST /sessions/not-a-uuid/cancel should return 422 when instance_id is uuid.UUID."""
    app.dependency_overrides[REQUIRE_ADMIN] = lambda: _ADMIN

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(f"/sessions/{_BAD_UUID}/cancel")

    assert response.status_code == 422


async def test_put_session_bad_uuid_returns_422() -> None:
    """PUT /sessions/not-a-uuid should return 422 when instance_id is uuid.UUID."""
    app.dependency_overrides[REQUIRE_ADMIN] = lambda: _ADMIN

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(f"/sessions/{_BAD_UUID}", json={})

    assert response.status_code == 422


async def test_get_session_attendance_bad_uuid_returns_422() -> None:
    """GET /sessions/not-a-uuid/attendance should return 422 when session_id is uuid.UUID."""
    app.dependency_overrides[REQUIRE_ADMIN] = lambda: _ADMIN

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get(f"/sessions/{_BAD_UUID}/attendance")

    assert response.status_code == 422


async def test_post_session_attendance_bad_uuid_returns_422() -> None:
    """POST /sessions/not-a-uuid/attendance should return 422 when session_id is uuid.UUID."""
    app.dependency_overrides[REQUIRE_ADMIN] = lambda: _ADMIN

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            f"/sessions/{_BAD_UUID}/attendance",
            json={"member_id": "00000000-0000-0000-0000-000000000099"},
        )

    assert response.status_code == 422


async def test_delete_session_attendance_bad_session_uuid_returns_422() -> None:
    """DELETE /sessions/not-a-uuid/attendance/not-a-uuid should return 422."""
    app.dependency_overrides[REQUIRE_ADMIN] = lambda: _ADMIN

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.delete(f"/sessions/{_BAD_UUID}/attendance/{_BAD_UUID}")

    assert response.status_code == 422


async def test_post_session_checkin_bad_uuid_returns_422() -> None:
    """POST /sessions/not-a-uuid/checkin should return 422 when session_id is uuid.UUID."""
    app.dependency_overrides[REQUIRE_MEMBER] = lambda: _MEMBER

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(f"/sessions/{_BAD_UUID}/checkin")

    assert response.status_code == 422


async def test_post_session_visitors_bad_uuid_returns_422() -> None:
    """POST /sessions/not-a-uuid/visitors should return 422 when session_id is uuid.UUID."""
    app.dependency_overrides[REQUIRE_ADMIN] = lambda: _ADMIN

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            f"/sessions/{_BAD_UUID}/visitors",
            json={"visitor_name": "Test Visitor"},
        )

    assert response.status_code == 422


async def test_get_member_attendance_bad_uuid_returns_422() -> None:
    """GET /members/not-a-uuid/attendance should return 422 when member_id is uuid.UUID."""
    app.dependency_overrides[REQUIRE_MEMBER] = lambda: _MEMBER

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get(f"/members/{_BAD_UUID}/attendance")

    assert response.status_code == 422
