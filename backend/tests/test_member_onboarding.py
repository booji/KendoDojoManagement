"""
Unit tests for issue #160 — first-save onboarding validation.

PUT /users/me/member (first-save, no existing member record) must return 422
when any of first_name, surname, or dob are missing.

Uses StubRepository pattern — NO real DB. Dependencies are overridden via
app.dependency_overrides to inject in-memory stubs.

Acceptance criteria:
  AC1: missing first_name → 422
  AC2: missing surname → 422
  AC3: missing dob → 422
  AC4: all three present (no emergency contact, no display_name) → 200 or 201
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.guards import REQUIRE_MEMBER
from app.auth.models import UserClaims
from app.main import app
from app.members.dependencies import get_member_repo

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_USER_SUB = "user-uuid-onboarding"

_MEMBER_CLAIMS = UserClaims(
    sub=_USER_SUB, email="onboard@dojo.test", role="member", is_active=True
)


def _member_override():
    return _MEMBER_CLAIMS


# ---------------------------------------------------------------------------
# Stub repository (copied from test_member_self_update.py for isolation)
# ---------------------------------------------------------------------------


class StubMemberRepo:
    """In-memory stand-in for a Member repository."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    async def get(self, member_id: str) -> dict[str, Any] | None:
        return self._store.get(member_id)

    async def get_by_email(self, email: str) -> dict[str, Any] | None:
        for item in self._store.values():
            if item["email"] == email:
                return item
        return None

    async def get_by_user_id(self, user_id: str) -> dict[str, Any] | None:
        for item in self._store.values():
            if item.get("user_id") == user_id:
                return item
        return None

    async def add(self, data: dict[str, Any]) -> dict[str, Any]:
        existing = await self.get_by_email(data["email"])
        if existing:
            raise ValueError(f"Member with email '{data['email']}' already exists")
        new_id = str(uuid.uuid4())
        record = {"id": new_id, **data}
        self._store[new_id] = record
        return record

    async def update(
        self, member_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        record = self._store.get(member_id)
        if record is None:
            return None
        record.update(data)
        return record

    async def deactivate(self, member_id: str) -> dict[str, Any] | None:
        record = self._store.get(member_id)
        if record is None:
            return None
        record["membership_status"] = "inactive"
        return record

    async def list(
        self,
        status: str | None = None,
        search: str | None = None,
    ) -> list[dict[str, Any]]:
        results = list(self._store.values())
        if status is not None:
            results = [r for r in results if r["membership_status"] == status]
        if search is not None:
            term = search.lower()
            results = [
                r
                for r in results
                if term in r["first_name"].lower()
                or term in r["surname"].lower()
                or term in r["email"].lower()
            ]
        return results


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def empty_member_repo() -> StubMemberRepo:
    """A repo with no pre-seeded records — simulates user with no member record."""
    repo = StubMemberRepo()
    app.dependency_overrides[get_member_repo] = lambda: repo
    return repo


# ---------------------------------------------------------------------------
# AC1 — missing first_name → 422 on first-save
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_first_save_missing_first_name_returns_422(empty_member_repo) -> None:
    """PUT with surname + dob but no first_name must return 422 on first-save."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.put(
            "/users/me/member",
            json={"surname": "Yamada", "dob": "1990-06-15"},
        )

    assert (
        response.status_code == 422
    ), f"Expected 422 when first_name is absent on first-save, got {response.status_code}"


# ---------------------------------------------------------------------------
# AC2 — missing surname → 422 on first-save
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_first_save_missing_surname_returns_422(empty_member_repo) -> None:
    """PUT with first_name + dob but no surname must return 422 on first-save."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.put(
            "/users/me/member",
            json={"first_name": "Taro", "dob": "1990-06-15"},
        )

    assert (
        response.status_code == 422
    ), f"Expected 422 when surname is absent on first-save, got {response.status_code}"


# ---------------------------------------------------------------------------
# AC3 — missing dob → 422 on first-save
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_first_save_missing_dob_returns_422(empty_member_repo) -> None:
    """PUT with first_name + surname but no dob must return 422 on first-save."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.put(
            "/users/me/member",
            json={"first_name": "Taro", "surname": "Yamada"},
        )

    assert (
        response.status_code == 422
    ), f"Expected 422 when dob is absent on first-save, got {response.status_code}"


# ---------------------------------------------------------------------------
# AC4 — all three present → success (200 or 201) without optional fields
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_first_save_with_required_fields_only_succeeds(empty_member_repo) -> None:
    """PUT with first_name + surname + dob (no emergency contact, no display_name)
    must succeed on first-save."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.put(
            "/users/me/member",
            json={
                "first_name": "Taro",
                "surname": "Yamada",
                "dob": "1990-06-15",
            },
        )

    assert response.status_code in (200, 201), (
        f"Expected 200/201 when all required fields present, got {response.status_code}: "
        f"{response.text}"
    )
    body = response.json()
    assert body["first_name"] == "Taro"
    assert body["surname"] == "Yamada"
    assert "id" in body


# ---------------------------------------------------------------------------
# Issue #249 — an explicit null for a required field on first-save must be
# treated the same as a missing field, not silently coerced into a value.
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_first_save_explicit_null_first_name_returns_422(
    empty_member_repo,
) -> None:
    """PUT with first_name explicitly null (surname + dob present) is still 422."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.put(
            "/users/me/member",
            json={"first_name": None, "surname": "Yamada", "dob": "1990-06-15"},
        )

    assert response.status_code == 422, (
        "Expected 422 when first_name is explicitly null on first-save, "
        f"got {response.status_code}"
    )


@pytest.mark.anyio
async def test_first_save_explicit_null_surname_returns_422(
    empty_member_repo,
) -> None:
    """PUT with surname explicitly null (first_name + dob present) is still 422."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.put(
            "/users/me/member",
            json={"first_name": "Taro", "surname": None, "dob": "1990-06-15"},
        )

    assert response.status_code == 422, (
        "Expected 422 when surname is explicitly null on first-save, "
        f"got {response.status_code}"
    )


@pytest.mark.anyio
async def test_first_save_explicit_null_dob_returns_422(empty_member_repo) -> None:
    """PUT with dob explicitly null (first_name + surname present) is still 422.

    dob is clearable on an *existing* record via explicit null, but on
    first-save it remains a required field — an explicit null must not be
    treated as "no opinion" and slip through as a create.
    """
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.put(
            "/users/me/member",
            json={"first_name": "Taro", "surname": "Yamada", "dob": None},
        )

    assert response.status_code == 422, (
        "Expected 422 when dob is explicitly null on first-save, "
        f"got {response.status_code}"
    )
