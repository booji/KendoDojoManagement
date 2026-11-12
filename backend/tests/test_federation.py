"""
Unit / integration tests for issue #124 — Federation catalogue management.

Uses StubRepository pattern — NO real DB. Dependencies are overridden via
app.dependency_overrides to inject in-memory stubs.

Acceptance criteria exercised here:
  8.  Pinned federations float to top of selection lists
 11.  Admins can add new federations to the catalogue (POST /federations)
 12.  Admins can edit federation metadata (PUT /federations/{id})
 13.  Admins can pin/unpin a federation (PUT /federations/{id} with is_pinned)
 14.  Admins can deactivate a federation (DELETE /federations/{id} sets is_active=false)
 15.  Admins can reactivate a deactivated federation (PUT /federations/{id} with is_active=true)
 16.  GET /federations returns active, ordered pinned-first, supports filters
 17.  POST/PUT/DELETE are admin-only; GET requires any authenticated user
 19.  Inactive federations hidden from list but preserved for referential integrity
 20.  federation_number column no longer on members table
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.guards import REQUIRE_ADMIN, REQUIRE_MEMBER
from app.auth.models import AccountClaims
from app.federations.dependencies import get_federation_repo  # noqa: F401 — red
from app.main import app

# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

_ADMIN = AccountClaims(sub="admin-uuid", email="admin@dojo.test", role="admin")
_MEMBER = AccountClaims(sub="member-uuid", email="member@dojo.test", role="member")


def _admin_override():
    return _ADMIN


def _member_override():
    return _MEMBER


# ---------------------------------------------------------------------------
# Stub repository
# ---------------------------------------------------------------------------


class StubFederationRepo:
    """In-memory stand-in for a Federation repository."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    async def get(self, federation_id: str) -> dict[str, Any] | None:
        return self._store.get(federation_id)

    async def add(self, data: dict[str, Any]) -> dict[str, Any]:
        new_id = str(uuid.uuid4())
        record: dict[str, Any] = {
            "id": new_id,
            "is_pinned": False,
            "is_active": True,
            "abbreviation": None,
            "iso_code": None,
            "website": None,
            "continental_grouping": None,
            "type": None,
            **data,
        }
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
        if type is not None:
            results = [r for r in results if r.get("type") == type]
        if continental_grouping is not None:
            results = [
                r
                for r in results
                if r.get("continental_grouping") == continental_grouping
            ]
        if search is not None:
            term = search.lower()
            results = [
                r
                for r in results
                if r["name"].lower().startswith(term)
                or (r.get("abbreviation") or "").lower().startswith(term)
            ]
        # Ordering: pinned-first alpha, then unpinned alpha
        pinned = sorted(
            [r for r in results if r.get("is_pinned")], key=lambda r: r["name"]
        )
        unpinned = sorted(
            [r for r in results if not r.get("is_pinned")], key=lambda r: r["name"]
        )
        return pinned + unpinned


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def fed_repo() -> StubFederationRepo:
    repo = StubFederationRepo()
    app.dependency_overrides[get_federation_repo] = lambda: repo
    return repo


# ---------------------------------------------------------------------------
# AC11 — POST /federations (admin only)
# ---------------------------------------------------------------------------


async def test_admin_can_create_federation(fed_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/federations", json={"name": "All Japan Kendo Federation"}
        )
    assert response.status_code == 201
    body = response.json()
    assert "id" in body
    assert body["name"] == "All Japan Kendo Federation"
    assert body["is_active"] is True
    assert body["is_pinned"] is False


async def test_create_federation_missing_name_returns_422(fed_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post("/federations", json={})
    assert response.status_code == 422


async def test_create_federation_with_all_optional_fields(fed_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    payload = {
        "name": "British Kendo Association",
        "abbreviation": "BKA",
        "iso_code": "GB",
        "website": "https://www.kendo.org.uk",
        "continental_grouping": "Europe",
        "type": "National",
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post("/federations", json=payload)
    assert response.status_code == 201
    body = response.json()
    assert body["abbreviation"] == "BKA"
    assert body["iso_code"] == "GB"
    assert body["website"] == "https://www.kendo.org.uk"
    assert body["continental_grouping"] == "Europe"
    assert body["type"] == "National"


async def test_create_federation_unauthenticated_returns_401(fed_repo) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/federations", json={"name": "Unauthenticated Federation"}
        )
    assert response.status_code == 401


async def test_member_cannot_create_federation(fed_repo) -> None:
    from tests.auth_support import sign_in

    token = sign_in(_MEMBER)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/federations",
            json={"name": "Member Attempt"},
            cookies={"access_token": token},
        )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# AC12 — PUT /federations/{id} (admin only)
# ---------------------------------------------------------------------------


async def test_admin_can_edit_federation_metadata(fed_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    record = await fed_repo.add({"name": "Old Name"})
    fed_id = record["id"]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(f"/federations/{fed_id}", json={"name": "New Name"})
    assert response.status_code == 200
    assert response.json()["name"] == "New Name"


async def test_edit_federation_clears_a_field_sent_as_null(fed_repo) -> None:
    """#585: a federation's abbreviation or website can be removed."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    record = await fed_repo.add(
        {"name": "AJKF", "abbreviation": "AJ", "website": "https://ajkf.example"}
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(
            f"/federations/{record['id']}",
            json={"abbreviation": None, "website": None},
        )
        refused = await c.put(f"/federations/{record['id']}", json={"name": None})
    assert response.status_code == 200
    assert response.json()["abbreviation"] is None
    assert response.json()["website"] is None
    assert response.json()["name"] == "AJKF"
    assert refused.status_code == 422


async def test_edit_federation_not_found_returns_404(fed_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    fake_id = str(uuid.uuid4())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(f"/federations/{fake_id}", json={"name": "Ghost"})
    assert response.status_code == 404


async def test_edit_federation_unauthenticated_returns_401(fed_repo) -> None:
    record = await fed_repo.add({"name": "Test Fed"})
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(f"/federations/{record['id']}", json={"name": "Hack"})
    assert response.status_code == 401


async def test_member_cannot_edit_federation(fed_repo) -> None:
    from tests.auth_support import sign_in

    record = await fed_repo.add({"name": "Test Fed"})
    token = sign_in(_MEMBER)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(
            f"/federations/{record['id']}",
            json={"name": "Hacked"},
            cookies={"access_token": token},
        )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# AC13 — Pin/unpin via PUT /federations/{id}
# ---------------------------------------------------------------------------


async def test_admin_can_pin_federation(fed_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    record = await fed_repo.add({"name": "Pinnable Fed"})
    fed_id = record["id"]
    assert record["is_pinned"] is False

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(f"/federations/{fed_id}", json={"is_pinned": True})
    assert response.status_code == 200
    assert response.json()["is_pinned"] is True


async def test_admin_can_unpin_federation(fed_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    record = await fed_repo.add({"name": "Pinned Fed", "is_pinned": True})
    fed_id = record["id"]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(f"/federations/{fed_id}", json={"is_pinned": False})
    assert response.status_code == 200
    assert response.json()["is_pinned"] is False


# ---------------------------------------------------------------------------
# AC14 — DELETE /federations/{id} soft-deletes (sets is_active=false)
# ---------------------------------------------------------------------------


async def test_admin_can_deactivate_federation(fed_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    record = await fed_repo.add({"name": "Active Fed"})
    fed_id = record["id"]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.delete(f"/federations/{fed_id}")
    assert response.status_code == 200
    assert response.json()["is_active"] is False


async def test_deactivate_nonexistent_federation_returns_404(fed_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    fake_id = str(uuid.uuid4())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.delete(f"/federations/{fake_id}")
    assert response.status_code == 404


async def test_delete_federation_unauthenticated_returns_401(fed_repo) -> None:
    record = await fed_repo.add({"name": "Test Fed"})
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.delete(f"/federations/{record['id']}")
    assert response.status_code == 401


async def test_member_cannot_delete_federation(fed_repo) -> None:
    from tests.auth_support import sign_in

    record = await fed_repo.add({"name": "Test Fed"})
    token = sign_in(_MEMBER)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.delete(
            f"/federations/{record['id']}",
            cookies={"access_token": token},
        )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# AC15 — Reactivate via PUT /federations/{id} with is_active=true
# ---------------------------------------------------------------------------


async def test_admin_can_reactivate_federation(fed_repo) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    record = await fed_repo.add({"name": "Dormant Fed", "is_active": False})
    fed_id = record["id"]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(f"/federations/{fed_id}", json={"is_active": True})
    assert response.status_code == 200
    assert response.json()["is_active"] is True


# ---------------------------------------------------------------------------
# AC16 — GET /federations ordering, filtering
# ---------------------------------------------------------------------------


async def test_get_federations_returns_active_only(fed_repo) -> None:
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    await fed_repo.add({"name": "Active Fed"})
    inactive = await fed_repo.add({"name": "Inactive Fed"})
    await fed_repo.deactivate(inactive["id"])

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/federations")
    assert response.status_code == 200
    names = [r["name"] for r in response.json()]
    assert "Active Fed" in names
    assert "Inactive Fed" not in names


async def test_get_federations_pinned_first_alphabetical(fed_repo) -> None:
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    await fed_repo.add({"name": "Zeta Fed"})
    await fed_repo.add({"name": "Alpha Fed"})
    await fed_repo.add({"name": "Pinned B", "is_pinned": True})
    await fed_repo.add({"name": "Pinned A", "is_pinned": True})

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/federations")
    assert response.status_code == 200
    names = [r["name"] for r in response.json()]
    # Pinned entries come first, alphabetically
    assert names[0] == "Pinned A"
    assert names[1] == "Pinned B"
    # Unpinned entries follow alphabetically
    assert names[2] == "Alpha Fed"
    assert names[3] == "Zeta Fed"


async def test_get_federations_filter_by_type(fed_repo) -> None:
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    await fed_repo.add({"name": "National A", "type": "National"})
    await fed_repo.add({"name": "Global A", "type": "Global Body"})

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/federations?type=National")
    assert response.status_code == 200
    results = response.json()
    assert all(r["type"] == "National" for r in results)
    assert any(r["name"] == "National A" for r in results)
    assert not any(r["name"] == "Global A" for r in results)


async def test_get_federations_filter_by_continental_grouping(fed_repo) -> None:
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    await fed_repo.add({"name": "Euro Fed", "continental_grouping": "Europe"})
    await fed_repo.add({"name": "Asia Fed", "continental_grouping": "Asia"})

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/federations?continental_grouping=Europe")
    assert response.status_code == 200
    results = response.json()
    assert all(r["continental_grouping"] == "Europe" for r in results)
    assert any(r["name"] == "Euro Fed" for r in results)
    assert not any(r["name"] == "Asia Fed" for r in results)


async def test_get_federations_search_by_name_prefix(fed_repo) -> None:
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    await fed_repo.add({"name": "British Kendo Association"})
    await fed_repo.add({"name": "All Japan Kendo Federation"})

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/federations?search=brit")
    assert response.status_code == 200
    results = response.json()
    assert len(results) == 1
    assert results[0]["name"] == "British Kendo Association"


async def test_get_federations_search_by_abbreviation_prefix(fed_repo) -> None:
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    await fed_repo.add({"name": "British Kendo Association", "abbreviation": "BKA"})
    await fed_repo.add({"name": "All Japan Kendo Federation", "abbreviation": "AJKF"})

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/federations?search=bka")
    assert response.status_code == 200
    results = response.json()
    assert len(results) == 1
    assert results[0]["abbreviation"] == "BKA"


# ---------------------------------------------------------------------------
# AC17 — GET /federations requires authenticated user (any role)
# ---------------------------------------------------------------------------


async def test_get_federations_unauthenticated_returns_401(fed_repo) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/federations")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# AC19 — Inactive federations hidden from list but record preserved
# ---------------------------------------------------------------------------


async def test_deactivated_federation_hidden_from_list_but_record_preserved(
    fed_repo,
) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    app.dependency_overrides[REQUIRE_MEMBER] = _admin_override
    record = await fed_repo.add({"name": "Will Be Deactivated"})
    fed_id = record["id"]

    # Deactivate
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        await c.delete(f"/federations/{fed_id}")

    # Not in list
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        list_resp = await c.get("/federations")
    assert list_resp.status_code == 200
    names = [r["name"] for r in list_resp.json()]
    assert "Will Be Deactivated" not in names

    # But GET by id still works (record preserved for referential integrity)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        get_resp = await c.get(f"/federations/{fed_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["is_active"] is False


# ---------------------------------------------------------------------------
# AC20 — federation_number column no longer on members table
# ---------------------------------------------------------------------------


def test_member_db_model_has_no_federation_number_column() -> None:
    """AC20: federation_number must not exist on the Member DB model."""
    from app.members.db_models import Member  # noqa: F401

    assert not hasattr(Member, "federation_number"), (
        "federation_number column must be removed from Member model (AC20)"
    )
