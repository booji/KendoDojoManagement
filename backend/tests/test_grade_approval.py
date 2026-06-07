"""
Unit tests for issue #146 — Admin approve/reject pending grade submissions.

Uses StubRepository pattern — NO real DB. Dependencies are overridden via
app.dependency_overrides to inject in-memory stubs.

Acceptance criteria exercised here:
  1. POST /members/{id}/grades/{entry_id}/approve → pending entry becomes confirmed,
     assigned_by set from auth token
  2. Approve non-existent entry → 404; approve already-confirmed entry → 409
  3. DELETE /members/{id}/grades/{entry_id} → 204 (pending entry removed)
  4. Delete confirmed entry → 409
  5. Non-admin caller → 403 for both endpoints
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.guards import REQUIRE_ADMIN, REQUIRE_MEMBER
from app.auth.models import UserClaims
from app.grades.dependencies import get_grade_repo
from app.main import app
from app.members.dependencies import get_member_repo

# ---------------------------------------------------------------------------
# Auth claim helpers
# ---------------------------------------------------------------------------

_ADMIN = UserClaims(
    sub="admin-uuid", email="admin@dojo.test", role="admin", is_active=True
)
_MEMBER_A = UserClaims(
    sub="member-a-uuid", email="member-a@dojo.test", role="member", is_active=True
)

_MEMBER_A_ID = "00000000-0000-0000-0000-000000000001"

_PENDING_ENTRY_ID = "aaaaaaaa-0000-0000-0000-000000000001"
_CONFIRMED_ENTRY_ID = "bbbbbbbb-0000-0000-0000-000000000002"


def _admin_override():
    return _ADMIN


def _member_a_override():
    return _MEMBER_A


# ---------------------------------------------------------------------------
# Stub repositories
# ---------------------------------------------------------------------------

_MEMBER_A_RECORD: dict[str, Any] = {
    "id": _MEMBER_A_ID,
    "email": "member-a@dojo.test",
    "full_name": "Member A",
    "user_id": _MEMBER_A.sub,
    "membership_status": "active",
}


class StubMemberRepo:
    """Minimal in-memory member repository for grade approval tests."""

    def __init__(self, members: list[dict[str, Any]] | None = None) -> None:
        self._store: dict[str, dict[str, Any]] = {}
        for m in members or [_MEMBER_A_RECORD]:
            self._store[m["id"]] = dict(m)

    async def get(self, member_id: str) -> dict[str, Any] | None:
        return self._store.get(member_id)

    async def get_by_email(self, email: str) -> dict[str, Any] | None:
        for item in self._store.values():
            if item["email"] == email:
                return item
        return None

    async def add(self, data: dict[str, Any]) -> dict[str, Any]:
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
        self, status: str | None = None, search: str | None = None
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


class StubGradeRepo:
    """In-memory grade repository supporting approve_entry and delete_entry.

    Seeded with one pending entry and one confirmed entry for member A.
    """

    def __init__(self) -> None:
        self._history: list[dict[str, Any]] = [
            {
                "id": _PENDING_ENTRY_ID,
                "member_id": _MEMBER_A_ID,
                "grade": "SHODAN",
                "display_name": "Shodan (1-dan)",
                "assigned_by": None,
                "promoted_at": "2025-01-01T10:00:00+00:00",
                "status": "pending",
            },
            {
                "id": _CONFIRMED_ENTRY_ID,
                "member_id": _MEMBER_A_ID,
                "grade": "ROKKYUU",
                "display_name": "Rokkyū (6-kyu)",
                "assigned_by": "admin-uuid",
                "promoted_at": "2024-01-01T10:00:00+00:00",
                "status": "confirmed",
            },
        ]

    async def get_current_grade(self, member_id: str) -> str | None:
        member_entries = [e for e in self._history if e["member_id"] == member_id]
        if not member_entries:
            return None
        return member_entries[-1]["grade"]

    async def add_promotion(
        self,
        member_id: str,
        grade: str,
        display_name: str,
        assigned_by: str | None,
        promoted_at: str,
        status: str = "confirmed",
    ) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "member_id": member_id,
            "grade": grade,
            "display_name": display_name,
            "assigned_by": assigned_by,
            "promoted_at": promoted_at,
            "status": status,
        }
        self._history.append(entry)
        return entry

    async def get_history(self, member_id: str) -> list[dict[str, Any]]:
        return [e for e in self._history if e["member_id"] == member_id]

    async def approve_entry(
        self, member_id: str, entry_id: str, approved_by: str
    ) -> dict[str, Any]:
        """Transition a pending entry to confirmed, setting assigned_by.

        Raises KeyError if entry not found.
        Raises ValueError if entry is not pending.
        """
        # NOTE: These methods do not yet exist on AbstractGradeRepository —
        # this stub implements the expected interface for the RED phase.
        for entry in self._history:
            if entry["id"] == entry_id and entry["member_id"] == member_id:
                if entry["status"] != "pending":
                    raise ValueError("Entry is not pending")
                entry["status"] = "confirmed"
                entry["assigned_by"] = approved_by
                return entry
        raise KeyError(f"Entry {entry_id} not found")

    async def delete_entry(self, member_id: str, entry_id: str) -> None:
        """Remove a pending entry.

        Raises KeyError if entry not found.
        Raises ValueError if entry is not pending (confirmed entries cannot be deleted).
        """
        for i, entry in enumerate(self._history):
            if entry["id"] == entry_id and entry["member_id"] == member_id:
                if entry["status"] != "pending":
                    raise ValueError("Only pending entries may be deleted")
                self._history.pop(i)
                return
        raise KeyError(f"Entry {entry_id} not found")


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


@pytest.fixture()
def grade_repo() -> StubGradeRepo:
    repo = StubGradeRepo()
    app.dependency_overrides[get_grade_repo] = lambda: repo
    return repo


# ---------------------------------------------------------------------------
# AC1 — POST approve transitions pending → confirmed, sets assigned_by
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_approve_pending_entry_returns_200_and_confirmed_status(
    member_repo, grade_repo
) -> None:
    """AC1: POST approve on a pending entry → 200, status==confirmed."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    member_id = _MEMBER_A_ID
    entry_id = _PENDING_ENTRY_ID

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(f"/members/{member_id}/grades/{entry_id}/approve")

    assert (
        response.status_code == 200
    ), f"Expected 200 OK, got {response.status_code}: {response.text}"
    body = response.json()
    assert (
        body["status"] == "confirmed"
    ), f"Entry status must be 'confirmed' after approval; got {body.get('status')!r}"


@pytest.mark.anyio
async def test_approve_sets_assigned_by_from_auth_token(
    member_repo, grade_repo
) -> None:
    """AC1: approved entry's assigned_by must equal the admin's sub from the token."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    member_id = _MEMBER_A_ID
    entry_id = _PENDING_ENTRY_ID

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(f"/members/{member_id}/grades/{entry_id}/approve")

    assert (
        response.status_code == 200
    ), f"Expected 200 OK, got {response.status_code}: {response.text}"
    body = response.json()
    assert (
        body.get("assigned_by") == _ADMIN.sub
    ), f"assigned_by must be set to the approving admin's sub; got {body.get('assigned_by')!r}"


# ---------------------------------------------------------------------------
# AC2 — approve 404 / 409
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_approve_nonexistent_entry_returns_404(member_repo, grade_repo) -> None:
    """AC2: Approving an entry that doesn't exist → 404."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    member_id = _MEMBER_A_ID
    nonexistent_id = "99999999-0000-0000-0000-000000000000"

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(f"/members/{member_id}/grades/{nonexistent_id}/approve")

    assert (
        response.status_code == 404
    ), f"Expected 404 Not Found, got {response.status_code}: {response.text}"


@pytest.mark.anyio
async def test_approve_already_confirmed_entry_returns_409(
    member_repo, grade_repo
) -> None:
    """AC2: Approving an entry that is already confirmed → 409."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    member_id = _MEMBER_A_ID
    entry_id = _CONFIRMED_ENTRY_ID

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(f"/members/{member_id}/grades/{entry_id}/approve")

    assert (
        response.status_code == 409
    ), f"Expected 409 Conflict for already-confirmed entry, got {response.status_code}: {response.text}"


# ---------------------------------------------------------------------------
# AC3 — DELETE pending entry → 204
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_delete_pending_entry_returns_204(member_repo, grade_repo) -> None:
    """AC3: DELETE on a pending entry → 204 No Content."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    member_id = _MEMBER_A_ID
    entry_id = _PENDING_ENTRY_ID

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.delete(f"/members/{member_id}/grades/{entry_id}")

    assert (
        response.status_code == 204
    ), f"Expected 204 No Content, got {response.status_code}: {response.text}"


@pytest.mark.anyio
async def test_delete_pending_entry_removes_it_from_history(
    member_repo, grade_repo
) -> None:
    """AC3: After DELETE, the entry no longer appears in grade history."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    app.dependency_overrides[REQUIRE_MEMBER] = _admin_override
    member_id = _MEMBER_A_ID
    entry_id = _PENDING_ENTRY_ID

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        delete_resp = await c.delete(f"/members/{member_id}/grades/{entry_id}")
        assert delete_resp.status_code == 204

        history_resp = await c.get(f"/members/{member_id}/grades")

    assert history_resp.status_code == 200
    ids = [e["id"] for e in history_resp.json()]
    assert entry_id not in ids, "Deleted entry must not appear in grade history"


# ---------------------------------------------------------------------------
# AC4 — DELETE confirmed entry → 409
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_delete_confirmed_entry_returns_409(member_repo, grade_repo) -> None:
    """AC4: Attempting to delete a confirmed entry → 409 Conflict."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    member_id = _MEMBER_A_ID
    entry_id = _CONFIRMED_ENTRY_ID

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.delete(f"/members/{member_id}/grades/{entry_id}")

    assert (
        response.status_code == 409
    ), f"Expected 409 Conflict when deleting confirmed entry, got {response.status_code}: {response.text}"


# ---------------------------------------------------------------------------
# AC5 — Non-admin callers → 403
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_approve_non_admin_returns_403(member_repo, grade_repo) -> None:
    """AC5: Non-admin caller on POST approve → 403 Forbidden."""
    app.dependency_overrides[REQUIRE_ADMIN] = _member_a_override
    member_id = _MEMBER_A_ID
    entry_id = _PENDING_ENTRY_ID

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(f"/members/{member_id}/grades/{entry_id}/approve")

    assert (
        response.status_code == 403
    ), f"Non-admin must be rejected with 403; got {response.status_code}"


@pytest.mark.anyio
async def test_delete_non_admin_returns_403(member_repo, grade_repo) -> None:
    """AC5: Non-admin caller on DELETE → 403 Forbidden."""
    app.dependency_overrides[REQUIRE_ADMIN] = _member_a_override
    member_id = _MEMBER_A_ID
    entry_id = _PENDING_ENTRY_ID

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.delete(f"/members/{member_id}/grades/{entry_id}")

    assert (
        response.status_code == 403
    ), f"Non-admin must be rejected with 403; got {response.status_code}"
