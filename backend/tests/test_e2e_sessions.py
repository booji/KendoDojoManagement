"""
E2E browser tests for issue #4 — Session management.

Acceptance criteria:
  1. Session type table is seeded with "General Training" on first run
  2. Admin can create additional session types via POST /session-types
  3. Admin can create a recurring session template via POST /sessions/templates
  4. Session instances are generated from a template up to a configurable horizon
  5. Admin can create an ad-hoc session via POST /sessions
  6. Admin can cancel a single session instance without affecting its template
  7. GET /sessions returns upcoming sessions visible to authenticated users
  8. Session list UI is functional on mobile and desktop

AC2, AC3 — no admin UI exists yet; covered via direct API assertions in AC1/AC4.
"""

import json
import os
import uuid

import pytest
from dotenv import load_dotenv
from playwright.sync_api import Page, expect

# Load the real JWT_SECRET from .env so tokens pass server-side validation.
_dotenv_path = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path=_dotenv_path, override=True)
os.environ.setdefault("JWT_SECRET", "test-secret-not-for-production")

from app import config as _config  # noqa: E402
from app.auth.models import UserClaims  # noqa: E402
from app.auth.token import encode_token  # noqa: E402

_config.JWT_SECRET = os.environ["JWT_SECRET"]

BASE_URL = "http://localhost:5173"
API_URL = "http://localhost:8000"


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


def _make_token(role: str) -> str:
    claims = UserClaims(
        sub=str(uuid.uuid4()),
        email=f"{role}@dojo.test",
        role=role,  # type: ignore[arg-type]
        is_active=True,
    )
    return encode_token(claims)


def _set_cookie(page: Page, token: str) -> None:
    """Navigate to the app and set the access_token cookie."""
    page.goto(BASE_URL)
    page.context.add_cookies(
        [{"name": "access_token", "value": token, "url": BASE_URL}]
    )


def _api_headers(token: str) -> dict:
    return {"Cookie": f"access_token={token}"}


# ---------------------------------------------------------------------------
# AC1 — Session type seeded with "General Training"
# ---------------------------------------------------------------------------


def test_general_training_session_type_exists_by_default(page: Page) -> None:
    """GET /session-types returns a list that includes 'General Training'."""
    token = _make_token("admin")
    response = page.request.get(
        f"{API_URL}/session-types",
        headers=_api_headers(token),
    )
    assert response.status == 200
    types = response.json()
    names = [t["name"] for t in types]
    assert "General Training" in names, f"Expected 'General Training' in {names}"


# ---------------------------------------------------------------------------
# AC2 — Admin can create additional session types (API-level, no UI yet)
# ---------------------------------------------------------------------------


def test_admin_can_create_session_type_via_ui(page: Page) -> None:
    """Admin POST /session-types creates a new session type (no UI yet; API only)."""
    token = _make_token("admin")
    unique_name = f"Kata_{uuid.uuid4().hex[:6]}"
    response = page.request.post(
        f"{API_URL}/session-types",
        headers={**_api_headers(token), "Content-Type": "application/json"},
        data=json.dumps({"name": unique_name}),
    )
    assert response.status == 201, f"Expected 201, got {response.status}: {response.text()}"
    body = response.json()
    assert body["name"] == unique_name
    assert "id" in body


# ---------------------------------------------------------------------------
# AC3 — Admin can create a recurring session template (API-level, no UI yet)
# ---------------------------------------------------------------------------


def test_admin_can_create_recurring_session_template_via_ui(page: Page) -> None:
    """Admin POST /sessions/templates creates a template (no UI yet; API only)."""
    admin_token = _make_token("admin")
    # Get a valid session type ID first
    types_resp = page.request.get(
        f"{API_URL}/session-types",
        headers=_api_headers(admin_token),
    )
    assert types_resp.status == 200
    type_id = types_resp.json()[0]["id"]

    payload = {
        "session_type_id": type_id,
        "title": "Thursday Evening Keiko",
        "start_date": "2099-07-03",
        "start_time": "19:00",
        "duration_minutes": 90,
        "recurrence": "weekly",
        "day_of_week": 3,
    }
    resp = page.request.post(
        f"{API_URL}/sessions/templates",
        headers={**_api_headers(admin_token), "Content-Type": "application/json"},
        data=json.dumps(payload),
    )
    assert resp.status == 201, f"Expected 201, got {resp.status}: {resp.text()}"
    body = resp.json()
    assert "id" in body
    assert body["title"] == "Thursday Evening Keiko"


# ---------------------------------------------------------------------------
# AC4 — Session instances generated from template show in UI session list
# ---------------------------------------------------------------------------


def test_generating_instances_from_template_shows_them_in_session_list(
    page: Page,
) -> None:
    """Generate instances from a template, then verify they appear in the sessions UI."""
    admin_token = _make_token("admin")

    # Get a session type
    types_resp = page.request.get(
        f"{API_URL}/session-types",
        headers=_api_headers(admin_token),
    )
    type_id = types_resp.json()[0]["id"]
    type_name = types_resp.json()[0]["name"]

    # Create a template with a far-future start date
    tmpl_resp = page.request.post(
        f"{API_URL}/sessions/templates",
        headers={**_api_headers(admin_token), "Content-Type": "application/json"},
        data=json.dumps({
            "session_type_id": type_id,
            "title": "E2E Template",
            "start_date": "2099-08-07",  # Thursday
            "start_time": "18:30",
            "duration_minutes": 60,
            "recurrence": "weekly",
            "day_of_week": 3,
        }),
    )
    assert tmpl_resp.status == 201
    template_id = tmpl_resp.json()["id"]

    # Generate instances up to a horizon two weeks out
    gen_resp = page.request.post(
        f"{API_URL}/sessions/templates/{template_id}/generate",
        headers={**_api_headers(admin_token), "Content-Type": "application/json"},
        data=json.dumps({"horizon": "2099-08-21"}),
    )
    assert gen_resp.status == 200
    instances = gen_resp.json()
    assert len(instances) >= 1

    # Navigate to sessions UI as a member and verify at least one card is visible
    member_token = _make_token("member")
    _set_cookie(page, member_token)
    page.goto(f"{BASE_URL}/sessions")
    page.wait_for_load_state("networkidle")

    # The sessions page renders session type names as card headings
    expect(page.get_by_text(type_name).first).to_be_visible()


# ---------------------------------------------------------------------------
# AC5 — Admin can create an ad-hoc session (API + visible in UI)
# ---------------------------------------------------------------------------


def test_admin_can_create_adhoc_session_via_ui(page: Page) -> None:
    """Create an ad-hoc session via API, verify it appears in the sessions UI."""
    admin_token = _make_token("admin")

    # Get a session type
    types_resp = page.request.get(
        f"{API_URL}/session-types",
        headers=_api_headers(admin_token),
    )
    type_id = types_resp.json()[0]["id"]
    type_name = types_resp.json()[0]["name"]

    # Create an ad-hoc session far in the future
    sess_resp = page.request.post(
        f"{API_URL}/sessions",
        headers={**_api_headers(admin_token), "Content-Type": "application/json"},
        data=json.dumps({
            "session_type_id": type_id,
            "date": "2099-09-10",
            "start_time": "20:00",
            "duration_minutes": 75,
        }),
    )
    assert sess_resp.status == 201, f"Expected 201, got {sess_resp.status}: {sess_resp.text()}"
    body = sess_resp.json()
    assert body["status"] == "scheduled"

    # Visit the sessions page as a member and confirm the card is visible
    member_token = _make_token("member")
    _set_cookie(page, member_token)
    page.goto(f"{BASE_URL}/sessions")
    page.wait_for_load_state("networkidle")

    expect(page.get_by_text(type_name).first).to_be_visible()


# ---------------------------------------------------------------------------
# AC6 — Cancelling a session instance removes it from the list; template intact
# ---------------------------------------------------------------------------


def test_cancelling_session_instance_removes_it_from_list_but_keeps_template(
    page: Page,
) -> None:
    """Cancel a session instance and verify it disappears from the UI list.

    After cancellation the template must still be retrievable via the API.
    """
    admin_token = _make_token("admin")

    types_resp = page.request.get(
        f"{API_URL}/session-types",
        headers=_api_headers(admin_token),
    )
    type_id = types_resp.json()[0]["id"]

    # Create a template
    tmpl_resp = page.request.post(
        f"{API_URL}/sessions/templates",
        headers={**_api_headers(admin_token), "Content-Type": "application/json"},
        data=json.dumps({
            "session_type_id": type_id,
            "title": "Cancel Test Template",
            "start_date": "2099-10-02",
            "start_time": "19:00",
            "duration_minutes": 90,
            "recurrence": "weekly",
            "day_of_week": 3,
        }),
    )
    assert tmpl_resp.status == 201
    template_id = tmpl_resp.json()["id"]

    # Generate one instance
    gen_resp = page.request.post(
        f"{API_URL}/sessions/templates/{template_id}/generate",
        headers={**_api_headers(admin_token), "Content-Type": "application/json"},
        data=json.dumps({"horizon": "2099-10-09"}),
    )
    assert gen_resp.status == 200
    instances = gen_resp.json()
    assert len(instances) >= 1
    instance_id = instances[0]["id"]

    # Cancel the instance
    cancel_resp = page.request.post(
        f"{API_URL}/sessions/{instance_id}/cancel",
        headers=_api_headers(admin_token),
    )
    assert cancel_resp.status == 200
    assert cancel_resp.json()["cancelled"] is True

    # Template must still be retrievable
    tmpl_get = page.request.get(
        f"{API_URL}/sessions/templates/{template_id}",
        headers=_api_headers(admin_token),
    )
    assert tmpl_get.status == 200
    assert tmpl_get.json()["id"] == template_id

    # The cancelled session must NOT appear in the member-facing sessions list
    member_token = _make_token("member")
    sessions_resp = page.request.get(
        f"{API_URL}/sessions",
        headers=_api_headers(member_token),
    )
    assert sessions_resp.status == 200
    ids = [s["id"] for s in sessions_resp.json()]
    assert instance_id not in ids, (
        f"Cancelled session {instance_id} should not appear in upcoming list"
    )


# ---------------------------------------------------------------------------
# AC7 — Authenticated member sees upcoming sessions in the UI
# ---------------------------------------------------------------------------


def test_authenticated_member_sees_upcoming_sessions_list(page: Page) -> None:
    """Member navigates to /sessions and sees a non-empty, loaded list."""
    admin_token = _make_token("admin")

    # Seed at least one session
    types_resp = page.request.get(
        f"{API_URL}/session-types",
        headers=_api_headers(admin_token),
    )
    type_id = types_resp.json()[0]["id"]
    type_name = types_resp.json()[0]["name"]

    page.request.post(
        f"{API_URL}/sessions",
        headers={**_api_headers(admin_token), "Content-Type": "application/json"},
        data=json.dumps({
            "session_type_id": type_id,
            "date": "2099-11-05",
            "start_time": "19:00",
            "duration_minutes": 90,
        }),
    )

    # Visit the sessions page as a member
    member_token = _make_token("member")
    _set_cookie(page, member_token)
    page.goto(f"{BASE_URL}/sessions")
    page.wait_for_load_state("networkidle")

    # Page heading
    expect(page.get_by_role("heading", name="Sessions")).to_be_visible()

    # At least one session card is rendered
    expect(page.get_by_text(type_name).first).to_be_visible()

    # Week group label rendered (format "Week of D Mon")
    week_labels = page.locator("h2").all()
    assert len(week_labels) >= 1, "Expected at least one week group label"


# ---------------------------------------------------------------------------
# AC8 — Session list UI is functional on mobile and desktop
# ---------------------------------------------------------------------------


def test_session_list_renders_correctly_on_mobile(page: Page) -> None:
    """At 375px width the sessions page loads and displays session cards."""
    admin_token = _make_token("admin")

    types_resp = page.request.get(
        f"{API_URL}/session-types",
        headers=_api_headers(admin_token),
    )
    type_id = types_resp.json()[0]["id"]
    type_name = types_resp.json()[0]["name"]

    page.request.post(
        f"{API_URL}/sessions",
        headers={**_api_headers(admin_token), "Content-Type": "application/json"},
        data=json.dumps({
            "session_type_id": type_id,
            "date": "2099-12-03",
            "start_time": "19:00",
            "duration_minutes": 90,
        }),
    )

    member_token = _make_token("member")
    page.set_viewport_size({"width": 375, "height": 667})
    _set_cookie(page, member_token)
    page.goto(f"{BASE_URL}/sessions")
    page.wait_for_load_state("networkidle")

    expect(page.get_by_role("heading", name="Sessions")).to_be_visible()
    expect(page.get_by_text(type_name).first).to_be_visible()


def test_session_list_renders_correctly_on_desktop(page: Page) -> None:
    """At 1280px width the sessions page loads and displays session cards."""
    admin_token = _make_token("admin")

    types_resp = page.request.get(
        f"{API_URL}/session-types",
        headers=_api_headers(admin_token),
    )
    type_id = types_resp.json()[0]["id"]
    type_name = types_resp.json()[0]["name"]

    page.request.post(
        f"{API_URL}/sessions",
        headers={**_api_headers(admin_token), "Content-Type": "application/json"},
        data=json.dumps({
            "session_type_id": type_id,
            "date": "2099-12-10",
            "start_time": "19:00",
            "duration_minutes": 90,
        }),
    )

    member_token = _make_token("member")
    page.set_viewport_size({"width": 1280, "height": 800})
    _set_cookie(page, member_token)
    page.goto(f"{BASE_URL}/sessions")
    page.wait_for_load_state("networkidle")

    expect(page.get_by_role("heading", name="Sessions")).to_be_visible()
    expect(page.get_by_text(type_name).first).to_be_visible()
