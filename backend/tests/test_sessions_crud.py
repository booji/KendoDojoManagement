"""
Tests for issue #51 — Session CRUD endpoints.

Acceptance criteria:
  1. GET /sessions/{id} returns 404 for unknown IDs, 200 with correct payload otherwise
  2. coach_notes is null in GET /sessions/{id} response for member-role requests
  3. PUT /sessions/{id} updates only the addressed instance; a sibling is unchanged
  4. PATCH /sessions/templates/{id} regenerates future instances from updated template;
     past instances unchanged
  5. DELETE /sessions/templates/{id} cancels all future instances and deactivates the template
  6. All endpoints covered by StubRepository tests

Uses StubRepository pattern — NO real DB. Dependencies are overridden via
app.dependency_overrides to inject in-memory stubs.
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
from app.sessions.dependencies import (
    get_session_instance_repo,
    get_session_template_repo,
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


def _member_override():
    return _MEMBER


# ---------------------------------------------------------------------------
# Stub repositories (with new methods needed for issue #51)
# ---------------------------------------------------------------------------


class StubSessionTemplateRepo:
    """In-memory stand-in for a SessionTemplate repository.

    Adds:
      - update(template_id, data) — update template fields, return updated dict
      - deactivate(template_id) — mark template as inactive
    """

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    async def list(self) -> list[dict[str, Any]]:
        return list(self._store.values())

    async def get(self, template_id: str) -> dict[str, Any] | None:
        return self._store.get(template_id)

    async def add(self, data: dict[str, Any]) -> dict[str, Any]:
        new_id = str(uuid.uuid4())
        record = {"id": new_id, "is_active": True, **data}
        self._store[new_id] = record
        return record

    async def update(
        self, template_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        record = self._store.get(template_id)
        if record is None:
            return None
        record.update(data)
        return record

    async def deactivate(self, template_id: str) -> dict[str, Any] | None:
        record = self._store.get(template_id)
        if record is None:
            return None
        record["is_active"] = False
        return record


class StubSessionInstanceRepo:
    """In-memory stand-in for a SessionInstance repository.

    Adds:
      - update(instance_id, data) — update instance fields, return updated dict
      - cancel_future_for_template(template_id, as_of_date) — cancel instances
        for template where date >= as_of_date
      - delete_future_for_template(template_id, as_of_date) — remove instances
        for template where date >= as_of_date (used before PATCH regeneration)
    """

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    async def list_upcoming(self, as_of: date | None = None) -> list[dict[str, Any]]:
        now = as_of or date.today()
        return [
            s
            for s in self._store.values()
            if not s.get("cancelled", False) and date.fromisoformat(s["date"]) >= now
        ]

    async def get(self, instance_id: str) -> dict[str, Any] | None:
        return self._store.get(instance_id)

    async def add(self, data: dict[str, Any]) -> dict[str, Any]:
        new_id = str(uuid.uuid4())
        record = {"id": new_id, "cancelled": False, **data}
        self._store[new_id] = record
        return record

    async def cancel(self, instance_id: str) -> dict[str, Any] | None:
        record = self._store.get(instance_id)
        if record is None:
            return None
        record["cancelled"] = True
        return record

    async def update(
        self, instance_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        record = self._store.get(instance_id)
        if record is None:
            return None
        record.update(data)
        return record

    async def cancel_future_for_template(
        self, template_id: str, as_of_date: date
    ) -> list[dict[str, Any]]:
        affected = []
        for record in self._store.values():
            if (
                record.get("template_id") == template_id
                and date.fromisoformat(record["date"]) >= as_of_date
            ):
                record["cancelled"] = True
                affected.append(record)
        return affected

    async def delete_future_for_template(
        self, template_id: str, as_of_date: date
    ) -> int:
        to_delete = [
            k
            for k, v in self._store.items()
            if v.get("template_id") == template_id
            and date.fromisoformat(v["date"]) >= as_of_date
        ]
        for k in to_delete:
            del self._store[k]
        return len(to_delete)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def template_repo() -> StubSessionTemplateRepo:
    repo = StubSessionTemplateRepo()
    app.dependency_overrides[get_session_template_repo] = lambda: repo
    return repo


@pytest.fixture()
def instance_repo() -> StubSessionInstanceRepo:
    repo = StubSessionInstanceRepo()
    app.dependency_overrides[get_session_instance_repo] = lambda: repo
    return repo


# ---------------------------------------------------------------------------
# Shared seed helpers
# ---------------------------------------------------------------------------


def _segment(
    *,
    start_time: str = "19:00",
    duration_minutes: int = 90,
) -> dict[str, Any]:
    return {
        "start_time": start_time,
        "duration_minutes": duration_minutes,
        "type_ids": [str(uuid.uuid4())],
    }


async def _seed_template(template_repo: StubSessionTemplateRepo) -> dict[str, Any]:
    """Add a minimal template directly to the stub store."""
    return await template_repo.add(
        {
            "title": "Weekly Keiko",
            "start_date": "2026-01-05",  # a Monday
            "segments": [_segment()],
            "recurrence": "weekly",
            "day_of_week": 0,  # Monday
            "location": "Main Hall",
        }
    )


async def _seed_instance(
    instance_repo: StubSessionInstanceRepo,
    *,
    template_id: str | None = None,
    instance_date: str = "2099-06-02",
    coach_notes: str | None = None,
) -> dict[str, Any]:
    """Add a minimal session instance directly to the stub store."""
    return await instance_repo.add(
        {
            "title": "Weekly Keiko",
            "date": instance_date,
            "segments": [_segment()],
            "template_id": template_id,
            "location": "Main Hall",
            "info": None,
            "coach_notes": coach_notes,
        }
    )


# ---------------------------------------------------------------------------
# AC1 — GET /sessions/{id}: 404 for unknown, 200 with payload otherwise
# ---------------------------------------------------------------------------


async def test_get_session_instance_not_found(instance_repo) -> None:
    """GET /sessions/{id} must return 404 when the ID is unknown."""
    app.dependency_overrides[REQUIRE_MEMBER] = _admin_override
    fake_id = str(uuid.uuid4())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get(f"/sessions/{fake_id}")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# AC2 — coach_notes visibility by role
# ---------------------------------------------------------------------------


async def test_get_session_instance_admin_sees_coach_notes(instance_repo) -> None:
    """Admin GET /sessions/{id} must include the real coach_notes value."""
    app.dependency_overrides[REQUIRE_MEMBER] = _admin_override
    inst = await _seed_instance(instance_repo, coach_notes="Focus on men-uchi today")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get(f"/sessions/{inst['id']}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == inst["id"]
    assert body["coach_notes"] == "Focus on men-uchi today"


async def test_get_session_instance_member_sees_null_coach_notes(
    instance_repo,
) -> None:
    """Member GET /sessions/{id} must return coach_notes as null even when stored value is non-null."""
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    inst = await _seed_instance(
        instance_repo, coach_notes="Secret notes for admin only"
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get(f"/sessions/{inst['id']}")
    assert response.status_code == 200
    body = response.json()
    assert body["coach_notes"] is None


# ---------------------------------------------------------------------------
# AC3 — PUT /sessions/{id}: updates only the addressed instance
# ---------------------------------------------------------------------------


async def test_put_session_instance_updates_target_only(
    template_repo, instance_repo
) -> None:
    """PUT /sessions/{id} must update only the target instance; a sibling from the
    same template must remain unchanged."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    tmpl = await _seed_template(template_repo)
    target = await _seed_instance(
        instance_repo,
        template_id=tmpl["id"],
        instance_date="2099-06-02",
    )
    sibling = await _seed_instance(
        instance_repo,
        template_id=tmpl["id"],
        instance_date="2099-06-09",
    )

    update_payload = {
        "location": "Updated Dojo",
        "info": "Special session",
        "segments": [_segment(start_time="20:00", duration_minutes=60)],
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.put(f"/sessions/{target['id']}", json=update_payload)
    assert response.status_code == 200
    body = response.json()
    assert body["location"] == "Updated Dojo"
    assert body["start_time"] == "20:00"
    assert body["duration_minutes"] == 60

    # Sibling must be unchanged — fetch it directly from the stub
    sibling_after = await instance_repo.get(sibling["id"])
    assert sibling_after is not None
    assert sibling_after.get("location") != "Updated Dojo"
    assert sibling_after["segments"][0]["start_time"] == "19:00"
    assert sibling_after["segments"][0]["duration_minutes"] == 90


# ---------------------------------------------------------------------------
# AC4 — PATCH /sessions/templates/{id}: regenerates future instances; past untouched
# ---------------------------------------------------------------------------


async def test_patch_template_regenerates_future_instances(
    template_repo, instance_repo
) -> None:
    """PATCH /sessions/templates/{id} must delete future instances and regenerate
    them from the updated template fields."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    tmpl = await _seed_template(template_repo)

    # Seed a future instance belonging to this template
    future_inst = await _seed_instance(
        instance_repo,
        template_id=tmpl["id"],
        instance_date="2099-06-02",
    )

    update_payload = {
        "segments": [_segment(start_time="20:00", duration_minutes=60)],
        "location": "New Location",
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.patch(
            f"/sessions/templates/{tmpl['id']}", json=update_payload
        )
    assert response.status_code == 200

    # The old future instance id should no longer exist (was deleted then regenerated)
    old_inst = await instance_repo.get(future_inst["id"])
    assert old_inst is None, "Old future instance must be replaced after PATCH"

    # New future instances should exist for this template
    all_instances = list(instance_repo._store.values())
    future_for_tmpl = [
        i
        for i in all_instances
        if i.get("template_id") == tmpl["id"]
        and date.fromisoformat(i["date"]) >= date.today()
    ]
    assert len(future_for_tmpl) >= 1, "Regenerated instances must exist after PATCH"


async def test_patch_template_leaves_past_instances_untouched(
    template_repo, instance_repo
) -> None:
    """PATCH /sessions/templates/{id} must not modify or delete past instances."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    tmpl = await _seed_template(template_repo)

    # Seed a past instance (date in the past)
    past_date = (date.today() - timedelta(days=7)).isoformat()
    past_inst = await _seed_instance(
        instance_repo,
        template_id=tmpl["id"],
        instance_date=past_date,
    )

    update_payload = {"segments": [_segment(start_time="20:00", duration_minutes=60)]}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.patch(
            f"/sessions/templates/{tmpl['id']}", json=update_payload
        )
    assert response.status_code == 200

    # Past instance must still exist and be unmodified
    past_after = await instance_repo.get(past_inst["id"])
    assert past_after is not None, "Past instance must not be deleted"
    assert (
        past_after["segments"][0]["start_time"] == "19:00"
    ), "Past instance start_time must be unchanged"
    assert (
        past_after["segments"][0]["duration_minutes"] == 90
    ), "Past instance duration must be unchanged"


# ---------------------------------------------------------------------------
# AC5 — DELETE /sessions/templates/{id}: cancels future instances, deactivates template
# ---------------------------------------------------------------------------


async def test_delete_template_cancels_future_instances(
    template_repo, instance_repo
) -> None:
    """DELETE /sessions/templates/{id} must set cancelled=True on all future instances."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    tmpl = await _seed_template(template_repo)

    future_inst = await _seed_instance(
        instance_repo,
        template_id=tmpl["id"],
        instance_date="2099-07-01",
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.delete(f"/sessions/templates/{tmpl['id']}")
    assert response.status_code == 200

    # Future instance must be cancelled
    updated = await instance_repo.get(future_inst["id"])
    assert updated is not None
    assert updated["cancelled"] is True, "Future instance must be cancelled"


async def test_delete_template_deactivates_template(
    template_repo, instance_repo
) -> None:
    """DELETE /sessions/templates/{id} must mark the template as inactive."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    tmpl = await _seed_template(template_repo)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.delete(f"/sessions/templates/{tmpl['id']}")
    assert response.status_code == 200

    # Template must now be inactive
    tmpl_after = await template_repo.get(tmpl["id"])
    assert tmpl_after is not None
    assert tmpl_after.get("is_active") is False, "Template must be deactivated"
