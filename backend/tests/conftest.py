import os
from typing import Any

import pytest

# Must be set before any app imports so token.py can read it
os.environ.setdefault("JWT_SECRET", "test-secret-not-for-production")


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


class _NoOpAttendanceRepo:
    """Stub attendance repo used as a default in unit tests that don't set one."""

    async def list_for_session(self, session_id: str) -> list[dict[str, Any]]:
        return []

    async def check_in(
        self, session_id: str, member_id: str, recorded_by: str
    ) -> dict[str, Any]:  # pragma: no cover
        return {}

    async def get_by_session_member(
        self, session_id: str, member_id: str
    ) -> dict[str, Any] | None:  # pragma: no cover
        return None

    async def admin_mark_attended(
        self, session_id: str, member_id: str, recorded_by: str
    ) -> dict[str, Any]:  # pragma: no cover
        return {}

    async def remove_attendance(
        self, session_id: str, member_id: str
    ) -> bool:  # pragma: no cover
        return False

    async def add_visitor(
        self, session_id: str, visitor_name: str, recorded_by: str
    ) -> dict[str, Any]:  # pragma: no cover
        return {}

    async def list_for_member(self, member_id: str) -> list[dict[str, Any]]:  # pragma: no cover
        return []


@pytest.fixture(autouse=True)
def _default_attendance_repo_stub():
    """Install a no-op attendance repo so tests that don't mock it don't hit the DB.

    Individual tests can override get_attendance_repo after this fixture runs.
    """
    from app.attendance.dependencies import get_attendance_repo
    from app.main import app

    stub = _NoOpAttendanceRepo()
    app.dependency_overrides.setdefault(get_attendance_repo, lambda: stub)
    yield
    # Teardown is handled by each test file's own clear_overrides fixture.
