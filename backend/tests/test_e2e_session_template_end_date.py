"""
Playwright E2E browser tests for issue #258 — bounded session recurrence
(end_date).

One test per browser-observable acceptance criterion.

Not covered here (not observable in a browser — see TDD agent report):
  - AC3: editing a template's recurrence regenerates only the delta, preserving
    an individually-edited instance. There is no frontend UI to PATCH a
    template's recurrence (only the extend action exists, which only ever
    bumps end_date). This is already covered at the HTTP layer in
    backend/tests/test_session_template_end_date.py::
    test_update_template_delta_add_remove_preserve. Faking a browser
    interaction for it here would not exercise the real behaviour.
  - AC4: GET /sessions performs no writes / no per-template query loop. This
    is a backend/repository-call-count property with no UI signal. Covered at
    the HTTP layer in test_session_template_end_date.py::test_get_sessions_performs_no_writes.
  - AC6: the Alembic migration and its backfill. Purely a data-layer concern
    with no UI surface. Covered in
    test_session_template_end_date.py::test_migration_adds_end_date_to_session_templates
    and ::test_migration_backfills_existing_rows_to_today_plus_six_months.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import date, timedelta

from dotenv import load_dotenv
from playwright.sync_api import Page, expect

_dotenv_path = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path=_dotenv_path, override=False)
os.environ.setdefault("JWT_SECRET", "test-secret-not-for-production")

from app import config as _config  # noqa: E402
from app.auth.models import AccountClaims  # noqa: E402
from app.auth.token import encode_token  # noqa: E402
from tests.e2e_support import complete_onboarding  # noqa: E402

_config.JWT_SECRET = os.environ["JWT_SECRET"]

BASE_URL = "http://localhost:5173"
API_URL = "http://localhost:8000/api"


# ---------------------------------------------------------------------------
# Auth helpers (same pattern as test_e2e_session_detail.py / test_e2e_sessions.py)
# ---------------------------------------------------------------------------


def _make_token(role: str) -> str:
    claims = AccountClaims(
        sub=str(uuid.uuid4()),
        email=f"{role}-{uuid.uuid4().hex[:6]}@dojo.test",
        role=role,  # type: ignore[arg-type]
        is_active=True,
    )
    token = encode_token(claims)
    complete_onboarding(token)
    return token


def _set_cookie(page: Page, token: str) -> None:
    page.goto(BASE_URL)
    page.context.add_cookies(
        [{"name": "access_token", "value": token, "url": BASE_URL}]
    )


def _api_headers(token: str) -> dict:
    return {"Cookie": f"access_token={token}"}


def _get_type_id(page: Page, token: str) -> str:
    resp = page.request.get(f"{API_URL}/session-types", headers=_api_headers(token))
    assert resp.status == 200
    return resp.json()[0]["id"]


def _select_segment_type(page: Page, segment, type_name: str) -> None:
    """Tick a session type for a segment via its SessionTypeMultiSelect popover."""
    segment.get_by_role("button", name="Session types").click()
    page.get_by_role("checkbox", name=type_name, exact=True).click()
    page.keyboard.press("Escape")


def _create_template_via_api(
    page: Page,
    admin_token: str,
    *,
    title: str,
    start_date: str,
    end_date: str,
    recurrence_days: list[int],
    interval_weeks: int = 1,
) -> dict:
    type_id = _get_type_id(page, admin_token)
    payload = {
        "title": title,
        "start_date": start_date,
        "end_date": end_date,
        "recurrence_days": recurrence_days,
        "interval_weeks": interval_weeks,
        "segments": [
            {"start_time": "19:00", "duration_minutes": 60, "type_ids": [type_id]}
        ],
    }
    resp = page.request.post(
        f"{API_URL}/sessions/templates",
        headers={**_api_headers(admin_token), "Content-Type": "application/json"},
        data=json.dumps(payload),
    )
    assert resp.status == 201, f"Template create failed: {resp.status} {resp.text()}"
    return resp.json()


def _first_instance_for_template(
    page: Page, admin_token: str, template_id: str
) -> dict:
    resp = page.request.get(f"{API_URL}/sessions", headers=_api_headers(admin_token))
    assert resp.status == 200
    matches = [s for s in resp.json() if s["template_id"] == template_id]
    assert matches, "Expected at least one generated instance for the template"
    return sorted(matches, key=lambda s: s["date"])[0]


# ---------------------------------------------------------------------------
# AC1 — end_date is required and bounded (start_date < end_date <= start_date
# + 6 months); violations surface as a validation error in the create dialog.
# ---------------------------------------------------------------------------


def test_create_dialog_rejects_end_date_beyond_six_month_cap(page: Page) -> None:
    admin_token = _make_token("admin")
    type_name_resp = page.request.get(
        f"{API_URL}/session-types", headers=_api_headers(admin_token)
    )
    type_name = type_name_resp.json()[0]["name"]

    _set_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/sessions")
    page.get_by_role("button", name="Create Session").click()
    dialog = page.get_by_role("dialog", name="Create Session")
    expect(dialog).to_be_visible(timeout=10_000)

    dialog.locator("#session-title").fill("AC1 Beyond Cap Template")
    dialog.get_by_text("Recurring session").click()

    # start_date and start_date + 7 months (beyond the 6-month cap)
    dialog.get_by_label("Start date").fill("2099-01-01")
    dialog.get_by_label("End date").fill("2099-08-02")

    seg1 = dialog.locator('[aria-label="Segment 1"]')
    seg1.get_by_label("Start time").fill("19:00")
    _select_segment_type(page, seg1, type_name)

    dialog.get_by_text("Mon", exact=True).click()

    dialog.get_by_role("button", name="Create Session").click()

    expect(dialog.get_by_role("alert")).to_contain_text(
        "end_date must not be more than 6", timeout=10_000
    )
    # Dialog stays open — the template was rejected, not created.
    expect(dialog).to_be_visible()


# ---------------------------------------------------------------------------
# AC2 — creating a template with an end date generates sessions across the
# full start_date..end_date range in one pass, visible in the session list.
# ---------------------------------------------------------------------------


def test_creating_template_populates_sessions_for_full_date_range(
    page: Page,
) -> None:
    admin_token = _make_token("admin")
    type_name_resp = page.request.get(
        f"{API_URL}/session-types", headers=_api_headers(admin_token)
    )
    type_name = type_name_resp.json()[0]["name"]

    unique_title = f"AC2 Full Range {uuid.uuid4().hex[:8]}"

    _set_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/sessions")
    page.get_by_role("button", name="Create Session").click()
    dialog = page.get_by_role("dialog", name="Create Session")
    expect(dialog).to_be_visible(timeout=10_000)

    dialog.locator("#session-title").fill(unique_title)
    dialog.get_by_text("Recurring session").click()

    # 2099-03-02 and 2099-03-23 are both Mondays, three weeks apart — weekly
    # recurrence on Monday generates exactly 4 instances (day 0, 7, 14, 21).
    dialog.get_by_label("Start date").fill("2099-03-02")
    dialog.get_by_label("End date").fill("2099-03-23")

    seg1 = dialog.locator('[aria-label="Segment 1"]')
    seg1.get_by_label("Start time").fill("19:00")
    _select_segment_type(page, seg1, type_name)

    dialog.get_by_text("Mon", exact=True).click()

    dialog.get_by_role("button", name="Create Session").click()
    expect(dialog).not_to_be_visible(timeout=10_000)

    page.goto(f"{BASE_URL}/sessions")
    page.wait_for_load_state("networkidle")
    table = page.locator("[data-testid='sessions-table']")
    # "Show past sessions" toggle defaults to hiding past sessions, but these
    # are all far in the future so no toggling is required.
    expect(table.get_by_text(unique_title).first).to_be_visible(timeout=10_000)
    expect(table.get_by_text(unique_title)).to_have_count(4)


# ---------------------------------------------------------------------------
# AC5 — the extend action bumps a template's expiry date and generates the
# newly-covered sessions, visible without a page reload.
# ---------------------------------------------------------------------------


def test_extend_action_bumps_expiry_date_shown_on_template(page: Page) -> None:
    admin_token = _make_token("admin")
    start = date.today() + timedelta(days=30)
    end = start + timedelta(days=14)
    template = _create_template_via_api(
        page,
        admin_token,
        title=f"AC5 Extend {uuid.uuid4().hex[:8]}",
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        recurrence_days=[start.weekday()],
    )
    instance = _first_instance_for_template(page, admin_token, template["id"])

    _set_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/sessions/{instance['id']}")
    page.wait_for_load_state("networkidle")

    expect(page.get_by_text("Series ends")).to_be_visible(timeout=10_000)
    expect(page.get_by_text(end.isoformat())).to_be_visible()

    new_end = end + timedelta(days=14)
    page.get_by_role("button", name="Extend Series").click()
    page.get_by_label("New end date").fill(new_end.isoformat())
    page.get_by_role("button", name="Confirm Extend").click()

    # Updates in place — no navigation/reload required.
    expect(page.get_by_text(new_end.isoformat())).to_be_visible(timeout=10_000)
    expect(page.get_by_text(end.isoformat())).not_to_be_visible()


# ---------------------------------------------------------------------------
# AC7 — the create template dialog has an end-date picker, and the session
# detail view (for a templated instance) shows the series' expiry date.
# ---------------------------------------------------------------------------


def test_template_dialog_has_end_date_picker_and_expiry_is_shown(
    page: Page,
) -> None:
    admin_token = _make_token("admin")

    _set_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/sessions")
    page.get_by_role("button", name="Create Session").click()
    dialog = page.get_by_role("dialog", name="Create Session")
    expect(dialog).to_be_visible(timeout=10_000)
    dialog.get_by_text("Recurring session").click()

    expect(dialog.get_by_label("End date")).to_be_visible()
    page.keyboard.press("Escape")

    # Expiry display on a real templated session's detail view.
    end = date.today() + timedelta(days=45)
    template = _create_template_via_api(
        page,
        admin_token,
        title=f"AC7 Expiry Display {uuid.uuid4().hex[:8]}",
        start_date=date.today().isoformat(),
        end_date=end.isoformat(),
        recurrence_days=list(range(7)),
    )
    instance = _first_instance_for_template(page, admin_token, template["id"])

    page.goto(f"{BASE_URL}/sessions/{instance['id']}")
    page.wait_for_load_state("networkidle")
    expect(page.get_by_text("Series ends")).to_be_visible(timeout=10_000)
    expect(page.get_by_text(end.isoformat())).to_be_visible()
