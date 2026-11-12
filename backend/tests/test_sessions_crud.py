"""
Tests for issue #51 — Session CRUD endpoints.

Acceptance criteria:
  1. GET /sessions/{id} returns 404 for unknown IDs, 200 with correct payload otherwise
  2. coach_notes is null in GET /sessions/{id} response for member-role requests
  3. PUT /sessions/{id} updates only the addressed instance; a sibling is unchanged
  4. PATCH /sessions/templates/{id} regenerates future instances from updated template;
     past instances unchanged
  5. DELETE /sessions/templates/{id} cancels all future instances and deactivates the template
  6. All endpoints covered without a database

NO real DB: dependencies are overridden via app.dependency_overrides to inject
the shared in-memory fakes from tests/fake_repositories.py (#337).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.guards import REQUIRE_ADMIN, REQUIRE_MEMBER
from app.auth.models import AccountClaims
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

_ADMIN = AccountClaims(sub="admin-uuid", email="admin@dojo.test", role="admin")
_MEMBER = AccountClaims(sub="member-uuid", email="member@dojo.test", role="member")
_TYPE_ID = str(uuid.uuid4())


def _admin_override():
    return _ADMIN


def _member_override():
    return _MEMBER


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def type_repo() -> InMemorySessionTypeRepository:
    """Segment writes check their types exist, so the one _segment uses does."""
    repo = InMemorySessionTypeRepository([{"id": _TYPE_ID, "name": "Keiko"}])
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
        "type_ids": [_TYPE_ID],
    }


async def _seed_template(
    template_repo: InMemorySessionTemplateRepository,
) -> dict[str, Any]:
    """Add a minimal template through the repository's own interface."""
    return await template_repo.add(
        {
            "title": "Weekly Keiko",
            "start_date": "2026-01-05",  # a Monday
            "end_date": "2030-01-01",  # far enough out to cover any test date
            "segments": [_segment()],
            "recurrence": "weekly",
            "day_of_week": 0,  # Monday
            "location": "Main Hall",
        }
    )


async def _seed_instance(
    instance_repo: InMemorySessionInstanceRepository,
    *,
    template_id: str | None = None,
    instance_date: str = "2099-06-02",
    coach_notes: str | None = None,
) -> dict[str, Any]:
    """Add a minimal session instance through the repository's own interface."""
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
        transport=ASGITransport(app=app), base_url="http://test/api"
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
        transport=ASGITransport(app=app), base_url="http://test/api"
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
        transport=ASGITransport(app=app), base_url="http://test/api"
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
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(f"/sessions/{target['id']}", json=update_payload)
    assert response.status_code == 200
    body = response.json()
    assert body["location"] == "Updated Dojo"
    assert body["start_time"] == "20:00"
    assert body["duration_minutes"] == 60

    # Sibling must be unchanged — fetch it back through the repository
    sibling_after = await instance_repo.get(sibling["id"])
    assert sibling_after is not None
    assert sibling_after.get("location") != "Updated Dojo"
    assert sibling_after["segments"][0]["start_time"] == "19:00"
    assert sibling_after["segments"][0]["duration_minutes"] == 90


async def test_put_session_instance_moves_it_to_a_new_date(instance_repo) -> None:
    """Issue #429: a changed date was silently dropped by the update schema."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    target = await _seed_instance(instance_repo, instance_date="2099-06-02")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(f"/sessions/{target['id']}", json={"date": "2099-06-05"})
    assert response.status_code == 200
    assert response.json()["date"] == "2099-06-05"
    stored = await instance_repo.get(target["id"])
    assert stored is not None
    assert stored["date"] == "2099-06-05"


async def test_put_session_instance_clears_a_field_sent_as_null(
    instance_repo,
) -> None:
    """#585: an explicit null clears an optional field; a missing key leaves
    it alone."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    target = await _seed_instance(instance_repo, coach_notes="Watch the kote")
    await instance_repo.update(target["id"], {"info": "Bring a bokken"})

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(
            f"/sessions/{target['id']}",
            json={"location": None, "info": None, "coach_notes": None},
        )
    assert response.status_code == 200
    stored = await instance_repo.get(target["id"])
    assert stored is not None
    assert stored["location"] is None
    assert stored["info"] is None
    assert stored["coach_notes"] is None
    assert stored["title"] == "Weekly Keiko"


@pytest.mark.parametrize("field", ["title", "date", "segments"])
async def test_put_session_instance_refuses_null_for_a_required_field(
    instance_repo, field
) -> None:
    """#585: a field every Session must have answers null with 422."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    target = await _seed_instance(instance_repo)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(f"/sessions/{target['id']}", json={field: None})
    assert response.status_code == 422


async def test_patch_template_clears_a_field_sent_as_null(
    template_repo, instance_repo
) -> None:
    """#585: the template PATCH follows the same rule as the Session PUT."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    tmpl = await _seed_template(template_repo)
    await template_repo.update(
        tmpl["id"], {"info": "Bring a bokken", "coach_notes": "Watch the kote"}
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.patch(
            f"/sessions/templates/{tmpl['id']}",
            json={"location": None, "info": None, "coach_notes": None},
        )
        refused = await c.patch(
            f"/sessions/templates/{tmpl['id']}", json={"title": None}
        )
    assert response.status_code == 200
    stored = await template_repo.get(tmpl["id"])
    assert stored is not None
    assert stored["location"] is None
    assert stored["info"] is None
    assert stored["coach_notes"] is None
    assert stored["title"] == "Weekly Keiko"
    assert refused.status_code == 422


@pytest.mark.parametrize("bad", ["2026-02-31", "not-a-date", "20990605"])
async def test_put_session_instance_rejects_a_date_that_is_not_real(
    instance_repo, bad
) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    target = await _seed_instance(instance_repo, instance_date="2099-06-02")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.put(f"/sessions/{target['id']}", json={"date": bad})
    assert response.status_code == 422
    stored = await instance_repo.get(target["id"])
    assert stored is not None
    assert stored["date"] == "2099-06-02"


# ---------------------------------------------------------------------------
# AC4 — PATCH /sessions/templates/{id}: delta-regenerates instances (issue #258
# supersedes the old delete-all-future-and-regenerate behaviour: existing
# instances at still-covered dates — including past ones — are left
# completely untouched; only no-longer-covered dates are removed.)
# ---------------------------------------------------------------------------


async def test_patch_template_preserves_instances_at_covered_dates(
    template_repo, instance_repo
) -> None:
    """PATCH /sessions/templates/{id} must not delete+regenerate an existing
    instance whose date remains covered by the template's recurrence — the
    old delete-all-future-and-regenerate behaviour is gone (issue #258 AC3)."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    tmpl = await _seed_template(template_repo)

    # A Monday within the seeded template's start_date..end_date range.
    covered_monday = "2026-01-12"
    existing_inst = await _seed_instance(
        instance_repo,
        template_id=tmpl["id"],
        instance_date=covered_monday,
    )

    update_payload = {
        "segments": [_segment(start_time="20:00", duration_minutes=60)],
        "location": "New Location",
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.patch(
            f"/sessions/templates/{tmpl['id']}", json=update_payload
        )
    assert response.status_code == 200

    # The existing instance at a still-covered date is left untouched by id
    # and by content — PATCH no longer deletes and regenerates it.
    preserved = await instance_repo.get(existing_inst["id"])
    assert preserved is not None, "Instance at a still-covered date must not be deleted"
    assert preserved["segments"][0]["start_time"] == "19:00", (
        "delta regen must not overwrite an existing instance's content"
    )


async def test_patch_template_leaves_past_instances_untouched(
    template_repo, instance_repo
) -> None:
    """PATCH /sessions/templates/{id} must not modify or delete past instances
    whose date remains covered by the recurrence."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    tmpl = await _seed_template(template_repo)

    # A covered Monday before "today" (2026-08-08 in this test environment).
    past_date = "2026-01-19"
    past_inst = await _seed_instance(
        instance_repo,
        template_id=tmpl["id"],
        instance_date=past_date,
    )

    update_payload = {"segments": [_segment(start_time="20:00", duration_minutes=60)]}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.patch(
            f"/sessions/templates/{tmpl['id']}", json=update_payload
        )
    assert response.status_code == 200

    # Past instance must still exist and be unmodified
    past_after = await instance_repo.get(past_inst["id"])
    assert past_after is not None, "Past instance must not be deleted"
    assert past_after["segments"][0]["start_time"] == "19:00", (
        "Past instance start_time must be unchanged"
    )
    assert past_after["segments"][0]["duration_minutes"] == 90, (
        "Past instance duration must be unchanged"
    )


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
        transport=ASGITransport(app=app), base_url="http://test/api"
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
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.delete(f"/sessions/templates/{tmpl['id']}")
    assert response.status_code == 200

    # Template must now be inactive
    tmpl_after = await template_repo.get(tmpl["id"])
    assert tmpl_after is not None
    assert tmpl_after.get("is_active") is False, "Template must be deactivated"
