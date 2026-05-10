"""
Playwright E2E tests for issue #8 — Grade promotion UI.

One test per acceptance criterion that has a frontend component.
Auth pattern: synthetic JWT tokens injected as cookies (same as test_e2e_attendance_admin.py).
"""

import os
import uuid

import requests
from dotenv import load_dotenv
from playwright.sync_api import Page, expect

_dotenv_path = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path=_dotenv_path, override=False)
os.environ.setdefault("JWT_SECRET", "test-secret-not-for-production")

from app import config as _config  # noqa: E402
from app.auth.models import UserClaims  # noqa: E402
from app.auth.token import encode_token  # noqa: E402

_config.JWT_SECRET = os.environ["JWT_SECRET"]

BASE_URL = "http://localhost:5173"
API_BASE = "http://localhost:8000"


def _make_token(role: str, sub: str | None = None) -> str:
    claims = UserClaims(
        sub=sub or str(uuid.uuid4()),
        email=f"{role}_{uuid.uuid4().hex[:6]}@dojo.test",
        role=role,  # type: ignore[arg-type]
        is_active=True,
    )
    return encode_token(claims)


def _cookie_dict(token: str) -> dict:
    return {"access_token": token}


def _inject_cookie(page: Page, token: str) -> None:
    page.context.add_cookies(
        [{"name": "access_token", "value": token, "url": BASE_URL}]
    )


def _get_session_type_id(admin_token: str) -> str:
    r = requests.get(f"{API_BASE}/session-types", cookies=_cookie_dict(admin_token))
    r.raise_for_status()
    return r.json()[0]["id"]


def _create_member_via_api(admin_token: str, full_name: str, email: str | None = None) -> str:
    r = requests.post(
        f"{API_BASE}/members",
        cookies=_cookie_dict(admin_token),
        json={
            "email": email or f"member-{uuid.uuid4().hex[:8]}@dojo.test",
            "full_name": full_name,
            "dob": "1990-01-01",
            "join_date": "2024-01-01",
            "membership_status": "active",
            "is_coach": False,
            "is_first_aider": False,
            "parental_consent_obtained": False,
        },
    )
    r.raise_for_status()
    return r.json()["id"]


# CardTitle in shadcn renders as a div[data-slot="card-title"], not a semantic
# heading element, so we locate it by text content within that slot.
_GRADE_CARD_TITLE = '[data-slot="card-title"]:has-text("Grade")'


# ---------------------------------------------------------------------------
# AC1/AC5 — Grade card shows member's current grade
# ---------------------------------------------------------------------------


def test_grade_shown_on_member_detail(page: Page) -> None:
    """AC1/AC5: Member detail page shows the member's current grade."""
    admin_token = _make_token("admin")
    member_id = _create_member_via_api(admin_token, "Grade Display Member")

    _inject_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/members/{member_id}")
    page.wait_for_load_state("networkidle")

    expect(page.locator(_GRADE_CARD_TITLE)).to_be_visible(timeout=8000)
    expect(page.get_by_text("Mukyū")).to_be_visible(timeout=8000)


# ---------------------------------------------------------------------------
# AC2 — Promote button visible for admin
# ---------------------------------------------------------------------------


def test_promote_button_visible_for_admin(page: Page) -> None:
    """AC2: Promote button is visible on the member detail page for admins."""
    admin_token = _make_token("admin")
    member_id = _create_member_via_api(admin_token, "Promote Button Member")

    _inject_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/members/{member_id}")
    page.wait_for_load_state("networkidle")

    expect(page.locator(_GRADE_CARD_TITLE)).to_be_visible(timeout=8000)
    expect(page.get_by_role("button", name="Promote member")).to_be_visible(timeout=8000)


# ---------------------------------------------------------------------------
# AC4/AC6 — Grade history toggle works
# ---------------------------------------------------------------------------


def test_grade_history_visible_to_member(page: Page) -> None:
    """AC4/AC6: Grade history toggle appears after a promotion and expands correctly."""
    admin_token = _make_token("admin")
    member_id = _create_member_via_api(admin_token, "History Toggle Member")

    _inject_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/members/{member_id}")
    page.wait_for_load_state("networkidle")

    expect(page.locator(_GRADE_CARD_TITLE)).to_be_visible(timeout=8000)
    expect(page.get_by_role("button", name="Promote member")).to_be_visible(timeout=8000)

    page.get_by_role("button", name="Promote member").click()

    toggle = page.locator("button", has_text="grade history")
    expect(toggle).to_be_visible(timeout=8000)

    toggle.click()
    expect(page.locator("#grade-history-list")).to_be_visible(timeout=5000)

    toggle.click()
    expect(page.locator("#grade-history-list")).not_to_be_visible(timeout=5000)
