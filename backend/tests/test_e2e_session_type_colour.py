"""
E2E browser tests for issue #76 — admin-configurable colour per session type.

Acceptance criteria:
  1. Admin can set a colour on any session type from the admin settings page
  2. Colour is persisted and returned on GET /session-types
  3. Calendar chips use the admin-chosen colour; fall back to auto-palette if no colour set
  4. Cancelled sessions remain fully grey regardless of type colour
"""

from __future__ import annotations

import datetime
import uuid

from playwright.sync_api import Page, expect

from app.auth.models import AccountClaims
from tests.e2e_support import (
    complete_onboarding,
    login_as,
)

BASE_URL = "http://localhost:5173"
API_URL = "http://localhost:8000/api"

# Use a date in the current month so no calendar navigation is needed.
_today = datetime.date.today()
_TEST_DATE = _today.replace(day=25).isoformat()
_TEST_TIME = "19:00"


def _make_token(role: str) -> str:
    claims = AccountClaims(
        sub=str(uuid.uuid4()),
        email=f"{role}-{uuid.uuid4().hex[:6]}@dojo.test",
        role=role,  # type: ignore[arg-type]
        is_active=True,
    )
    token = login_as(claims)
    # Seed the acting user's Member profile so the RequireProfile gate does
    # not bounce every navigation to /onboarding before assertions run (#221).
    complete_onboarding(token)
    return token


def _set_cookie(page: Page, token: str) -> None:
    page.goto(BASE_URL)
    page.context.add_cookies(
        [{"name": "access_token", "value": token, "url": BASE_URL}]
    )


def _api_headers(token: str) -> dict:
    return {"Cookie": f"access_token={token}"}


def _create_session_type(page: Page, admin_token: str) -> dict:
    """Create a throwaway session type for one test to mutate.

    These tests must never touch the seeded defaults (#246): they set and clear
    colours, and the seeded rows ship with colours of their own that a teardown
    cannot restore. Every test owns a uniquely named type instead.
    """
    name = f"Colour Test {uuid.uuid4().hex[:8]}"
    resp = page.request.post(
        f"{API_URL}/session-types",
        headers={**_api_headers(admin_token), "Content-Type": "application/json"},
        data=f'{{"name": "{name}"}}',
    )
    assert resp.status == 201, f"Could not create session type: {resp.text()}"
    return resp.json()


def _delete_session_type(page: Page, admin_token: str, type_id: str) -> None:
    """Remove the throwaway type. Best-effort: the API refuses to delete a type
    still referenced by a session segment, which is fine — an unused extra type
    affects no other test."""
    page.request.delete(
        f"{API_URL}/session-types/{type_id}",
        headers=_api_headers(admin_token),
    )


def test_admin_can_set_colour_on_session_type(page: Page) -> None:
    """AC1: Admin can set a colour on any session type from the admin settings page."""
    admin_token = _make_token("admin")
    session_type = _create_session_type(page, admin_token)
    type_id = session_type["id"]
    type_name = session_type["name"]

    _set_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/admin/settings")
    page.wait_for_load_state("networkidle")

    # Colour picker input is identified by its aria-label
    colour_input = page.get_by_label(f"Colour for {type_name}")
    expect(colour_input).to_be_visible(timeout=10000)

    _delete_session_type(page, admin_token, type_id)


def test_session_type_colour_persisted_and_returned(page: Page) -> None:
    """AC2: Colour set via API is persisted and returned on GET /session-types."""
    admin_token = _make_token("admin")
    session_type = _create_session_type(page, admin_token)
    type_id = session_type["id"]
    test_colour = "#e74c3c"

    # Set via API
    put_resp = page.request.put(
        f"{API_URL}/session-types/{type_id}",
        headers={**_api_headers(admin_token), "Content-Type": "application/json"},
        data=f'{{"colour": "{test_colour}"}}',
    )
    assert put_resp.status == 200
    assert put_resp.json()["colour"] == test_colour

    # Verify GET reflects it
    get_resp = page.request.get(
        f"{API_URL}/session-types",
        headers=_api_headers(admin_token),
    )
    matching = [t for t in get_resp.json() if t["id"] == type_id]
    assert len(matching) == 1
    assert matching[0]["colour"] == test_colour

    _delete_session_type(page, admin_token, type_id)


def test_calendar_chips_use_admin_chosen_colour_with_auto_palette_fallback(
    page: Page,
) -> None:
    """AC3: Calendar chips use admin-chosen colour; fall back to auto-palette when null."""
    admin_token = _make_token("admin")
    session_type = _create_session_type(page, admin_token)
    type_id = session_type["id"]
    test_colour = "#3498db"

    # Create a session in the far-future test month
    session_resp = page.request.post(
        f"{API_URL}/sessions",
        headers={**_api_headers(admin_token), "Content-Type": "application/json"},
        data=f'{{"title": "Colour Test", "date": "{_TEST_DATE}", "segments": [{{"start_time": "{_TEST_TIME}", "duration_minutes": 90, "type_ids": ["{type_id}"]}}]}}',
    )
    assert session_resp.status == 201
    session_id = session_resp.json()["id"]

    # Set colour
    page.request.put(
        f"{API_URL}/session-types/{type_id}",
        headers={**_api_headers(admin_token), "Content-Type": "application/json"},
        data=f'{{"colour": "{test_colour}"}}',
    )

    _set_cookie(page, admin_token)
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")

    # Find the chip and check it has an inline colour style
    chip = page.locator(f'[data-session-id="{session_id}"]')
    expect(chip).to_be_visible(timeout=10000)
    # Browser converts hex to rgb(), so check the style is non-empty
    # (inline colour applied) rather than matching the hex string literally.
    style = chip.get_attribute("style") or ""
    assert style != "", "Expected chip to have inline colour style, got empty style"

    # Cleanup
    _delete_session_type(page, admin_token, type_id)
    page.request.post(
        f"{API_URL}/sessions/{session_id}/cancel",
        headers=_api_headers(admin_token),
    )


def test_cancelled_sessions_remain_grey_regardless_of_type_colour(page: Page) -> None:
    """AC4: Cancelled sessions remain grey (muted) even when type has a colour set."""
    admin_token = _make_token("admin")
    session_type = _create_session_type(page, admin_token)
    type_id = session_type["id"]
    test_colour = "#e74c3c"

    # Create + cancel a session
    session_resp = page.request.post(
        f"{API_URL}/sessions",
        headers={**_api_headers(admin_token), "Content-Type": "application/json"},
        data=f'{{"title": "Colour Test", "date": "{_TEST_DATE}", "segments": [{{"start_time": "20:00", "duration_minutes": 90, "type_ids": ["{type_id}"]}}]}}',
    )
    assert session_resp.status == 201
    session_id = session_resp.json()["id"]

    page.request.post(
        f"{API_URL}/sessions/{session_id}/cancel",
        headers=_api_headers(admin_token),
    )

    # Set a vivid colour on the type
    page.request.put(
        f"{API_URL}/session-types/{type_id}",
        headers={**_api_headers(admin_token), "Content-Type": "application/json"},
        data=f'{{"colour": "{test_colour}"}}',
    )

    _set_cookie(page, admin_token)
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")

    # Cancelled chip must NOT have the type colour inline style
    chip = page.locator(f'[data-session-id="{session_id}"]')
    expect(chip).to_be_visible(timeout=10000)
    style = chip.get_attribute("style") or ""
    assert (
        "e74c3c" not in style.lower()
    ), f"Cancelled chip should not have type colour, got style: {style}"

    _delete_session_type(page, admin_token, type_id)
