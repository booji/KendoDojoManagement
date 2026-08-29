"""
Tests for issue #176 — Guard type deletion when referenced by a segment.

Acceptance criteria:
  1. Deleting a session type referenced by any segment is rejected with HTTP 409 Conflict
     and a descriptive detail message.
  2. Deleting an unreferenced session type succeeds (HTTP 204 or 200).
  3. Covers both the referenced and unreferenced cases.

Tests (unit/integration — in-memory fakes, no DB):
  - DELETE /session-types/{id} with an unreferenced type succeeds (204/200)
  - DELETE /session-types/{id} with a type referenced by a template segment returns 409
  - DELETE /session-types/{id} with a type referenced by an instance segment returns 409
  - DELETE /session-types/{id} for a non-existent type returns 404
  - DELETE /session-types/{id} for a non-admin returns 403

NO real DB: the shared in-memory fakes stand in. Dependencies are overridden via
app.dependency_overrides to inject in-memory stubs.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.guards import REQUIRE_ADMIN
from app.auth.models import UserClaims
from app.auth.token import encode_token
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

_ADMIN = UserClaims(
    sub="admin-uuid", email="admin@dojo.test", role="admin", is_active=True
)
_MEMBER = UserClaims(
    sub="member-uuid", email="member@dojo.test", role="member", is_active=True
)


def _admin_override():
    return _ADMIN


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
# Seed helpers
# ---------------------------------------------------------------------------


async def _seed_type(
    repo: InMemorySessionTypeRepository, *, name: str = "Keiko"
) -> dict[str, Any]:
    return await repo.add(name)


async def _seed_template_with_type(
    repo: InMemorySessionTemplateRepository, type_id: str
) -> dict[str, Any]:
    """Add a template with a segment that references type_id."""
    return await repo.add(
        {
            "title": "Weekly Keiko",
            "start_date": "2026-01-05",
            "recurrence": "weekly",
            "day_of_week": 0,
            "location": "Main Hall",
            "segments": [
                {
                    "start_time": "19:00",
                    "duration_minutes": 90,
                    "type_ids": [type_id],
                    "coach_notes": None,
                }
            ],
        }
    )


async def _seed_instance_with_type(
    repo: InMemorySessionInstanceRepository, type_id: str
) -> dict[str, Any]:
    """Add an instance with a segment that references type_id."""
    return await repo.add(
        {
            "title": "Monday Keiko",
            "date": "2099-07-01",
            "location": "Main Hall",
            "info": None,
            "coach_notes": None,
            "segments": [
                {
                    "start_time": "19:00",
                    "duration_minutes": 90,
                    "type_ids": [type_id],
                    "coach_notes": None,
                }
            ],
        }
    )


# ---------------------------------------------------------------------------
# AC1 — Deleting an unreferenced type succeeds
# ---------------------------------------------------------------------------


async def test_delete_unreferenced_session_type_succeeds(
    type_repo, template_repo, instance_repo
) -> None:
    """DELETE /session-types/{id} for an unreferenced type must return 204 (or 200)."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    st = await _seed_type(type_repo, name="Iaido")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.delete(f"/session-types/{st['id']}")

    assert response.status_code in (
        200,
        204,
    ), f"Expected 200 or 204 for unreferenced type, got {response.status_code}"
    # Type must be gone from the store
    remaining = await type_repo.list()
    assert all(r["id"] != st["id"] for r in remaining), (
        "Deleted type must not appear in subsequent list"
    )


# ---------------------------------------------------------------------------
# AC2a — Deleting a type referenced by a template segment is rejected with 409
# ---------------------------------------------------------------------------


async def test_delete_session_type_referenced_by_template_segment_returns_409(
    type_repo, template_repo, instance_repo
) -> None:
    """DELETE /session-types/{id} must return 409 when any template segment references the type."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    st = await _seed_type(type_repo, name="Kendo")
    await _seed_template_with_type(template_repo, st["id"])

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.delete(f"/session-types/{st['id']}")

    assert response.status_code == 409, (
        f"Expected 409 when type is referenced by a template segment, got {response.status_code}"
    )
    body = response.json()
    assert "detail" in body, "409 response must include a 'detail' field"
    assert body["detail"], "409 detail message must not be empty"
    # Type must NOT have been deleted
    remaining = await type_repo.list()
    assert any(r["id"] == st["id"] for r in remaining), (
        "Type referenced by a template segment must not be deleted"
    )


# ---------------------------------------------------------------------------
# AC2b — Deleting a type referenced by an instance segment is rejected with 409
# ---------------------------------------------------------------------------


async def test_delete_session_type_referenced_by_instance_segment_returns_409(
    type_repo, template_repo, instance_repo
) -> None:
    """DELETE /session-types/{id} must return 409 when any instance segment references the type."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    st = await _seed_type(type_repo, name="Jodo")
    await _seed_instance_with_type(instance_repo, st["id"])

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.delete(f"/session-types/{st['id']}")

    assert response.status_code == 409, (
        f"Expected 409 when type is referenced by an instance segment, got {response.status_code}"
    )
    body = response.json()
    assert "detail" in body, "409 response must include a 'detail' field"
    assert body["detail"], "409 detail message must not be empty"
    # Type must NOT have been deleted
    remaining = await type_repo.list()
    assert any(r["id"] == st["id"] for r in remaining), (
        "Type referenced by an instance segment must not be deleted"
    )


# ---------------------------------------------------------------------------
# AC3 — Deleting a non-existent type returns 404
# ---------------------------------------------------------------------------


async def test_delete_nonexistent_session_type_returns_404(
    type_repo, template_repo, instance_repo
) -> None:
    """DELETE /session-types/{id} for an unknown id must return 404."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    fake_id = str(uuid.uuid4())

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.delete(f"/session-types/{fake_id}")

    assert response.status_code == 404, (
        f"Expected 404 for non-existent type, got {response.status_code}"
    )


# ---------------------------------------------------------------------------
# AC4 — Non-admin is forbidden (403)
# ---------------------------------------------------------------------------


async def test_delete_session_type_forbidden_for_member(
    type_repo, template_repo, instance_repo
) -> None:
    """DELETE /session-types/{id} must return 403 for a non-admin user."""
    member_claims = UserClaims(
        sub="member-uuid", email="m@dojo.test", role="member", is_active=True
    )
    member_token = encode_token(member_claims)
    st = await _seed_type(type_repo, name="Naginata")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.delete(
            f"/session-types/{st['id']}",
            cookies={"access_token": member_token},
        )

    assert response.status_code == 403, (
        f"Expected 403 for non-admin DELETE, got {response.status_code}"
    )
