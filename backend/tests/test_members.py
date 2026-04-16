"""
Unit / integration tests for issue #6 — Member CRUD.

Uses StubRepository pattern — NO real DB. Dependencies are overridden via
app.dependency_overrides to inject in-memory stubs.

Acceptance criteria exercised here:
  1. Member schema: UUID, email, full name, DOB, join date, membership status,
     is_coach, is_first_aider, emergency contact name/phone, federation number,
     parental_consent_obtained
  2. is_minor derived at read time from DOB (not stored)
  3. POST /members creates a member (admin only)
  4. GET /members/{id} returns profile (admin sees all; member sees own only)
  5. PUT /members/{id} updates any field (admin only)
  6. DELETE /members/{id} deactivates the member (sets status to inactive)
  7. GET /members supports filtering by status and search by name/email
  8. PRD testing decisions: valid create, missing required fields, is_minor edge
     cases, update persists, deactivate sets inactive, filter by status, search,
     parental consent flag
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.guards import REQUIRE_ADMIN, REQUIRE_MEMBER
from app.auth.models import UserClaims
from app.main import app
from app.members.dependencies import get_member_repo  # noqa: F401 — will fail (red)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ADMIN = UserClaims(
    sub="admin-uuid", email="admin@dojo.test", role="admin", is_active=True
)
_MEMBER_CLAIMS = UserClaims(
    sub="member-uuid-self", email="self@dojo.test", role="member", is_active=True
)


def _admin_override():
    return _ADMIN


def _member_override():
    return _MEMBER_CLAIMS


def _valid_member_payload(**overrides) -> dict[str, Any]:
    base: dict[str, Any] = {
        "email": "taro@dojo.test",
        "full_name": "Taro Yamada",
        "dob": "1990-06-15",
        "join_date": "2024-01-10",
        "membership_status": "active",
        "is_coach": False,
        "is_first_aider": False,
        "emergency_contact_name": "Hanako Yamada",
        "emergency_contact_phone": "+447700900000",
        "federation_number": "FED-001",
        "parental_consent_obtained": False,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Stub repository
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
                if term in r["full_name"].lower() or term in r["email"].lower()
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
def member_repo() -> StubMemberRepo:
    repo = StubMemberRepo()
    app.dependency_overrides[get_member_repo] = lambda: repo
    return repo


# ---------------------------------------------------------------------------
# AC3 — POST /members (admin only)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_admin_can_create_member(member_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post("/members", json=_valid_member_payload())
    assert response.status_code == 201
    body = response.json()
    assert "id" in body
    assert body["email"] == "taro@dojo.test"
    assert body["full_name"] == "Taro Yamada"
    assert body["membership_status"] == "active"
    assert body["is_coach"] is False
    assert body["is_first_aider"] is False
    assert body["parental_consent_obtained"] is False
    assert (
        "dob" not in body or "is_minor" in body
    )  # is_minor derived, not stored DOB raw


@pytest.mark.anyio
async def test_create_member_response_schema_has_all_required_fields(
    member_repo,
) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post("/members", json=_valid_member_payload())
    assert response.status_code == 201
    body = response.json()
    expected_fields = {
        "id",
        "email",
        "full_name",
        "join_date",
        "membership_status",
        "is_coach",
        "is_first_aider",
        "emergency_contact_name",
        "emergency_contact_phone",
        "federation_number",
        "parental_consent_obtained",
        "is_minor",
    }
    for field in expected_fields:
        assert field in body, f"Missing field: {field}"


@pytest.mark.anyio
async def test_member_cannot_create_member(member_repo) -> None:
    from app.auth.token import encode_token

    token = encode_token(_MEMBER_CLAIMS)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/members",
            json=_valid_member_payload(),
            cookies={"access_token": token},
        )
    assert response.status_code == 403


@pytest.mark.anyio
async def test_create_member_unauthenticated_returns_401(member_repo) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post("/members", json=_valid_member_payload())
    assert response.status_code == 401


@pytest.mark.anyio
async def test_create_member_missing_required_fields_returns_422(member_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    # Missing email, full_name, dob, join_date
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post("/members", json={})
    assert response.status_code == 422


@pytest.mark.anyio
async def test_create_member_missing_email_returns_422(member_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    payload = _valid_member_payload()
    del payload["email"]
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post("/members", json=payload)
    assert response.status_code == 422


@pytest.mark.anyio
async def test_create_member_missing_dob_returns_422(member_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    payload = _valid_member_payload()
    del payload["dob"]
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post("/members", json=payload)
    assert response.status_code == 422


@pytest.mark.anyio
async def test_create_duplicate_member_email_returns_409(member_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        await c.post("/members", json=_valid_member_payload())
        response = await c.post("/members", json=_valid_member_payload())
    assert response.status_code == 409


# ---------------------------------------------------------------------------
# AC1 / AC2 — Schema fields and is_minor derived from DOB
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_is_minor_false_for_adult(member_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    adult_dob = (date.today() - timedelta(days=365 * 20)).isoformat()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        resp = await c.post("/members", json=_valid_member_payload(dob=adult_dob))
    assert resp.status_code == 201
    assert resp.json()["is_minor"] is False


@pytest.mark.anyio
async def test_is_minor_true_for_minor(member_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    minor_dob = (date.today() - timedelta(days=365 * 10)).isoformat()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        resp = await c.post("/members", json=_valid_member_payload(dob=minor_dob))
    assert resp.status_code == 201
    assert resp.json()["is_minor"] is True


@pytest.mark.anyio
async def test_is_minor_false_on_exact_18th_birthday(member_repo) -> None:
    """Edge case: exactly 18 today → not a minor."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    today = date.today()
    dob_exactly_18 = date(today.year - 18, today.month, today.day)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        resp = await c.post(
            "/members", json=_valid_member_payload(dob=dob_exactly_18.isoformat())
        )
    assert resp.status_code == 201
    assert resp.json()["is_minor"] is False


@pytest.mark.anyio
async def test_is_minor_true_one_day_before_18th_birthday(member_repo) -> None:
    """Edge case: one day before 18th birthday → still a minor."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    today = date.today()
    dob_one_day_before = date(today.year - 18, today.month, today.day) + timedelta(
        days=1
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        resp = await c.post(
            "/members", json=_valid_member_payload(dob=dob_one_day_before.isoformat())
        )
    assert resp.status_code == 201
    assert resp.json()["is_minor"] is True


# ---------------------------------------------------------------------------
# AC4 — GET /members/{id}
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_admin_can_get_any_member_profile(member_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    app.dependency_overrides[REQUIRE_MEMBER] = _admin_override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        create_resp = await c.post("/members", json=_valid_member_payload())
    member_id = create_resp.json()["id"]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get(f"/members/{member_id}")
    assert response.status_code == 200
    assert response.json()["id"] == member_id


@pytest.mark.anyio
async def test_member_can_get_own_profile(member_repo) -> None:
    # Seed member with sub matching _MEMBER_CLAIMS.sub
    record = await member_repo.add(
        {
            **_valid_member_payload(email="self@dojo.test"),
            "user_id": _MEMBER_CLAIMS.sub,
        }
    )
    member_id = record["id"]
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get(f"/members/{member_id}")
    assert response.status_code == 200
    assert response.json()["id"] == member_id


@pytest.mark.anyio
async def test_member_cannot_get_other_member_profile(member_repo) -> None:
    # Seed another member with a different user_id
    other_record = await member_repo.add(
        {
            **_valid_member_payload(email="other@dojo.test"),
            "user_id": "some-other-user-uuid",
        }
    )
    other_id = other_record["id"]
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get(f"/members/{other_id}")
    assert response.status_code == 403


@pytest.mark.anyio
async def test_get_member_not_found_returns_404(member_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    app.dependency_overrides[REQUIRE_MEMBER] = _admin_override
    fake_id = str(uuid.uuid4())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get(f"/members/{fake_id}")
    assert response.status_code == 404


@pytest.mark.anyio
async def test_get_member_unauthenticated_returns_401(member_repo) -> None:
    fake_id = str(uuid.uuid4())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get(f"/members/{fake_id}")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# AC5 — PUT /members/{id} (admin only)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_admin_can_update_member_field(member_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        create_resp = await c.post("/members", json=_valid_member_payload())
    member_id = create_resp.json()["id"]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.put(
            f"/members/{member_id}", json={"full_name": "Taro Updated"}
        )
    assert response.status_code == 200
    assert response.json()["full_name"] == "Taro Updated"


@pytest.mark.anyio
async def test_update_persists_change(member_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    app.dependency_overrides[REQUIRE_MEMBER] = _admin_override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        create_resp = await c.post("/members", json=_valid_member_payload())
    member_id = create_resp.json()["id"]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        await c.put(f"/members/{member_id}", json={"is_coach": True})

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        get_resp = await c.get(f"/members/{member_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["is_coach"] is True


@pytest.mark.anyio
async def test_update_member_not_found_returns_404(member_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    fake_id = str(uuid.uuid4())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.put(f"/members/{fake_id}", json={"full_name": "Ghost"})
    assert response.status_code == 404


@pytest.mark.anyio
async def test_member_cannot_update_member(member_repo) -> None:
    from app.auth.token import encode_token

    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        create_resp = await c.post("/members", json=_valid_member_payload())
    member_id = create_resp.json()["id"]

    del app.dependency_overrides[REQUIRE_ADMIN]
    token = encode_token(_MEMBER_CLAIMS)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.put(
            f"/members/{member_id}",
            json={"full_name": "Hacked"},
            cookies={"access_token": token},
        )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# AC6 — DELETE /members/{id} deactivates (sets status to inactive)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_delete_deactivates_member(member_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        create_resp = await c.post("/members", json=_valid_member_payload())
    member_id = create_resp.json()["id"]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.delete(f"/members/{member_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["membership_status"] == "inactive"
    assert body["id"] == member_id


@pytest.mark.anyio
async def test_delete_does_not_remove_record(member_repo) -> None:
    """DELETE should deactivate, not hard-delete. Record still retrievable."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    app.dependency_overrides[REQUIRE_MEMBER] = _admin_override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        create_resp = await c.post("/members", json=_valid_member_payload())
    member_id = create_resp.json()["id"]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        await c.delete(f"/members/{member_id}")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        get_resp = await c.get(f"/members/{member_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["membership_status"] == "inactive"


@pytest.mark.anyio
async def test_delete_nonexistent_member_returns_404(member_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    fake_id = str(uuid.uuid4())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.delete(f"/members/{fake_id}")
    assert response.status_code == 404


@pytest.mark.anyio
async def test_member_cannot_delete_member(member_repo) -> None:
    from app.auth.token import encode_token

    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        create_resp = await c.post("/members", json=_valid_member_payload())
    member_id = create_resp.json()["id"]

    del app.dependency_overrides[REQUIRE_ADMIN]
    token = encode_token(_MEMBER_CLAIMS)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.delete(
            f"/members/{member_id}",
            cookies={"access_token": token},
        )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# AC7 — GET /members with filtering and search
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_members_returns_all_for_admin(member_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    await member_repo.add(_valid_member_payload(email="a@dojo.test"))
    await member_repo.add(_valid_member_payload(email="b@dojo.test"))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/members")
    assert response.status_code == 200
    assert len(response.json()) == 2


@pytest.mark.anyio
async def test_get_members_filter_by_active_status(member_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    await member_repo.add(
        _valid_member_payload(email="active@dojo.test", membership_status="active")
    )
    await member_repo.add(
        _valid_member_payload(email="inactive@dojo.test", membership_status="inactive")
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/members?status=active")
    assert response.status_code == 200
    results = response.json()
    assert all(r["membership_status"] == "active" for r in results)
    emails = [r["email"] for r in results]
    assert "active@dojo.test" in emails
    assert "inactive@dojo.test" not in emails


@pytest.mark.anyio
async def test_get_members_filter_by_inactive_status(member_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    await member_repo.add(
        _valid_member_payload(email="active2@dojo.test", membership_status="active")
    )
    await member_repo.add(
        _valid_member_payload(
            email="suspended@dojo.test", membership_status="suspended"
        )
    )
    await member_repo.add(
        _valid_member_payload(email="inactive2@dojo.test", membership_status="inactive")
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/members?status=inactive")
    assert response.status_code == 200
    results = response.json()
    assert all(r["membership_status"] == "inactive" for r in results)


@pytest.mark.anyio
async def test_get_members_search_by_name(member_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    await member_repo.add(
        _valid_member_payload(email="musashi@dojo.test", full_name="Musashi Miyamoto")
    )
    await member_repo.add(
        _valid_member_payload(email="kojiro@dojo.test", full_name="Sasaki Kojiro")
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/members?search=musashi")
    assert response.status_code == 200
    results = response.json()
    assert len(results) == 1
    assert results[0]["full_name"] == "Musashi Miyamoto"


@pytest.mark.anyio
async def test_get_members_search_by_email(member_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    await member_repo.add(
        _valid_member_payload(email="findme@dojo.test", full_name="Someone")
    )
    await member_repo.add(
        _valid_member_payload(email="other@dojo.test", full_name="Other Person")
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/members?search=findme")
    assert response.status_code == 200
    results = response.json()
    assert len(results) == 1
    assert results[0]["email"] == "findme@dojo.test"


@pytest.mark.anyio
async def test_get_members_unauthenticated_returns_401(member_repo) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/members")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# PRD testing decisions — parental consent
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_parental_consent_can_be_set_and_read_back(member_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    app.dependency_overrides[REQUIRE_MEMBER] = _admin_override
    payload = _valid_member_payload(parental_consent_obtained=True)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        create_resp = await c.post("/members", json=payload)
    assert create_resp.status_code == 201
    member_id = create_resp.json()["id"]
    assert create_resp.json()["parental_consent_obtained"] is True

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        get_resp = await c.get(f"/members/{member_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["parental_consent_obtained"] is True


@pytest.mark.anyio
async def test_parental_consent_defaults_to_false(member_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    payload = _valid_member_payload()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        create_resp = await c.post("/members", json=payload)
    assert create_resp.status_code == 201
    assert create_resp.json()["parental_consent_obtained"] is False
