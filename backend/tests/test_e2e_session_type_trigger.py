"""
E2E browser test for issue #78 — session type selector trigger shows name.

The single-select SelectTrigger this test originally targeted was replaced by the
multi-select ``SessionTypeMultiSelect`` (aria-label "Session types"): an empty
trigger shows "Select session types…", selected types render as name badges, and
options are checkboxes labelled by name. The acceptance criteria still hold for
the new control:
  1. Selecting a session type shows the type name in the trigger (not the UUID)
  2. A placeholder is shown when no type is selected
  3. Dropdown list items display session type names
"""

import os
import re
import uuid

from dotenv import load_dotenv
from playwright.sync_api import Page, expect

# Load the real JWT_SECRET from .env so tokens pass server-side validation.
_dotenv_path = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path=_dotenv_path, override=False)
os.environ.setdefault("JWT_SECRET", "test-secret-not-for-production")

from app import config as _config  # noqa: E402
from app.auth.models import UserClaims  # noqa: E402
from app.auth.token import encode_token  # noqa: E402
from tests.e2e_support import complete_onboarding  # noqa: E402

_config.JWT_SECRET = os.environ["JWT_SECRET"]

BASE_URL = "http://localhost:5173"
API_URL = "http://localhost:8000/api"


# ---------------------------------------------------------------------------
# Auth helpers (mirrors test_e2e_sessions.py)
# ---------------------------------------------------------------------------


def _make_token(role: str) -> str:
    claims = UserClaims(
        sub=str(uuid.uuid4()),
        email=f"{role}-{uuid.uuid4().hex[:6]}@dojo.test",
        role=role,  # type: ignore[arg-type]
        is_active=True,
    )
    token = encode_token(claims)
    # Seed the acting user's Member profile so the RequireProfile gate does
    # not bounce every navigation to /onboarding before assertions run (#221).
    complete_onboarding(token)
    return token


def _set_cookie(page: Page, token: str) -> None:
    """Navigate to the app and set the access_token cookie."""
    page.goto(BASE_URL)
    page.context.add_cookies(
        [{"name": "access_token", "value": token, "url": BASE_URL}]
    )


def _api_headers(token: str) -> dict:
    return {"Cookie": f"access_token={token}"}


# ---------------------------------------------------------------------------
# AC1 — Trigger shows type name after selection (not a UUID)
# ---------------------------------------------------------------------------


def test_session_type_trigger_shows_name_after_selection(page: Page) -> None:
    """After selecting a session type, the SelectTrigger displays the name, not the UUID."""
    admin_token = _make_token("admin")

    # Fetch available session types from the API
    types_resp = page.request.get(
        f"{API_URL}/session-types",
        headers=_api_headers(admin_token),
    )
    assert types_resp.status == 200
    session_types = types_resp.json()
    assert len(session_types) >= 1, "Need at least one session type"
    first_type = session_types[0]
    type_name = first_type["name"]

    # Navigate to sessions page as admin
    _set_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/sessions")
    page.wait_for_load_state("networkidle")

    # Open the "New Session" dialog
    page.get_by_role("button", name="Create Session").click()
    page.wait_for_selector("[role='dialog']")

    # The multi-select trigger should show the placeholder before any selection
    trigger = page.get_by_role("button", name="Session types").first
    expect(trigger).to_be_visible()

    # Open the popover and tick the first session type
    trigger.click()
    page.get_by_role("checkbox", name=type_name, exact=True).click()

    # AC1: The trigger must now show the type name (as a badge), not the raw UUID
    expect(trigger).to_contain_text(type_name)

    # Confirm the trigger does NOT show a bare UUID pattern
    trigger_text = trigger.inner_text()
    uuid_pattern = re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
    )
    assert not uuid_pattern.match(
        trigger_text.strip()
    ), f"Trigger shows a raw UUID '{trigger_text}' instead of the type name '{type_name}'"


# ---------------------------------------------------------------------------
# AC2 — Placeholder "Select type…" shown when no type is selected
# (placeholder rendering is not broken — this should already pass)
# ---------------------------------------------------------------------------


def test_session_type_trigger_shows_placeholder_when_empty(page: Page) -> None:
    """Before any selection, the SelectTrigger shows 'Select type…' placeholder."""
    admin_token = _make_token("admin")

    _set_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/sessions")
    page.wait_for_load_state("networkidle")

    # Open the "New Session" dialog
    page.get_by_role("button", name="Create Session").click()
    page.wait_for_selector("[role='dialog']")

    # Before selection the trigger must show the placeholder text
    trigger = page.get_by_role("button", name="Session types").first
    expect(trigger).to_contain_text("Select session types…")


# ---------------------------------------------------------------------------
# AC3 — Dropdown list items show names (unaffected by the bug)
# ---------------------------------------------------------------------------


def test_session_type_dropdown_items_show_names(page: Page) -> None:
    """The options inside the open dropdown list display session type names."""
    admin_token = _make_token("admin")

    types_resp = page.request.get(
        f"{API_URL}/session-types",
        headers=_api_headers(admin_token),
    )
    assert types_resp.status == 200
    session_types = types_resp.json()
    assert len(session_types) >= 1, "Need at least one session type"
    type_name = session_types[0]["name"]

    _set_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/sessions")
    page.wait_for_load_state("networkidle")

    # Open the "New Session" dialog, then open the multi-select popover
    page.get_by_role("button", name="Create Session").click()
    page.wait_for_selector("[role='dialog']")
    page.get_by_role("button", name="Session types").first.click()

    # The option in the open list must be visible with the type name
    expect(page.get_by_role("checkbox", name=type_name, exact=True)).to_be_visible()
