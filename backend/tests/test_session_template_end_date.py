"""
Failing tests for issue #258 — bounded session recurrence (end_date).

Acceptance criteria covered:
  1. SessionTemplate gains a REQUIRED end_date, validated
     start_date < end_date <= start_date + 6 months. Violations -> 422.
  2. Creating a template generates instances for the full start_date..end_date
     range in one pass.
  3. Updating a template's recurrence (PATCH) regenerates only the delta:
     newly-covered dates are added, no-longer-covered dates are removed, and
     individually-edited/cancelled future instances are NOT clobbered.
  4. GET /sessions performs no writes and no per-template query loop.
     needs_rolling_extension() / repo.latest_date_for_template() are gone.
  5. POST /sessions/templates/{id}/extend (admin-only) bumps end_date (capped
     at 6 months from *now*) and generates only newly-covered dates.
     Idempotent. 403 non-admin, 404 unknown template, 422 out-of-bounds.
  6. Alembic migration adds end_date, backfilling existing rows to
     today + 6 months (structural/static test — no DB).

Uses the StubRepository pattern — NO real DB.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.guards import REQUIRE_ADMIN, REQUIRE_MEMBER
from app.auth.models import UserClaims
from app.auth.token import encode_token
from app.main import app
from app.sessions.dependencies import (
    get_session_instance_repo,
    get_session_template_repo,
    get_session_type_repo,
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


def _admin_override() -> UserClaims:
    return _ADMIN


def _member_override() -> UserClaims:
    return _MEMBER


def _member_cookie() -> dict[str, str]:
    return {"access_token": encode_token(_MEMBER)}


# ---------------------------------------------------------------------------
# Stub repositories
# ---------------------------------------------------------------------------


class StubSessionTypeRepo:
    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}
        seeded_id = str(uuid.uuid4())
        self._store[seeded_id] = {"id": seeded_id, "name": "General Training"}

    async def list(self) -> list[dict[str, Any]]:
        return list(self._store.values())

    async def get_by_name(self, name: str) -> dict[str, Any] | None:
        return next((r for r in self._store.values() if r["name"] == name), None)

    async def get(self, type_id: str) -> dict[str, Any] | None:
        return self._store.get(type_id)


class StubSessionTemplateRepo:
    """In-memory stand-in for AbstractSessionTemplateRepository.

    Raises if `list()` is invoked when `forbid_list` is set — used to assert
    GET /sessions no longer loops over templates (AC4).
    """

    def __init__(self, forbid_list: bool = False) -> None:
        self._store: dict[str, dict[str, Any]] = {}
        self.forbid_list = forbid_list
        self.list_calls = 0

    async def add(self, data: dict[str, Any]) -> dict[str, Any]:
        new_id = str(uuid.uuid4())
        record = {"id": new_id, "is_active": True, **data}
        self._store[new_id] = record
        return record

    async def get(self, template_id: str) -> dict[str, Any] | None:
        return self._store.get(template_id)

    async def list(self) -> list[dict[str, Any]]:
        self.list_calls += 1
        if self.forbid_list:
            raise AssertionError(
                "template_repo.list() must not be called by GET /sessions (AC4)"
            )
        return list(self._store.values())

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
    """In-memory stand-in for AbstractSessionInstanceRepository.

    Tracks write-call counts so tests can assert "no writes happened" (AC4).
    `forbid_writes`, when set, makes add/update/cancel/delete raise instead of
    merely counting — used for an unambiguous no-writes-on-GET assertion.
    """

    def __init__(self, forbid_writes: bool = False) -> None:
        self._store: dict[str, dict[str, Any]] = {}
        self.forbid_writes = forbid_writes
        self.add_calls = 0
        self.update_calls = 0
        self.delete_calls = 0

    def _maybe_forbid(self, what: str) -> None:
        if self.forbid_writes:
            raise AssertionError(f"unexpected write via {what}() during GET /sessions")

    async def add(self, data: dict[str, Any]) -> dict[str, Any]:
        self.add_calls += 1
        self._maybe_forbid("add")
        new_id = str(uuid.uuid4())
        record = {
            "id": new_id,
            "cancelled": False,
            "notes": None,
            "location": None,
            "info": None,
            "coach_notes": None,
            "checkin_url": None,
            **data,
        }
        self._store[new_id] = record
        return record

    async def get(self, instance_id: str) -> dict[str, Any] | None:
        return self._store.get(instance_id)

    async def list(self) -> list[dict[str, Any]]:
        return list(self._store.values())

    async def list_upcoming(self, as_of: date | None = None) -> list[dict[str, Any]]:
        now = as_of or date.today()
        return [
            r
            for r in self._store.values()
            if not r.get("cancelled", False) and date.fromisoformat(r["date"]) >= now
        ]

    async def list_in_range(
        self, from_date: date, to_date: date
    ) -> list[dict[str, Any]]:
        return [
            r
            for r in self._store.values()
            if from_date <= date.fromisoformat(r["date"]) <= to_date
        ]

    async def latest_date_for_template(self, template_id: str) -> date | None:
        # Present here (mirroring the pre-#258 SQL repo) so
        # test_get_sessions_performs_no_writes exercises the real old
        # rolling-extension code path today. AC4 requires this method be
        # deleted from the repository *protocol*; see
        # test_latest_date_for_template_removed_from_protocol.
        return None

    async def cancel(self, instance_id: str) -> dict[str, Any] | None:
        self.update_calls += 1
        self._maybe_forbid("cancel")
        record = self._store.get(instance_id)
        if record is None:
            return None
        record["cancelled"] = True
        return record

    async def update(
        self, instance_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        self.update_calls += 1
        self._maybe_forbid("update")
        record = self._store.get(instance_id)
        if record is None:
            return None
        record.update(data)
        return record

    async def delete(self, instance_id: str) -> dict[str, Any] | None:
        self.delete_calls += 1
        self._maybe_forbid("delete")
        return self._store.pop(instance_id, None)

    async def cancel_future_for_template(
        self, template_id: str, as_of_date: date
    ) -> list[dict[str, Any]]:
        rows = [
            r
            for r in self._store.values()
            if r.get("template_id") == template_id
            and date.fromisoformat(r["date"]) >= as_of_date
            and not r.get("cancelled", False)
        ]
        for r in rows:
            r["cancelled"] = True
        return rows

    async def delete_future_for_template(
        self, template_id: str, as_of_date: date
    ) -> int:
        ids = [
            r["id"]
            for r in self._store.values()
            if r.get("template_id") == template_id
            and date.fromisoformat(r["date"]) >= as_of_date
        ]
        for i in ids:
            del self._store[i]
        return len(ids)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def type_repo() -> StubSessionTypeRepo:
    repo = StubSessionTypeRepo()
    app.dependency_overrides[get_session_type_repo] = lambda: repo
    return repo


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


@pytest.fixture(autouse=True)
def _wire_auth():
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _segment(type_id: str) -> dict[str, Any]:
    return {"start_time": "19:00", "duration_minutes": 90, "type_ids": [type_id]}


def _add_months(d: date, months: int) -> date:
    """Add calendar months to a date, clamping the day if the target month is
    shorter (mirrors the common '+6 months' cap semantics)."""
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(
        d.day,
        [
            31,
            29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
            31,
            30,
            31,
            30,
            31,
            31,
            30,
            31,
            30,
            31,
        ][month - 1],
    )
    return date(year, month, day)


# ---------------------------------------------------------------------------
# AC1 — end_date required + bounds validation on create
# ---------------------------------------------------------------------------


async def test_create_template_requires_end_date(type_repo) -> None:
    type_id = list(type_repo._store.keys())[0]
    payload = {
        "title": "No End Date",
        "start_date": "2026-01-05",
        "recurrence_days": [0],
        "segments": [_segment(type_id)],
    }
    async with _client() as c:
        response = await c.post("/sessions/templates", json=payload)
    assert response.status_code == 422, response.text


async def test_create_template_end_date_must_be_after_start_date(type_repo) -> None:
    type_id = list(type_repo._store.keys())[0]
    payload = {
        "title": "Backwards range",
        "start_date": "2026-01-05",
        "end_date": "2026-01-05",  # equal, not strictly after
        "recurrence_days": [0],
        "segments": [_segment(type_id)],
    }
    async with _client() as c:
        response = await c.post("/sessions/templates", json=payload)
    assert response.status_code == 422, response.text


async def test_create_template_end_date_beyond_six_month_cap_rejected(
    type_repo,
) -> None:
    type_id = list(type_repo._store.keys())[0]
    start = date(2026, 1, 5)
    too_far = _add_months(start, 6) + timedelta(days=1)
    payload = {
        "title": "Too far",
        "start_date": start.isoformat(),
        "end_date": too_far.isoformat(),
        "recurrence_days": [0],
        "segments": [_segment(type_id)],
    }
    async with _client() as c:
        response = await c.post("/sessions/templates", json=payload)
    assert response.status_code == 422, response.text


async def test_create_template_end_date_exactly_six_months_out_accepted(
    type_repo, template_repo, instance_repo
) -> None:
    type_id = list(type_repo._store.keys())[0]
    start = date(2026, 1, 5)
    boundary = _add_months(start, 6)
    payload = {
        "title": "Exactly boundary",
        "start_date": start.isoformat(),
        "end_date": boundary.isoformat(),
        "recurrence_days": [0],
        "segments": [_segment(type_id)],
    }
    async with _client() as c:
        response = await c.post("/sessions/templates", json=payload)
    assert response.status_code == 201, response.text
    assert response.json()["end_date"] == boundary.isoformat()


# ---------------------------------------------------------------------------
# AC2 — creating a template generates instances for the full range in one pass
# ---------------------------------------------------------------------------


async def test_create_template_generates_full_range_instances(
    type_repo, template_repo, instance_repo
) -> None:
    type_id = list(type_repo._store.keys())[0]
    start = date(2026, 1, 5)  # Monday
    end = start + timedelta(weeks=4)  # 5 Mondays: 0,1,2,3,4 weeks out
    payload = {
        "title": "Weekly Keiko",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "recurrence_days": [0],
        "interval_weeks": 1,
        "segments": [_segment(type_id)],
    }
    async with _client() as c:
        response = await c.post("/sessions/templates", json=payload)
    assert response.status_code == 201, response.text
    template_id = response.json()["id"]

    generated = [
        r for r in instance_repo._store.values() if r.get("template_id") == template_id
    ]
    generated_dates = sorted(r["date"] for r in generated)
    expected_dates = [(start + timedelta(weeks=w)).isoformat() for w in range(5)]
    assert generated_dates == expected_dates, (
        f"expected instances on {expected_dates}, got {generated_dates}"
    )


# ---------------------------------------------------------------------------
# AC3 — PATCH regenerates only the delta; edited/cancelled instances survive
# ---------------------------------------------------------------------------


async def test_update_template_delta_add_remove_preserve(
    type_repo, template_repo, instance_repo
) -> None:
    type_id = list(type_repo._store.keys())[0]
    start = date(2026, 2, 2)  # Monday
    end = start + timedelta(weeks=4)
    create_payload = {
        "title": "Weekly Keiko",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "recurrence_days": [0],  # Mondays only
        "interval_weeks": 1,
        "segments": [_segment(type_id)],
    }

    async with _client() as c:
        tmpl = (await c.post("/sessions/templates", json=create_payload)).json()
        template_id = tmpl["id"]

        mondays = sorted(
            (
                r
                for r in instance_repo._store.values()
                if r.get("template_id") == template_id
            ),
            key=lambda r: r["date"],
        )
        cancelled_target = next(
            r for r in mondays if r["date"] == (start + timedelta(weeks=2)).isoformat()
        )
        edited_target = next(
            r for r in mondays if r["date"] == (start + timedelta(weeks=3)).isoformat()
        )

        cancel_resp = await c.post(f"/sessions/{cancelled_target['id']}/cancel")
        assert cancel_resp.status_code == 200, cancel_resp.text

        edit_resp = await c.put(
            f"/sessions/{edited_target['id']}",
            json={"title": "Individually Edited Keiko"},
        )
        assert edit_resp.status_code == 200, edit_resp.text

        # Add Thursdays to the recurrence.
        patch_resp = await c.patch(
            f"/sessions/templates/{template_id}",
            json={"recurrence_days": [0, 3]},
        )
        assert patch_resp.status_code == 200, patch_resp.text

    all_after_add = [
        r for r in instance_repo._store.values() if r.get("template_id") == template_id
    ]
    thursdays_after_add = [
        r for r in all_after_add if date.fromisoformat(r["date"]).weekday() == 3
    ]
    assert len(thursdays_after_add) > 0, "newly-covered Thursdays were not added"

    mondays_after_add = {
        r["date"]: r
        for r in all_after_add
        if date.fromisoformat(r["date"]).weekday() == 0
    }
    assert mondays_after_add[cancelled_target["date"]]["cancelled"] is True, (
        "cancelled Monday instance must not be clobbered by the delta regen"
    )
    assert (
        mondays_after_add[edited_target["date"]]["title"] == "Individually Edited Keiko"
    ), "individually edited Monday instance must not be clobbered by the delta regen"
    assert len(mondays_after_add) == 5, "no duplicate Monday instances after PATCH"

    # Remove Thursdays again -> unedited Thursdays disappear, Mondays unaffected.
    async with _client() as c:
        patch_resp2 = await c.patch(
            f"/sessions/templates/{template_id}",
            json={"recurrence_days": [0]},
        )
        assert patch_resp2.status_code == 200, patch_resp2.text

    all_after_remove = [
        r for r in instance_repo._store.values() if r.get("template_id") == template_id
    ]
    thursdays_after_remove = [
        r for r in all_after_remove if date.fromisoformat(r["date"]).weekday() == 3
    ]
    assert len(thursdays_after_remove) == 0, (
        "Thursdays no longer covered by recurrence must be removed"
    )

    mondays_after_remove = {
        r["date"]: r
        for r in all_after_remove
        if date.fromisoformat(r["date"]).weekday() == 0
    }
    assert len(mondays_after_remove) == 5
    assert mondays_after_remove[cancelled_target["date"]]["cancelled"] is True
    assert (
        mondays_after_remove[edited_target["date"]]["title"]
        == "Individually Edited Keiko"
    )


# ---------------------------------------------------------------------------
# AC4 — GET /sessions performs no writes and no per-template query loop
# ---------------------------------------------------------------------------


async def test_get_sessions_performs_no_writes(type_repo) -> None:
    template_repo = StubSessionTemplateRepo(forbid_list=True)
    instance_repo = StubSessionInstanceRepo(forbid_writes=True)
    app.dependency_overrides[get_session_template_repo] = lambda: template_repo
    app.dependency_overrides[get_session_instance_repo] = lambda: instance_repo

    # Seed a template directly into the store (bypassing forbid_list, which
    # only guards .list()) so a stale rolling-extension code path — if still
    # present — has something to iterate over and attempt to write.
    template_id = str(uuid.uuid4())
    template_repo._store[template_id] = {
        "id": template_id,
        "title": "Weekly Keiko",
        "start_date": (date.today() - timedelta(days=7)).isoformat(),
        "recurrence_days": [date.today().weekday()],
        "interval_weeks": 1,
        "segments": [],
        "is_active": True,
    }

    async with _client() as c:
        response = await c.get("/sessions")

    assert response.status_code == 200, response.text
    assert instance_repo.add_calls == 0, "GET /sessions must not add instances"
    assert instance_repo.update_calls == 0, "GET /sessions must not update instances"
    assert instance_repo.delete_calls == 0, "GET /sessions must not delete instances"
    assert template_repo.list_calls == 0, (
        "GET /sessions must not loop over templates (rolling extension is gone)"
    )


def test_needs_rolling_extension_removed_from_service() -> None:
    """needs_rolling_extension must be fully removed from app.sessions.service
    (AC4) — its presence signals the rolling-extension code path still exists."""
    import app.sessions.service as service_module

    assert not hasattr(service_module, "needs_rolling_extension"), (
        "needs_rolling_extension must be removed per AC4"
    )


def test_latest_date_for_template_removed_from_protocol() -> None:
    """latest_date_for_template must be fully removed from
    AbstractSessionInstanceRepository (AC4)."""
    from app.sessions.repository import AbstractSessionInstanceRepository

    assert not hasattr(AbstractSessionInstanceRepository, "latest_date_for_template"), (
        "latest_date_for_template must be removed from the repository protocol per AC4"
    )


# ---------------------------------------------------------------------------
# AC5 — POST /sessions/templates/{id}/extend
# ---------------------------------------------------------------------------


async def _create_template_for_extend(
    c: AsyncClient, type_id: str, start: date, end: date
) -> dict[str, Any]:
    payload = {
        "title": "Extend Me",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "recurrence_days": [start.weekday()],
        "interval_weeks": 1,
        "segments": [_segment(type_id)],
    }
    resp = await c.post("/sessions/templates", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_extend_bumps_end_date_and_adds_only_new_dates(
    type_repo, template_repo, instance_repo
) -> None:
    type_id = list(type_repo._store.keys())[0]
    today = date.today()
    start = today - timedelta(days=14)
    initial_end = today + timedelta(days=14)

    async with _client() as c:
        tmpl = await _create_template_for_extend(c, type_id, start, initial_end)
        template_id = tmpl["id"]
        before_count = len(
            [
                r
                for r in instance_repo._store.values()
                if r.get("template_id") == template_id
            ]
        )

        new_end = today + timedelta(days=60)
        extend_resp = await c.post(
            f"/sessions/templates/{template_id}/extend",
            json={"end_date": new_end.isoformat()},
        )
    assert extend_resp.status_code == 200, extend_resp.text
    assert extend_resp.json()["end_date"] == new_end.isoformat()

    after = [
        r for r in instance_repo._store.values() if r.get("template_id") == template_id
    ]
    assert len(after) > before_count, "extend must generate newly-covered dates"
    assert any(date.fromisoformat(r["date"]) > initial_end for r in after), (
        "extend must generate instances beyond the old end_date"
    )


async def test_extend_idempotent(type_repo, template_repo, instance_repo) -> None:
    type_id = list(type_repo._store.keys())[0]
    today = date.today()
    start = today - timedelta(days=14)
    initial_end = today + timedelta(days=14)
    new_end = today + timedelta(days=60)

    async with _client() as c:
        tmpl = await _create_template_for_extend(c, type_id, start, initial_end)
        template_id = tmpl["id"]

        first = await c.post(
            f"/sessions/templates/{template_id}/extend",
            json={"end_date": new_end.isoformat()},
        )
        assert first.status_code == 200, first.text
        count_after_first = len(
            [
                r
                for r in instance_repo._store.values()
                if r.get("template_id") == template_id
            ]
        )

        second = await c.post(
            f"/sessions/templates/{template_id}/extend",
            json={"end_date": new_end.isoformat()},
        )
        assert second.status_code == 200, second.text
        count_after_second = len(
            [
                r
                for r in instance_repo._store.values()
                if r.get("template_id") == template_id
            ]
        )

    assert count_after_second == count_after_first, (
        "calling extend twice with the same target end_date must add nothing new"
    )


async def test_extend_rejects_beyond_six_month_cap_from_today(
    type_repo, template_repo, instance_repo
) -> None:
    type_id = list(type_repo._store.keys())[0]
    today = date.today()
    start = today - timedelta(days=14)
    initial_end = today + timedelta(days=14)
    too_far = _add_months(today, 6) + timedelta(days=1)

    async with _client() as c:
        tmpl = await _create_template_for_extend(c, type_id, start, initial_end)
        resp = await c.post(
            f"/sessions/templates/{tmpl['id']}/extend",
            json={"end_date": too_far.isoformat()},
        )
    assert resp.status_code == 422, resp.text


async def test_extend_rejects_end_date_earlier_than_current(
    type_repo, template_repo, instance_repo
) -> None:
    type_id = list(type_repo._store.keys())[0]
    today = date.today()
    start = today - timedelta(days=14)
    initial_end = today + timedelta(days=30)
    earlier = today + timedelta(days=10)

    async with _client() as c:
        tmpl = await _create_template_for_extend(c, type_id, start, initial_end)
        resp = await c.post(
            f"/sessions/templates/{tmpl['id']}/extend",
            json={"end_date": earlier.isoformat()},
        )
    assert resp.status_code == 422, resp.text


async def test_extend_unknown_template_404(
    type_repo, template_repo, instance_repo
) -> None:
    unknown_id = str(uuid.uuid4())
    async with _client() as c:
        resp = await c.post(
            f"/sessions/templates/{unknown_id}/extend",
            json={"end_date": (date.today() + timedelta(days=30)).isoformat()},
        )
    assert resp.status_code == 404, resp.text
    # Guard against a false-pass where /extend simply doesn't exist as a
    # route yet (FastAPI's generic {"detail": "Not Found"} for an unmatched
    # path also happens to be a 404). Require the endpoint's own
    # template-not-found message, matching the convention used everywhere
    # else in this router (e.g. "Template not found").
    assert "template" in resp.json().get("detail", "").lower(), (
        f"expected a template-not-found detail message, got {resp.json()!r}"
    )


async def test_extend_forbidden_for_non_admin(
    type_repo, template_repo, instance_repo
) -> None:
    type_id = list(type_repo._store.keys())[0]
    today = date.today()
    start = today - timedelta(days=14)
    initial_end = today + timedelta(days=14)

    async with _client() as c:
        tmpl = await _create_template_for_extend(c, type_id, start, initial_end)
        # The module-level _wire_auth fixture unconditionally overrides
        # REQUIRE_ADMIN so admin-only endpoints work without a cookie in the
        # other tests above. Drop that override here so this request is
        # authorized by its real cookie instead, matching how "forbidden"
        # cases are exercised elsewhere in this suite.
        del app.dependency_overrides[REQUIRE_ADMIN]
        resp = await c.post(
            f"/sessions/templates/{tmpl['id']}/extend",
            json={"end_date": (today + timedelta(days=30)).isoformat()},
            cookies=_member_cookie(),
        )
    assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# AC6 — Alembic migration adds end_date, backfilling to today + 6 months
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    import os

    if "REPO_ROOT" in os.environ:
        return Path(os.environ["REPO_ROOT"])
    current = Path(__file__).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "backend").is_dir() and (candidate / ".git").exists():
            return candidate
    # Fallback for the container layout: /app is backend/, no /repo mount.
    return Path(__file__).resolve().parents[1]


def _versions_dir() -> Path:
    root = _repo_root()
    candidate = root / "backend" / "alembic" / "versions"
    if candidate.is_dir():
        return candidate
    return root / "alembic" / "versions"


def _find_end_date_migration() -> Path | None:
    versions_dir = _versions_dir()
    if not versions_dir.is_dir():
        return None
    for path in versions_dir.glob("*.py"):
        text = path.read_text()
        if "session_templates" in text and "end_date" in text:
            return path
    return None


def test_migration_adds_end_date_to_session_templates() -> None:
    migration_path = _find_end_date_migration()
    assert migration_path is not None, (
        "expected an alembic migration under backend/alembic/versions adding "
        "'end_date' to 'session_templates' (issue #258 AC6)"
    )
    text = migration_path.read_text()
    assert "add_column" in text, "migration must add the end_date column"
    assert "session_templates" in text


def test_migration_backfills_existing_rows_to_today_plus_six_months() -> None:
    migration_path = _find_end_date_migration()
    assert migration_path is not None, (
        "expected an alembic migration under backend/alembic/versions adding "
        "'end_date' to 'session_templates' (issue #258 AC6)"
    )
    text = migration_path.read_text()
    # The backfill must be computed relative to "today" at migration time
    # (e.g. via op.execute with a date/interval expression), not a fixed
    # server_default literal — a static 6-month-out date differs per row's
    # migration run date, so a plain server_default cannot express it.
    assert "op.execute" in text, (
        "backfilling end_date to today + 6 months requires a data migration step (op.execute)"
    )
    assert "6" in text, "backfill expression must reference the 6-month offset"
