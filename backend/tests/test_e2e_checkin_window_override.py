"""
Playwright browser tests for issue #193 — per-session check-in window
override UI (session edit form).

Promoted from red-phase xfail stubs now that the session edit form
(frontend/src/pages/SessionDetailPage.tsx EditForm) implements the two
override inputs. Auth pattern follows test_e2e_session_detail.py /
test_e2e_checkin_window.py: JWT tokens are generated directly and injected
as cookies; sessions are created via the authenticated REST API.

One test per acceptance criterion from issue #193:
  1. Session edit form exposes the two per-session override inputs.
  2. Each override input's placeholder reflects the live dojo default.
  3. Saving an override value persists it and is reflected back on reload.
  4. Blanking an override input clears it back to "use dojo default".
"""

from __future__ import annotations

import json
import os
import uuid

from dotenv import load_dotenv
from playwright.sync_api import Page, expect

_dotenv_path = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path=_dotenv_path, override=False)
os.environ.setdefault("JWT_SECRET", "test-secret-not-for-production")

from app.auth.models import AccountClaims  # noqa: E402
from tests.e2e_support import (
    complete_onboarding,  # noqa: E402
    login_as,  # noqa: E402
)

BASE_URL = "http://localhost:5173"
API_URL = "http://localhost:8000/api"


# ── helpers (mirrors test_e2e_session_detail.py / test_e2e_checkin_window.py) ──


def _make_user_with_complete_profile(role: str) -> str:
    """Create a JWT for `role` with a complete profile behind it (an Account
    and its Member, #432) so the RequireProfile gate does not redirect to
    /onboarding before the session detail / edit form can render."""
    claims = AccountClaims(
        sub=str(uuid.uuid4()),
        email=f"{role}_{uuid.uuid4().hex[:6]}@dojo.test",
        role=role,  # type: ignore[arg-type]
        is_active=True,
    )
    token = login_as(claims)
    complete_onboarding(
        token, first_name="Checkin", surname="Override", dob="1990-06-15"
    )
    return token


def _set_cookie(page: Page, token: str) -> None:
    page.goto(BASE_URL)
    page.context.add_cookies(
        [{"name": "access_token", "value": token, "url": BASE_URL}]
    )


def _api_headers(token: str) -> dict:
    return {"Cookie": f"access_token={token}"}


def _create_session(page: Page, token: str) -> str:
    types_resp = page.request.get(
        f"{API_URL}/session-types",
        headers=_api_headers(token),
    )
    type_id = types_resp.json()[0]["id"]

    resp = page.request.post(
        f"{API_URL}/sessions",
        headers={**_api_headers(token), "Content-Type": "application/json"},
        data=json.dumps(
            {
                "title": "Checkin Window Override Test Session",
                "date": "2099-12-01",
                "segments": [
                    {
                        "start_time": "19:00",
                        "duration_minutes": 90,
                        "type_ids": [type_id],
                    }
                ],
            }
        ),
    )
    assert resp.status == 201, f"Session create failed: {resp.text()}"
    return resp.json()["id"]


def _get_dojo_defaults(page: Page, token: str) -> tuple[int, int]:
    resp = page.request.get(
        f"{API_URL}/settings/dojo",
        headers=_api_headers(token),
    )
    assert resp.status == 200
    data = resp.json()
    return data["checkin_window_before_minutes"], data["checkin_window_after_minutes"]


def _open_edit_form(page: Page, session_id: str) -> None:
    page.goto(f"{BASE_URL}/sessions/{session_id}")
    page.wait_for_load_state("networkidle")
    page.get_by_role("button", name="Edit").click()
    expect(page.get_by_role("heading", name="Edit Session")).to_be_visible()


# ── AC1 — Session edit form exposes the two override inputs ────────────────


def test_session_edit_form_shows_checkin_window_override_inputs(page: Page) -> None:
    admin_token = _make_user_with_complete_profile("admin")
    session_id = _create_session(page, admin_token)

    _set_cookie(page, admin_token)
    _open_edit_form(page, session_id)

    expect(page.get_by_label("Check-in opens before (minutes)")).to_be_visible()
    expect(page.get_by_label("Check-in closes after (minutes)")).to_be_visible()


# ── AC2 — Placeholder reflects the live dojo default ────────────────────────


def test_session_edit_form_override_inputs_show_live_dojo_default_as_placeholder(
    page: Page,
) -> None:
    admin_token = _make_user_with_complete_profile("admin")
    session_id = _create_session(page, admin_token)
    before_default, after_default = _get_dojo_defaults(page, admin_token)

    _set_cookie(page, admin_token)
    _open_edit_form(page, session_id)

    before_input = page.get_by_label("Check-in opens before (minutes)")
    after_input = page.get_by_label("Check-in closes after (minutes)")

    expect(before_input).to_have_attribute("placeholder", str(before_default))
    expect(after_input).to_have_attribute("placeholder", str(after_default))
    # Neither field carries a value yet — the default is placeholder-only.
    expect(before_input).to_have_value("")
    expect(after_input).to_have_value("")


# ── AC3 — Saving an override persists it and reloads populated ─────────────


def test_session_edit_form_saving_override_persists_and_reloads(page: Page) -> None:
    admin_token = _make_user_with_complete_profile("admin")
    session_id = _create_session(page, admin_token)

    _set_cookie(page, admin_token)
    _open_edit_form(page, session_id)

    before_input = page.get_by_label("Check-in opens before (minutes)")
    after_input = page.get_by_label("Check-in closes after (minutes)")
    before_input.fill("45")
    after_input.fill("90")
    page.get_by_role("button", name="Save").click()

    # Save returns to the read-only detail view.
    expect(page.get_by_role("heading", name="Edit Session")).not_to_be_visible()

    # Reload the page from scratch and re-open the edit form.
    page.reload()
    page.wait_for_load_state("networkidle")
    page.get_by_role("button", name="Edit").click()
    expect(page.get_by_role("heading", name="Edit Session")).to_be_visible()

    expect(page.get_by_label("Check-in opens before (minutes)")).to_have_value("45")
    expect(page.get_by_label("Check-in closes after (minutes)")).to_have_value("90")


# ── AC4 — Blanking an override clears it back to the dojo default ──────────


def test_session_edit_form_blanking_override_input_clears_it(page: Page) -> None:
    admin_token = _make_user_with_complete_profile("admin")
    session_id = _create_session(page, admin_token)
    before_default, _after_default = _get_dojo_defaults(page, admin_token)

    _set_cookie(page, admin_token)
    _open_edit_form(page, session_id)

    # First, set an override.
    before_input = page.get_by_label("Check-in opens before (minutes)")
    before_input.fill("15")
    page.get_by_role("button", name="Save").click()
    expect(page.get_by_role("heading", name="Edit Session")).not_to_be_visible()

    # Re-open, confirm the override saved, then blank it.
    page.get_by_role("button", name="Edit").click()
    before_input = page.get_by_label("Check-in opens before (minutes)")
    expect(before_input).to_have_value("15")
    before_input.fill("")
    page.get_by_role("button", name="Save").click()
    expect(page.get_by_role("heading", name="Edit Session")).not_to_be_visible()

    # Reload from scratch — the override should be gone, placeholder restored.
    page.reload()
    page.wait_for_load_state("networkidle")
    page.get_by_role("button", name="Edit").click()
    before_input = page.get_by_label("Check-in opens before (minutes)")
    expect(before_input).to_have_value("")
    expect(before_input).to_have_attribute("placeholder", str(before_default))
