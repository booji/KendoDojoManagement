"""
Unit / integration tests for issue #124 — Member federation memberships.

Uses StubRepository pattern — NO real DB. Dependencies are overridden via
app.dependency_overrides to inject in-memory stubs.

Acceptance criteria exercised here:
  1.  Members can add multiple federation memberships (federation_id, member_number,
      optional renewal_date)
  3.  Members can enter a membership number (free text, max 100 chars)
  4.  Members can optionally record a renewal date
  5.  Visual/computed warning: expiring_soon (≤30 days), expired, or None
  6.  Members can edit existing federation memberships
  7.  Members can remove a federation membership
  9.  Admins can manage memberships on any member via /members/{id}/federations
 10.  Members can manage their own via /accounts/me/federations; cannot access others'
 18.  Renewal date status is a computed field in the response, not stored
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.guards import REQUIRE_ADMIN, REQUIRE_MEMBER
from app.auth.models import AccountClaims
from app.federations.db_models import Federation
from app.federations.dependencies import get_federation_repo  # noqa: F401 — red
from app.main import app
from app.member_federations.dependencies import (  # noqa: F401 — red
    get_member_federation_repo,
)
from app.member_federations.repository import (
    MemberFederationRecord,
    SqlMemberFederationRepository,
)
from app.members.db_models import Member
from app.members.dependencies import get_member_repo  # noqa: F401
from tests.fake_repositories import InMemoryMemberRepository

# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

_MEMBER_A_ID = "aaaaaaaa-0000-0000-0000-00000000000a"
_FED_ID = "fedfedfe-0000-0000-0000-000000000001"

_ADMIN = AccountClaims(sub="admin-uuid", email="admin@dojo.test", role="admin")
_MEMBER_A = AccountClaims(
    sub=_MEMBER_A_ID,
    email="member-a@dojo.test",
    role="member",
)
_MEMBER_B = AccountClaims(
    sub="bbbbbbbb-0000-0000-0000-00000000000b",
    email="member-b@dojo.test",
    role="member",
)


def _admin_override():
    return _ADMIN


def _member_a_override():
    return _MEMBER_A


def _member_b_override():
    return _MEMBER_B


# ---------------------------------------------------------------------------
# Stub repositories
# ---------------------------------------------------------------------------

_MEMBER_A_RECORD: dict[str, Any] = {
    "id": _MEMBER_A_ID,
    "email": "member-a@dojo.test",
    "first_name": "Member",
    "surname": "A",
    "user_id": _MEMBER_A.sub,
    "membership_status": "active",
}

_MEMBER_B_RECORD: dict[str, Any] = {
    "id": "bbbbbbbb-0000-0000-0000-00000000000b",
    "email": "member-b@dojo.test",
    "first_name": "Member",
    "surname": "B",
    "user_id": _MEMBER_B.sub,
    "membership_status": "active",
}

_FED_RECORD: dict[str, Any] = {
    "id": _FED_ID,
    "name": "All Japan Kendo Federation",
    "abbreviation": "AJKF",
    "is_active": True,
    "is_pinned": False,
}


class StubFederationRepo:
    """Minimal in-memory federation repository."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {
            _FED_RECORD["id"]: dict(_FED_RECORD),
        }

    async def get(self, federation_id: str) -> dict[str, Any] | None:
        return self._store.get(federation_id)

    async def add(self, data: dict[str, Any]) -> dict[str, Any]:
        new_id = str(uuid.uuid4())
        record = {"id": new_id, "is_active": True, "is_pinned": False, **data}
        self._store[new_id] = record
        return record

    async def update(
        self, federation_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        record = self._store.get(federation_id)
        if record is None:
            return None
        record.update(data)
        return record

    async def deactivate(self, federation_id: str) -> dict[str, Any] | None:
        record = self._store.get(federation_id)
        if record is None:
            return None
        record["is_active"] = False
        return record

    async def list(
        self,
        type: str | None = None,
        continental_grouping: str | None = None,
        search: str | None = None,
        include_inactive: bool = False,
    ) -> list[dict[str, Any]]:
        results = list(self._store.values())
        if not include_inactive:
            results = [r for r in results if r.get("is_active", True)]
        return results


class StubMemberFederationRepo:
    """In-memory stand-in for a MemberFederation repository.

    Returns MemberFederationRecord, like the SQL implementation, and settles
    renewal_date to an ISO string the same way it does (#345).
    """

    def __init__(self) -> None:
        self._store: dict[str, MemberFederationRecord] = {}

    async def get(self, membership_id: str) -> MemberFederationRecord | None:
        return self._store.get(membership_id)

    async def get_for_member(self, member_id: str) -> list[MemberFederationRecord]:
        return [r for r in self._store.values() if r.member_id == member_id]

    async def add(self, data: dict[str, Any]) -> MemberFederationRecord:
        new_id = str(uuid.uuid4())
        record = MemberFederationRecord(id=new_id, **_iso_dates(data))
        self._store[new_id] = record
        return record

    async def update(
        self, membership_id: str, data: dict[str, Any]
    ) -> MemberFederationRecord | None:
        record = self._store.get(membership_id)
        if record is None:
            return None
        updated = record.model_copy(update=_iso_dates(data))
        self._store[membership_id] = updated
        return updated

    async def remove(self, membership_id: str) -> bool:
        if membership_id not in self._store:
            return False
        del self._store[membership_id]
        return True


def _iso_dates(data: dict[str, Any]) -> dict[str, Any]:
    """Mirror the SQL repository, which stores a date and reads back a string."""
    renewal = data.get("renewal_date")
    if renewal is None:
        return dict(data)
    return {**data, "renewal_date": getattr(renewal, "isoformat", lambda: renewal)()}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def member_repo() -> InMemoryMemberRepository:
    repo = InMemoryMemberRepository([_MEMBER_A_RECORD, _MEMBER_B_RECORD])
    app.dependency_overrides[get_member_repo] = lambda: repo
    return repo


@pytest.fixture()
def fed_repo() -> StubFederationRepo:
    repo = StubFederationRepo()
    app.dependency_overrides[get_federation_repo] = lambda: repo
    return repo


@pytest.fixture()
def mf_repo() -> StubMemberFederationRepo:
    repo = StubMemberFederationRepo()
    app.dependency_overrides[get_member_federation_repo] = lambda: repo
    return repo


# ---------------------------------------------------------------------------
# AC1/AC3 — POST /members/{id}/federations (admin manages any member)
# ---------------------------------------------------------------------------


async def test_admin_can_add_federation_membership(
    member_repo, fed_repo, mf_repo
) -> None:
    """AC1/AC9: Admin can add a federation membership to any member."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    member_id = _MEMBER_A_ID
    fed_id = _FED_ID

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            f"/members/{member_id}/federations",
            json={"federation_id": fed_id, "member_number": "AJKF-12345"},
        )
    assert response.status_code == 201
    body = response.json()
    assert "id" in body
    assert body["member_id"] == member_id
    assert body["federation_id"] == fed_id
    assert body["member_number"] == "AJKF-12345"


async def test_add_federation_membership_missing_federation_id_returns_422(
    member_repo, fed_repo, mf_repo
) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            f"/members/{_MEMBER_A_ID}/federations",
            json={"member_number": "12345"},
        )
    assert response.status_code == 422


async def test_add_federation_membership_missing_member_number_returns_422(
    member_repo, fed_repo, mf_repo
) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            f"/members/{_MEMBER_A_ID}/federations",
            json={"federation_id": _FED_ID},
        )
    assert response.status_code == 422


async def test_add_federation_membership_member_number_too_long_returns_422(
    member_repo, fed_repo, mf_repo
) -> None:
    """AC3: member_number has max 100 chars."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            f"/members/{_MEMBER_A_ID}/federations",
            json={
                "federation_id": _FED_ID,
                "member_number": "X" * 101,
            },
        )
    assert response.status_code == 422


async def test_add_federation_membership_max_100_chars_accepted(
    member_repo, fed_repo, mf_repo
) -> None:
    """AC3: exactly 100 chars is valid."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            f"/members/{_MEMBER_A_ID}/federations",
            json={
                "federation_id": _FED_ID,
                "member_number": "X" * 100,
            },
        )
    assert response.status_code == 201


async def test_add_federation_membership_member_not_found_returns_404(
    member_repo, fed_repo, mf_repo
) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    fake_id = str(uuid.uuid4())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            f"/members/{fake_id}/federations",
            json={
                "federation_id": _FED_ID,
                "member_number": "123",
            },
        )
    assert response.status_code == 404


@pytest.mark.parametrize(
    ("path", "override"),
    [
        (f"/members/{_MEMBER_A_ID}/federations", REQUIRE_ADMIN),
        ("/accounts/me/federations", REQUIRE_MEMBER),
    ],
)
async def test_add_federation_membership_unknown_federation_returns_422(
    member_repo, fed_repo, mf_repo, path, override
) -> None:
    """#586: an unknown federation_id is a 422, not an unmapped FK violation."""
    app.dependency_overrides[override] = _member_a_override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            path,
            json={"federation_id": str(uuid.uuid4()), "member_number": "123"},
        )
    assert response.status_code == 422
    assert response.json()["detail"] == "Federation not found"
    assert mf_repo._store == {}


async def test_add_federation_membership_unauthenticated_returns_401(
    member_repo, fed_repo, mf_repo
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            f"/members/{_MEMBER_A_ID}/federations",
            json={
                "federation_id": _FED_ID,
                "member_number": "123",
            },
        )
    assert response.status_code == 401


async def test_member_cannot_add_to_other_member_via_admin_endpoint(
    member_repo, fed_repo, mf_repo
) -> None:
    """AC10: Member cannot add to another member's federations via /members/{id}/federations."""
    from tests.auth_support import sign_in

    token = sign_in(_MEMBER_A)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/members/bbbbbbbb-0000-0000-0000-00000000000b/federations",
            json={
                "federation_id": _FED_ID,
                "member_number": "123",
            },
            cookies={"access_token": token},
        )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# AC4 — Optional renewal_date
# ---------------------------------------------------------------------------


async def test_add_membership_with_renewal_date(member_repo, fed_repo, mf_repo) -> None:
    """AC4: renewal_date is stored when provided."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            f"/members/{_MEMBER_A_ID}/federations",
            json={
                "federation_id": _FED_ID,
                "member_number": "AJKF-001",
                "renewal_date": "2026-04-01",
            },
        )
    assert response.status_code == 201
    assert response.json()["renewal_date"] == "2026-04-01"


async def test_add_membership_without_renewal_date(
    member_repo, fed_repo, mf_repo
) -> None:
    """AC4: renewal_date is optional — None when not supplied."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            f"/members/{_MEMBER_A_ID}/federations",
            json={
                "federation_id": _FED_ID,
                "member_number": "AJKF-002",
            },
        )
    assert response.status_code == 201
    assert response.json()["renewal_date"] is None


# ---------------------------------------------------------------------------
# AC5/AC18 — Renewal date status computed field
# ---------------------------------------------------------------------------


async def test_renewal_status_none_when_no_date(member_repo, fed_repo, mf_repo) -> None:
    """AC5/AC18: renewal_status is None when no renewal_date."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            f"/members/{_MEMBER_A_ID}/federations",
            json={
                "federation_id": _FED_ID,
                "member_number": "AJKF-003",
            },
        )
    assert response.status_code == 201
    assert response.json()["renewal_status"] is None


async def test_renewal_status_expired_when_past_date(
    member_repo, fed_repo, mf_repo
) -> None:
    """AC5/AC18: renewal_status is 'expired' when renewal_date is in the past."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    past_date = (date.today() - timedelta(days=1)).isoformat()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            f"/members/{_MEMBER_A_ID}/federations",
            json={
                "federation_id": _FED_ID,
                "member_number": "AJKF-004",
                "renewal_date": past_date,
            },
        )
    assert response.status_code == 201
    assert response.json()["renewal_status"] == "expired"


async def test_renewal_status_expiring_soon_within_30_days(
    member_repo, fed_repo, mf_repo
) -> None:
    """AC5/AC18: renewal_status is 'expiring_soon' when within 30 days from today."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    soon_date = (date.today() + timedelta(days=15)).isoformat()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            f"/members/{_MEMBER_A_ID}/federations",
            json={
                "federation_id": _FED_ID,
                "member_number": "AJKF-005",
                "renewal_date": soon_date,
            },
        )
    assert response.status_code == 201
    assert response.json()["renewal_status"] == "expiring_soon"


async def test_renewal_status_expiring_soon_exactly_30_days(
    member_repo, fed_repo, mf_repo
) -> None:
    """AC5/AC18: renewal_status is 'expiring_soon' when exactly 30 days away."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    boundary_date = (date.today() + timedelta(days=30)).isoformat()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            f"/members/{_MEMBER_A_ID}/federations",
            json={
                "federation_id": _FED_ID,
                "member_number": "AJKF-006",
                "renewal_date": boundary_date,
            },
        )
    assert response.status_code == 201
    assert response.json()["renewal_status"] == "expiring_soon"


async def test_renewal_status_ok_when_beyond_30_days(
    member_repo, fed_repo, mf_repo
) -> None:
    """AC5: No warning when renewal_date is more than 30 days away — status should be None or 'ok'."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    future_date = (date.today() + timedelta(days=31)).isoformat()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            f"/members/{_MEMBER_A_ID}/federations",
            json={
                "federation_id": _FED_ID,
                "member_number": "AJKF-007",
                "renewal_date": future_date,
            },
        )
    assert response.status_code == 201
    # Status must NOT be expired or expiring_soon
    assert response.json()["renewal_status"] not in ("expired", "expiring_soon")


# ---------------------------------------------------------------------------
# AC6 — Edit existing membership (PUT /members/{id}/federations/{mf_id})
# ---------------------------------------------------------------------------


async def test_admin_can_edit_federation_membership(
    member_repo, fed_repo, mf_repo
) -> None:
    """AC6/AC9: Admin can edit an existing membership's member_number or renewal_date."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    # Seed a membership directly in the stub
    membership = await mf_repo.add(
        {
            "member_id": _MEMBER_A_ID,
            "federation_id": _FED_ID,
            "member_number": "OLD-001",
        }
    )
    mf_id = membership.id

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(
            f"/members/{_MEMBER_A_ID}/federations/{mf_id}",
            json={"member_number": "NEW-999"},
        )
    assert response.status_code == 200
    assert response.json()["member_number"] == "NEW-999"


async def test_admin_can_update_renewal_date(member_repo, fed_repo, mf_repo) -> None:
    """AC6: Admin can update the renewal_date on an existing membership."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    membership = await mf_repo.add(
        {
            "member_id": _MEMBER_A_ID,
            "federation_id": _FED_ID,
            "member_number": "AJKF-010",
        }
    )
    mf_id = membership.id
    new_date = (date.today() + timedelta(days=365)).isoformat()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(
            f"/members/{_MEMBER_A_ID}/federations/{mf_id}",
            json={"renewal_date": new_date},
        )
    assert response.status_code == 200
    assert response.json()["renewal_date"] == new_date


async def test_admin_can_clear_renewal_date(member_repo, fed_repo, mf_repo) -> None:
    """#585: a mistyped renewal date can be removed, not just replaced."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    membership = await mf_repo.add(
        {
            "member_id": _MEMBER_A_ID,
            "federation_id": _FED_ID,
            "member_number": "AJKF-011",
            "renewal_date": date(2001, 1, 1),
        }
    )
    url = f"/members/{_MEMBER_A_ID}/federations/{membership.id}"

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(url, json={"renewal_date": None})
        refused = await c.put(url, json={"member_number": None})
    assert response.status_code == 200
    assert response.json()["renewal_date"] is None
    assert response.json()["member_number"] == "AJKF-011"
    assert refused.status_code == 422


async def test_edit_federation_membership_not_found_returns_404(
    member_repo, fed_repo, mf_repo
) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    fake_id = str(uuid.uuid4())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(
            f"/members/{_MEMBER_A_ID}/federations/{fake_id}",
            json={"member_number": "Ghost"},
        )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# AC7 — Remove a federation membership (DELETE)
# ---------------------------------------------------------------------------


async def test_admin_can_remove_federation_membership(
    member_repo, fed_repo, mf_repo
) -> None:
    """AC7/AC9: Admin can delete a federation membership."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    membership = await mf_repo.add(
        {
            "member_id": _MEMBER_A_ID,
            "federation_id": _FED_ID,
            "member_number": "TO-BE-REMOVED",
        }
    )
    mf_id = membership.id

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.delete(f"/members/{_MEMBER_A_ID}/federations/{mf_id}")
    assert response.status_code == 204


async def test_remove_federation_membership_not_found_returns_404(
    member_repo, fed_repo, mf_repo
) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    fake_id = str(uuid.uuid4())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.delete(f"/members/{_MEMBER_A_ID}/federations/{fake_id}")
    assert response.status_code == 404


async def test_remove_federation_membership_unauthenticated_returns_401(
    member_repo, fed_repo, mf_repo
) -> None:
    membership = await mf_repo.add(
        {
            "member_id": _MEMBER_A_ID,
            "federation_id": _FED_ID,
            "member_number": "UNAUTH",
        }
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.delete(
            f"/members/{_MEMBER_A_ID}/federations/{membership.id}"
        )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# AC9 — GET /members/{id}/federations (admin)
# ---------------------------------------------------------------------------


async def test_admin_can_list_member_federations(
    member_repo, fed_repo, mf_repo
) -> None:
    """AC9: Admin can list all federation memberships for any member."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    await mf_repo.add(
        {
            "member_id": _MEMBER_A_ID,
            "federation_id": _FED_ID,
            "member_number": "AJKF-100",
        }
    )
    await mf_repo.add(
        {
            "member_id": _MEMBER_A_ID,
            "federation_id": _FED_ID,
            "member_number": "AJKF-200",
        }
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get(f"/members/{_MEMBER_A_ID}/federations")
    assert response.status_code == 200
    assert len(response.json()) == 2


async def test_get_member_federations_not_found_returns_404(
    member_repo, fed_repo, mf_repo
) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    fake_id = str(uuid.uuid4())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get(f"/members/{fake_id}/federations")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# AC10 — /accounts/me/federations (member self-service)
# ---------------------------------------------------------------------------


async def test_member_can_add_own_federation_membership(
    member_repo, fed_repo, mf_repo
) -> None:
    """AC10: Member can add a federation membership to their own profile."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_a_override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/accounts/me/federations",
            json={
                "federation_id": _FED_ID,
                "member_number": "SELF-001",
            },
        )
    assert response.status_code == 201
    body = response.json()
    assert body["member_id"] == _MEMBER_A.sub
    assert body["member_number"] == "SELF-001"


async def test_member_can_list_own_federation_memberships(
    member_repo, fed_repo, mf_repo
) -> None:
    """AC10: Member can list their own federation memberships."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_a_override
    await mf_repo.add(
        {
            "member_id": _MEMBER_A.sub,
            "federation_id": _FED_ID,
            "member_number": "SELF-A",
        }
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/accounts/me/federations")
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["member_number"] == "SELF-A"


async def test_member_can_edit_own_federation_membership(
    member_repo, fed_repo, mf_repo
) -> None:
    """AC10: Member can edit their own membership."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_a_override
    membership = await mf_repo.add(
        {
            "member_id": _MEMBER_A.sub,
            "federation_id": _FED_ID,
            "member_number": "BEFORE",
        }
    )
    mf_id = membership.id
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(
            f"/accounts/me/federations/{mf_id}",
            json={"member_number": "AFTER"},
        )
    assert response.status_code == 200
    assert response.json()["member_number"] == "AFTER"


async def test_member_can_clear_own_renewal_date(
    member_repo, fed_repo, mf_repo
) -> None:
    """#585: the self-service route clears a renewal date sent as null."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_a_override
    membership = await mf_repo.add(
        {
            "member_id": _MEMBER_A.sub,
            "federation_id": _FED_ID,
            "member_number": "OWN-001",
            "renewal_date": date(2001, 1, 1),
        }
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(
            f"/accounts/me/federations/{membership.id}",
            json={"renewal_date": None},
        )
    assert response.status_code == 200
    assert response.json()["renewal_date"] is None


async def test_member_can_remove_own_federation_membership(
    member_repo, fed_repo, mf_repo
) -> None:
    """AC10: Member can remove their own membership."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_a_override
    membership = await mf_repo.add(
        {
            "member_id": _MEMBER_A.sub,
            "federation_id": _FED_ID,
            "member_number": "REMOVE-ME",
        }
    )
    mf_id = membership.id
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.delete(f"/accounts/me/federations/{mf_id}")
    assert response.status_code == 204


async def test_member_cannot_edit_other_members_federation_via_me_endpoint(
    member_repo, fed_repo, mf_repo
) -> None:
    """AC10: Member B cannot edit Member A's federation membership via /accounts/me/federations."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_b_override
    # A membership belonging to member A
    membership = await mf_repo.add(
        {
            "member_id": _MEMBER_A.sub,
            "federation_id": _FED_ID,
            "member_number": "MEMBER-A-ONLY",
        }
    )
    mf_id = membership.id
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(
            f"/accounts/me/federations/{mf_id}",
            json={"member_number": "STOLEN"},
        )
    assert response.status_code == 404


async def test_member_cannot_delete_other_members_federation_via_me_endpoint(
    member_repo, fed_repo, mf_repo
) -> None:
    """AC10: Member B cannot delete Member A's membership via /accounts/me/federations."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_b_override
    membership = await mf_repo.add(
        {
            "member_id": _MEMBER_A.sub,
            "federation_id": _FED_ID,
            "member_number": "MEMBER-A-ONLY-2",
        }
    )
    mf_id = membership.id
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.delete(f"/accounts/me/federations/{mf_id}")
    assert response.status_code == 404


async def test_me_federations_unauthenticated_returns_401(
    member_repo, fed_repo, mf_repo
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/accounts/me/federations")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# The repository seam settles the date type itself (#345)
# ---------------------------------------------------------------------------


async def _seed_member_and_federation(db_session) -> tuple[str, str]:
    """Insert the two rows a membership needs to point at."""
    member = Member(
        email="seam@dojo.test",
        first_name="Seam",
        surname="Test",
        join_date="2026-01-01",
        membership_status="active",
    )
    federation = Federation(name="Seam Federation")
    db_session.add_all([member, federation])
    await db_session.flush()
    return member.id, federation.id


async def test_add_accepts_a_date_and_reads_back_an_iso_string(db_session) -> None:
    """The seam settles the type: a date goes in, an ISO string comes out.

    Callers used to convert before writing — the router did it in four places
    — because nothing said which of the two a repository wanted.
    """
    member_id, federation_id = await _seed_member_and_federation(db_session)
    repo = SqlMemberFederationRepository(db_session)

    record = await repo.add(
        {
            "member_id": member_id,
            "federation_id": federation_id,
            "member_number": "SEAM-1",
            "renewal_date": date(2027, 3, 1),
        }
    )

    assert record.renewal_date == "2027-03-01"
    assert (await repo.get(record.id)).renewal_date == "2027-03-01"


async def test_add_still_accepts_an_iso_string(db_session) -> None:
    """The other half of settling it: a string is understood too, and stored
    as a date rather than reaching the Date column as text."""
    member_id, federation_id = await _seed_member_and_federation(db_session)
    repo = SqlMemberFederationRepository(db_session)

    record = await repo.add(
        {
            "member_id": member_id,
            "federation_id": federation_id,
            "member_number": "SEAM-2",
            "renewal_date": "2027-04-01",
        }
    )

    assert record.renewal_date == "2027-04-01"


async def test_update_refuses_a_key_that_is_not_a_column(db_session) -> None:
    """A silently dropped write is a call that reports success and does
    nothing. The in-memory fakes already refuse one (#337); so does this."""
    member_id, federation_id = await _seed_member_and_federation(db_session)
    repo = SqlMemberFederationRepository(db_session)
    record = await repo.add(
        {
            "member_id": member_id,
            "federation_id": federation_id,
            "member_number": "SEAM-3",
        }
    )

    with pytest.raises(TypeError, match="not a column"):
        await repo.update(record.id, {"membre_number": "typo"})
