"""
Tests for issue #178 — recurring templates carry segments and instance
generation deep-copies them (parent PRD #172).

The segment data model and the generation pipeline already exist (built across
#174–#177). This suite locks in the #178 acceptance criteria as observable
behaviour:

  1. A multi-segment template generates instances whose segments are a
     faithful copy (same start_time, duration, coach_notes, ordered type_ids).
  2. Editing a generated instance's segments does not mutate the template
     (nor sibling instances).
  3. Recurrence settings live at the template level only — generated instances
     carry no recurrence fields.
  4. generate_instances deep-copies segments: mutating a generated instance's
     segment in place never reaches back into the template.

NO real DB tables are touched: the shared in-memory fakes stand in. The unit test
exercises the pure service function; the endpoint tests exercise the route
layer with stub repositories.
"""

from __future__ import annotations

import uuid
from datetime import date
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
from app.sessions.service import generate_instances
from tests.fake_repositories import (
    InMemorySessionInstanceRepository,
    InMemorySessionTemplateRepository,
    InMemorySessionTypeRepository,
)

# ---------------------------------------------------------------------------
# Helpers / claims
# ---------------------------------------------------------------------------

_ADMIN = AccountClaims(sub="admin-uuid", email="admin@dojo.test", role="admin")
_MEMBER = AccountClaims(sub="member-uuid", email="member@dojo.test", role="member")


def _admin_override() -> AccountClaims:
    return _ADMIN


def _member_override() -> AccountClaims:
    return _MEMBER


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _wire_overrides() -> Any:
    type_repo = InMemorySessionTypeRepository([{"name": "Kihon"}, {"name": "Jigeiko"}])
    template_repo = InMemorySessionTemplateRepository()
    instance_repo = InMemorySessionInstanceRepository()
    app.dependency_overrides[get_session_type_repo] = lambda: type_repo
    app.dependency_overrides[get_session_template_repo] = lambda: template_repo
    app.dependency_overrides[get_session_instance_repo] = lambda: instance_repo
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override
    yield {"type": type_repo, "template": template_repo, "instance": instance_repo}
    app.dependency_overrides.clear()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test/api")


async def _type_ids(repo: InMemorySessionTypeRepository) -> list[str]:
    return [r["id"] for r in await repo.list()]


# ---------------------------------------------------------------------------
# AC4 — generate_instances deep-copies segments (pure unit test)
# ---------------------------------------------------------------------------


def test_generate_instances_deep_copies_segments() -> None:
    """Mutating a generated instance's segment in place must NOT reach back
    into the template's segment data. Guards against a shallow copy in
    generate_instances."""
    type_a, type_b = str(uuid.uuid4()), str(uuid.uuid4())
    template = {
        "id": str(uuid.uuid4()),
        "title": "Tuesday Keiko",
        "start_date": "2025-03-04",  # Tuesday
        "recurrence_days": [1],
        "interval_weeks": 1,
        "segments": [
            {
                "start_time": "19:00",
                "duration_minutes": 60,
                "type_ids": [type_a],
            },
            {
                "start_time": "20:00",
                "duration_minutes": 30,
                "type_ids": [type_b],
            },
        ],
    }

    instances = generate_instances(template, date(2025, 3, 18))
    assert len(instances) >= 2, "expected multiple weekly instances"

    # Mutate the first instance's segment data in place.
    instances[0]["segments"][0]["start_time"] = "06:00"
    instances[0]["segments"][0]["type_ids"].append("injected")
    instances[0]["segments"].append(
        {"start_time": "21:00", "duration_minutes": 15, "type_ids": ["extra"]}
    )

    # Template is untouched.
    assert template["segments"][0]["start_time"] == "19:00"
    assert template["segments"][0]["type_ids"] == [type_a]
    assert len(template["segments"]) == 2

    # Sibling instance is untouched.
    assert instances[1]["segments"][0]["start_time"] == "19:00"
    assert instances[1]["segments"][0]["type_ids"] == [type_a]
    assert len(instances[1]["segments"]) == 2


# ---------------------------------------------------------------------------
# AC1 — a multi-segment template generates instances that faithfully copy
#       every segment
# ---------------------------------------------------------------------------


async def test_multi_segment_template_generates_faithful_copy(
    _wire_overrides: dict[str, Any],
) -> None:
    type_a, type_b = await _type_ids(_wire_overrides["type"])
    # end_date is just past start_date so creation only auto-generates the
    # first occurrence (issue #258); /generate below produces the rest up to
    # its own horizon, giving this test fresh instances to inspect.
    template_payload = {
        "title": "Tuesday Keiko",
        "start_date": "2025-03-04",  # Tuesday
        "end_date": "2025-03-05",
        "recurrence_days": [1],
        "interval_weeks": 1,
        "segments": [
            {
                "start_time": "19:00",
                "duration_minutes": 60,
                "type_ids": [type_a],
            },
            {
                "start_time": "20:00",
                "duration_minutes": 30,
                "type_ids": [type_b, type_a],
            },
        ],
    }

    async with _client() as c:
        tmpl = await c.post("/sessions/templates", json=template_payload)
        assert tmpl.status_code == 201
        template_id = tmpl.json()["id"]

        gen = await c.post(
            f"/sessions/templates/{template_id}/generate",
            json={"horizon": "2025-03-18"},
        )
    assert gen.status_code == 200
    instances = gen.json()
    assert len(instances) >= 2

    for inst in instances:
        assert inst["template_id"] == template_id
        segs = inst["segments"]
        assert len(segs) == 2, "both template segments must be copied"
        assert segs[0]["start_time"] == "19:00"
        assert segs[0]["duration_minutes"] == 60
        assert segs[0]["type_ids"] == [type_a]
        assert segs[1]["start_time"] == "20:00"
        assert segs[1]["duration_minutes"] == 30
        # Segment type order is preserved faithfully.
        assert segs[1]["type_ids"] == [type_b, type_a]


# ---------------------------------------------------------------------------
# AC2 — editing a generated instance's segments does not mutate the template
#       or its sibling instances
# ---------------------------------------------------------------------------


async def test_editing_instance_leaves_template_and_siblings_unchanged(
    _wire_overrides: dict[str, Any],
) -> None:
    type_a, type_b = await _type_ids(_wire_overrides["type"])
    # end_date is just past start_date so creation only auto-generates the
    # first occurrence (issue #258); /generate below produces the rest.
    template_payload = {
        "title": "Tuesday Keiko",
        "start_date": "2025-03-04",  # Tuesday
        "end_date": "2025-03-05",
        "recurrence_days": [1],
        "interval_weeks": 1,
        "segments": [
            {"start_time": "19:00", "duration_minutes": 60, "type_ids": [type_a]},
            {"start_time": "20:00", "duration_minutes": 30, "type_ids": [type_b]},
        ],
    }

    async with _client() as c:
        template_id = (
            await c.post("/sessions/templates", json=template_payload)
        ).json()["id"]
        instances = (
            await c.post(
                f"/sessions/templates/{template_id}/generate",
                json={"horizon": "2025-03-18"},
            )
        ).json()
        assert len(instances) >= 2
        edited_id = instances[0]["id"]
        sibling_id = instances[1]["id"]

        # Rewrite the first instance to a single, different segment.
        edit = await c.put(
            f"/sessions/{edited_id}",
            json={
                "segments": [
                    {
                        "start_time": "06:30",
                        "duration_minutes": 45,
                        "type_ids": [type_b],
                    }
                ]
            },
        )
        assert edit.status_code == 200
        assert len(edit.json()["segments"]) == 1

        template_after = (await c.get(f"/sessions/templates/{template_id}")).json()
        sibling_after = (await c.get(f"/sessions/{sibling_id}")).json()

    # Template keeps its original two segments unchanged.
    tmpl_segs = template_after["segments"]
    assert len(tmpl_segs) == 2
    assert tmpl_segs[0]["start_time"] == "19:00"
    assert tmpl_segs[0]["type_ids"] == [type_a]
    assert tmpl_segs[1]["start_time"] == "20:00"
    assert tmpl_segs[1]["type_ids"] == [type_b]

    # Sibling instance is unaffected by the edit to its neighbour.
    sib_segs = sibling_after["segments"]
    assert len(sib_segs) == 2
    assert sib_segs[0]["start_time"] == "19:00"
    assert sib_segs[1]["start_time"] == "20:00"


# ---------------------------------------------------------------------------
# AC3 — recurrence settings remain at the template level; instances carry none
# ---------------------------------------------------------------------------


async def test_recurrence_stays_at_template_level(
    _wire_overrides: dict[str, Any],
) -> None:
    (type_a, _type_b) = await _type_ids(_wire_overrides["type"])
    # end_date is just past start_date so creation only auto-generates the
    # first occurrence (issue #258); /generate below produces the rest.
    template_payload = {
        "title": "Tuesday Keiko",
        "start_date": "2025-03-04",
        "end_date": "2025-03-05",
        "recurrence_days": [1],
        "interval_weeks": 2,
        "segments": [
            {"start_time": "19:00", "duration_minutes": 90, "type_ids": [type_a]}
        ],
    }

    async with _client() as c:
        tmpl = (await c.post("/sessions/templates", json=template_payload)).json()
        instances = (
            await c.post(
                f"/sessions/templates/{tmpl['id']}/generate",
                json={"horizon": "2025-04-30"},
            )
        ).json()

    # Recurrence config is exposed on the template.
    assert tmpl["recurrence_days"] == [1]
    assert tmpl["interval_weeks"] == 2

    # No recurrence config leaks onto the instance or its segments.
    assert len(instances) >= 1
    inst = instances[0]
    for field in ("recurrence", "recurrence_days", "interval_weeks", "day_of_week"):
        assert field not in inst, f"instance must not carry recurrence field {field!r}"
    for seg in inst["segments"]:
        for field in ("recurrence", "recurrence_days", "interval_weeks"):
            assert field not in seg, (
                f"segment must not carry recurrence field {field!r}"
            )
