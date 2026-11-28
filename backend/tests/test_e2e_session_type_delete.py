"""
E2E browser tests for issue #183 — delete a session type from Admin Settings.

Acceptance criteria:
  1. Deleting a session type referenced by any segment is rejected with a clear error.
  2. Deleting an unreferenced session type succeeds (it disappears from the list).
  3. After a failed (409) delete, the type still appears in the settings list.

Promoted from xfail stubs to real Playwright assertions against the live UI at
http://localhost:5173. Auth/seeding pattern mirrors test_e2e_segment_editor.py.
"""

from __future__ import annotations

import json
import uuid

from playwright.sync_api import Page, expect

from app.auth.schemas import AccountClaims
from tests.e2e_support import (
    complete_onboarding,
    login_as,
)

BASE_URL = "http://localhost:5173"
API_URL = "http://localhost:8000/api"


# ---------------------------------------------------------------------------
# Auth / seeding helpers (same pattern as test_e2e_segment_editor.py)
# ---------------------------------------------------------------------------


def _make_token(role: str) -> str:
    claims = AccountClaims(
        sub=str(uuid.uuid4()),
        email=f"{role}-{uuid.uuid4().hex[:6]}@dojo.test",
        role=role,  # type: ignore[arg-type]
    )
    return login_as(claims)


def _api_headers(token: str) -> dict:
    return {"Cookie": f"access_token={token}"}


def _set_cookie(page: Page, token: str) -> None:
    page.goto(BASE_URL)
    page.context.add_cookies(
        [{"name": "access_token", "value": token, "url": BASE_URL}]
    )


def _seed_profile(page: Page, token: str) -> None:
    complete_onboarding(token, first_name="Test", surname="Admin", dob="1990-01-01")


def _create_session_type(page: Page, admin_token: str, name: str) -> dict:
    resp = page.request.post(
        f"{API_URL}/session-types",
        headers={**_api_headers(admin_token), "Content-Type": "application/json"},
        data=json.dumps({"name": name}),
    )
    assert resp.status in (200, 201), f"Type create failed: {resp.status} {resp.text()}"
    return resp.json()


def _create_session_referencing_type(
    page: Page, admin_token: str, type_id: str, title: str
) -> dict:
    payload = {
        "title": title,
        "date": "2099-12-01",
        "location": None,
        "info": None,
        "coach_notes": None,
        "segments": [
            {
                "start_time": "19:00",
                "duration_minutes": 60,
                "type_ids": [type_id],
            }
        ],
    }
    resp = page.request.post(
        f"{API_URL}/sessions",
        headers={**_api_headers(admin_token), "Content-Type": "application/json"},
        data=json.dumps(payload),
    )
    assert resp.status == 201, f"Session create failed: {resp.status} {resp.text()}"
    return resp.json()


# ---------------------------------------------------------------------------
# AC2 — Admin can delete an unreferenced session type
# ---------------------------------------------------------------------------


def test_admin_can_delete_unreferenced_session_type(page: Page) -> None:
    """AC2: Admin can delete a session type that is not referenced by any segment."""
    admin_token = _make_token("admin")
    _seed_profile(page, admin_token)
    name = f"Unref {uuid.uuid4().hex[:6]}"
    _create_session_type(page, admin_token, name)

    _set_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/admin/settings/session-types")

    row_label = page.get_by_text(name, exact=True)
    expect(row_label).to_be_visible(timeout=10_000)

    page.get_by_role("button", name=f"Delete {name}").click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_be_visible()
    # Opens on Cancel, so Enter on open never deletes (#492).
    expect(dialog.get_by_role("button", name="Cancel")).to_be_focused()
    dialog.get_by_role("button", name="Delete", exact=True).click()

    # The type disappears from the list (its delete control is gone).
    expect(page.get_by_role("button", name=f"Delete {name}")).not_to_be_visible(
        timeout=10_000
    )


# ---------------------------------------------------------------------------
# AC1 — Deleting a referenced type shows a clear error
# ---------------------------------------------------------------------------


def test_delete_session_type_shows_error_when_referenced_by_segment(page: Page) -> None:
    """AC1: Attempting to delete a session type used by a segment shows a clear error."""
    admin_token = _make_token("admin")
    _seed_profile(page, admin_token)
    name = f"Ref {uuid.uuid4().hex[:6]}"
    created = _create_session_type(page, admin_token, name)
    _create_session_referencing_type(page, admin_token, created["id"], f"Uses {name}")

    _set_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/admin/settings/session-types")

    expect(page.get_by_text(name, exact=True)).to_be_visible(timeout=10_000)

    page.get_by_role("button", name=f"Delete {name}").click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_be_visible()
    dialog.get_by_role("button", name="Delete", exact=True).click()

    # A clear error referencing the segment is surfaced.
    expect(
        dialog.get_by_text("referenced by one or more session segments")
    ).to_be_visible(timeout=10_000)


# ---------------------------------------------------------------------------
# AC3 — The referenced type remains after a failed delete
# ---------------------------------------------------------------------------


def test_referenced_session_type_remains_after_failed_delete(page: Page) -> None:
    """AC3: After a failed delete attempt (409), the type still appears in the list."""
    admin_token = _make_token("admin")
    _seed_profile(page, admin_token)
    name = f"Keep {uuid.uuid4().hex[:6]}"
    created = _create_session_type(page, admin_token, name)
    _create_session_referencing_type(page, admin_token, created["id"], f"Uses {name}")

    _set_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/admin/settings/session-types")

    expect(page.get_by_text(name, exact=True)).to_be_visible(timeout=10_000)

    page.get_by_role("button", name=f"Delete {name}").click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_be_visible()
    dialog.get_by_role("button", name="Delete", exact=True).click()

    # Error shown, dialog can be dismissed, and the type is still listed.
    expect(
        dialog.get_by_text("referenced by one or more session segments")
    ).to_be_visible(timeout=10_000)
    dialog.get_by_role("button", name="Cancel").click()
    expect(page.get_by_text(name, exact=True)).to_be_visible()
