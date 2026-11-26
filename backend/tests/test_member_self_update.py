"""
Unit tests for issue #25 — Member self-update API, updated for issue #158.

Uses StubRepository pattern — NO real DB. Dependencies are overridden via
app.dependency_overrides to inject in-memory stubs.

Acceptance criteria exercised here:
  1. GET /accounts/me/member returns caller's Member record (200) or 404 if none
  2. PUT /accounts/me/member updates allowed self-service fields, returns updated record
  3. Admin-only fields sent to PUT /accounts/me/member are rejected (422) or silently ignored
  4. PUT /accounts/me/member creates a new Member record if none linked (first-save onboarding)
  5. Both endpoints return 401 for unauthenticated requests

Issue #158 changes:
  - full_name replaced by first_name + surname + display_name
  - parental_consent_obtained removed
  - dob is now nullable
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.guards import REQUIRE_MEMBER
from app.auth.models import AccountClaims
from app.dependencies import get_uow
from app.main import app
from app.members.dependencies import get_member_repo
from tests.fake_repositories import InMemoryMemberRepository, RecordingUnitOfWork

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_USER_SUB = "user-uuid-self"
_OTHER_SUB = "user-uuid-other"

_MEMBER_CLAIMS = AccountClaims(sub=_USER_SUB, email="self@dojo.test", role="member")


def _member_override():
    return _MEMBER_CLAIMS


def _seed_record(**overrides) -> dict[str, Any]:
    base: dict[str, Any] = {
        "email": "self@dojo.test",
        "first_name": "Self",
        "surname": "Member",
        "display_name": None,
        "dob": "1990-06-15",
        "join_date": "2024-01-10",
        "membership_status": "active",
        "is_coach": False,
        "is_first_aider": False,
        "emergency_contact_name": "Emergency Contact",
        "emergency_contact_phone": "+447700900001",
        "user_id": _USER_SUB,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def member_repo() -> InMemoryMemberRepository:
    repo = InMemoryMemberRepository()
    app.dependency_overrides[get_member_repo] = lambda: repo
    return repo


# ---------------------------------------------------------------------------
# AC1 — GET /accounts/me/member
# ---------------------------------------------------------------------------


async def test_get_my_member_returns_own_record(member_repo) -> None:
    """Happy path: authenticated member with a linked record gets 200."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    await member_repo.add(_seed_record())

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/accounts/me/member")

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "self@dojo.test"
    assert body["first_name"] == "Self"
    assert body["surname"] == "Member"
    assert "id" in body


async def test_get_my_member_returns_404_when_no_linked_record(member_repo) -> None:
    """Member exists in auth but has no Member record yet."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/accounts/me/member")

    assert response.status_code == 404


async def test_get_my_member_unauthenticated_returns_401(member_repo) -> None:
    """No credentials → 401."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/accounts/me/member")

    assert response.status_code == 401


async def test_get_my_member_response_schema(member_repo) -> None:
    """Response includes all expected MemberResponse fields for issue #158."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    await member_repo.add(_seed_record())

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/accounts/me/member")

    assert response.status_code == 200
    body = response.json()
    expected_fields = {
        "id",
        "email",
        "first_name",
        "surname",
        "display_name",
        "dob",
        "join_date",
        "membership_status",
        "is_coach",
        "is_first_aider",
        "emergency_contact_name",
        "emergency_contact_phone",
    }
    for field in expected_fields:
        assert field in body, f"Missing field in response: {field}"
    # Legacy fields must be absent
    assert "full_name" not in body, "full_name must not appear in MemberResponse"
    assert "parental_consent_obtained" not in body, (
        "parental_consent_obtained must not appear in MemberResponse"
    )
    assert "is_minor" not in body, "is_minor must not appear in MemberResponse"


async def test_get_my_member_only_returns_own_record(member_repo) -> None:
    """Endpoint resolves by claims.sub, not a URL parameter."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    # Seed a record for another user — must not be returned
    await member_repo.add(_seed_record(email="other@dojo.test", user_id=_OTHER_SUB))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/accounts/me/member")

    # Caller has no linked record, should be 404
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# AC2 — PUT /accounts/me/member updates allowed fields
# ---------------------------------------------------------------------------


async def test_put_my_member_updates_first_name(member_repo) -> None:
    """PUT updates first_name and returns updated record."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    await member_repo.add(_seed_record())

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(
            "/accounts/me/member",
            json={"first_name": "UpdatedFirst"},
        )

    assert response.status_code == 200
    assert response.json()["first_name"] == "UpdatedFirst"


class _VanishingMemberRepository(InMemoryMemberRepository):
    """The record is found, then deleted by someone else before the update."""

    async def update(
        self, member_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        return None


async def test_put_my_member_gone_before_the_update_returns_404() -> None:
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    repo = _VanishingMemberRepository([_seed_record()])
    app.dependency_overrides[get_member_repo] = lambda: repo
    uow = RecordingUnitOfWork()
    app.dependency_overrides[get_uow] = lambda: uow

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put("/accounts/me/member", json={"first_name": "New"})

    assert response.status_code == 404
    assert uow.commits == 0


async def test_put_my_member_updates_surname(member_repo) -> None:
    """PUT updates surname and returns updated record."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    await member_repo.add(_seed_record())

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(
            "/accounts/me/member",
            json={"surname": "UpdatedSurname"},
        )

    assert response.status_code == 200
    assert response.json()["surname"] == "UpdatedSurname"


async def test_put_my_member_updates_display_name(member_repo) -> None:
    """PUT updates display_name and returns updated record."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    await member_repo.add(_seed_record())

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(
            "/accounts/me/member",
            json={"display_name": "Taro-san"},
        )

    assert response.status_code == 200
    assert response.json()["display_name"] == "Taro-san"


async def test_put_my_member_updates_dob(member_repo) -> None:
    """PUT updates dob."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    await member_repo.add(_seed_record())

    new_dob = "1985-03-20"
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(
            "/accounts/me/member",
            json={"dob": new_dob},
        )

    assert response.status_code == 200
    # Record should reflect the new dob; is_minor must not appear
    body = response.json()
    assert body["dob"] == new_dob
    assert "is_minor" not in body


async def test_put_my_member_updates_emergency_contact(member_repo) -> None:
    """PUT updates emergency contact fields."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    await member_repo.add(_seed_record())

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(
            "/accounts/me/member",
            json={
                "emergency_contact_name": "New Emergency",
                "emergency_contact_phone": "+447700900999",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["emergency_contact_name"] == "New Emergency"
    assert body["emergency_contact_phone"] == "+447700900999"


async def test_put_my_member_update_persists(member_repo) -> None:
    """Change made via PUT is visible in subsequent GET."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    await member_repo.add(_seed_record())

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        await c.put("/accounts/me/member", json={"first_name": "Persisted"})

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        get_response = await c.get("/accounts/me/member")

    assert get_response.status_code == 200
    assert get_response.json()["first_name"] == "Persisted"


async def test_put_my_member_unauthenticated_returns_401(member_repo) -> None:
    """No credentials → 401."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(
            "/accounts/me/member",
            json={"first_name": "Hacker"},
        )

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# AC3 — Admin-only fields must not be applied via PUT /accounts/me/member
# ---------------------------------------------------------------------------


async def test_put_my_member_admin_only_field_is_rejected_or_ignored(
    member_repo,
) -> None:
    """
    Sending is_coach (admin-only) via PUT /accounts/me/member must not apply the change.
    Either 422 (rejected) or 200 with the field unchanged are acceptable.
    """
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    await member_repo.add(_seed_record(is_coach=False))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(
            "/accounts/me/member",
            json={"is_coach": True},
        )

    assert response.status_code in (200, 422)
    if response.status_code == 200:
        # Field must NOT have been applied
        assert response.json()["is_coach"] is False


async def test_put_my_member_membership_status_is_rejected_or_ignored(
    member_repo,
) -> None:
    """
    Sending membership_status (admin-only) via PUT /accounts/me/member must not apply the change.
    """
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    await member_repo.add(_seed_record(membership_status="active"))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(
            "/accounts/me/member",
            json={"membership_status": "inactive"},
        )

    assert response.status_code in (200, 422)
    if response.status_code == 200:
        assert response.json()["membership_status"] == "active"


async def test_put_my_member_is_first_aider_is_rejected_or_ignored(member_repo) -> None:
    """is_first_aider is an admin-only field."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    await member_repo.add(_seed_record(is_first_aider=False))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(
            "/accounts/me/member",
            json={"is_first_aider": True},
        )

    assert response.status_code in (200, 422)
    if response.status_code == 200:
        assert response.json()["is_first_aider"] is False


# ---------------------------------------------------------------------------
# AC4 (#432) — PUT /accounts/me/member never creates a Member
#
# Every Account belongs to a Member, created before the Account is (the first
# Admin's at the setup claim), so onboarding completes an existing record. An
# Account with none is a broken invariant, not a first save.
# ---------------------------------------------------------------------------


async def test_put_my_member_without_a_linked_record_is_404(member_repo) -> None:
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(
            "/accounts/me/member",
            json={"first_name": "Brand", "surname": "New", "dob": "1995-08-22"},
        )

    assert response.status_code == 404
    assert await member_repo.list() == []


# ---------------------------------------------------------------------------
# AC #159 — Partial-update field isolation and blank-dob preservation
# ---------------------------------------------------------------------------


async def test_put_my_member_display_name_only_preserves_first_and_surname(
    member_repo,
) -> None:
    """Saving only display_name must not overwrite first_name or surname."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    await member_repo.add(_seed_record(first_name="Taro", surname="Yamada"))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(
            "/accounts/me/member",
            json={"display_name": "Taro-san"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["display_name"] == "Taro-san"
    assert body["first_name"] == "Taro"
    assert body["surname"] == "Yamada"


async def test_put_my_member_omitting_dob_preserves_existing_dob(
    member_repo,
) -> None:
    """Sending no dob field must not clear the existing date of birth."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    await member_repo.add(_seed_record(dob="1990-06-15"))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(
            "/accounts/me/member",
            json={"display_name": "NoDobChange"},
        )

    assert response.status_code == 200
    assert response.json()["dob"] == "1990-06-15"


# ---------------------------------------------------------------------------
# Issue #249 — explicit null must clear clearable self-service fields, but
# must never wipe first_name/surname, and omitted fields must stay untouched.
# ---------------------------------------------------------------------------


async def test_put_my_member_explicit_null_clears_emergency_contact_phone(
    member_repo,
) -> None:
    """An explicit JSON null for emergency_contact_phone must clear the stored value."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    await member_repo.add(_seed_record(emergency_contact_phone="+447700900001"))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(
            "/accounts/me/member",
            json={"emergency_contact_phone": None},
        )

    assert response.status_code == 200
    assert response.json()["emergency_contact_phone"] is None


async def test_put_my_member_explicit_null_clear_persists_to_get(member_repo) -> None:
    """A cleared field via explicit null stays cleared on a subsequent GET."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    await member_repo.add(_seed_record(emergency_contact_phone="+447700900001"))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        await c.put(
            "/accounts/me/member",
            json={"emergency_contact_phone": None},
        )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        get_response = await c.get("/accounts/me/member")

    assert get_response.status_code == 200
    assert get_response.json()["emergency_contact_phone"] is None


async def test_put_my_member_explicit_null_clears_display_name(member_repo) -> None:
    """An explicit JSON null for display_name must clear the stored value."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    await member_repo.add(_seed_record(display_name="Taro-san"))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(
            "/accounts/me/member",
            json={"display_name": None},
        )

    assert response.status_code == 200
    assert response.json()["display_name"] is None


async def test_put_my_member_explicit_null_clears_emergency_contact_name(
    member_repo,
) -> None:
    """An explicit JSON null for emergency_contact_name must clear the stored value."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    await member_repo.add(_seed_record(emergency_contact_name="Emergency Contact"))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(
            "/accounts/me/member",
            json={"emergency_contact_name": None},
        )

    assert response.status_code == 200
    assert response.json()["emergency_contact_name"] is None


async def test_put_my_member_explicit_null_clears_dob(member_repo) -> None:
    """An explicit JSON null for dob must clear the stored date of birth.

    dob is clearable via explicit null on this self-service route, matching
    the admin route's semantics (#585) — unlike first-save
    onboarding, where a missing/null dob is still rejected with 422.
    """
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    await member_repo.add(_seed_record(dob="1990-06-15"))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(
            "/accounts/me/member",
            json={"dob": None},
        )

    assert response.status_code == 200
    assert response.json()["dob"] is None


async def test_put_my_member_omitted_emergency_contact_name_untouched(
    member_repo,
) -> None:
    """A field omitted entirely from the payload must be left untouched."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    await member_repo.add(_seed_record(emergency_contact_name="Emergency Contact"))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(
            "/accounts/me/member",
            json={"first_name": "StillSelf"},
        )

    assert response.status_code == 200
    assert response.json()["emergency_contact_name"] == "Emergency Contact"


async def test_put_my_member_explicit_null_first_name_does_not_wipe_value(
    member_repo,
) -> None:
    """An explicit null for first_name must not clear the stored value.

    first_name is required-by-domain on this route (unlike display_name/dob/
    emergency_contact_*), so a null there is refused with 422 (#585).
    """
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    await member_repo.add(_seed_record(first_name="Taro"))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(
            "/accounts/me/member",
            json={"first_name": None, "display_name": "Taro-san"},
        )
        stored = await c.get("/accounts/me/member")

    assert response.status_code == 422
    assert stored.json()["first_name"] == "Taro"
    assert stored.json()["display_name"] != "Taro-san"


async def test_put_my_member_explicit_null_surname_does_not_wipe_value(
    member_repo,
) -> None:
    """An explicit null for surname must not clear the stored value."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    await member_repo.add(_seed_record(surname="Yamada"))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(
            "/accounts/me/member",
            json={"surname": None, "display_name": "Taro-san"},
        )
        stored = await c.get("/accounts/me/member")

    assert response.status_code == 422
    assert stored.json()["surname"] == "Yamada"
    assert stored.json()["display_name"] != "Taro-san"
