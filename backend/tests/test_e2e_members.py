"""
Playwright browser tests for issue #6 — Member CRUD UI.

Auth pattern: synthetic JWT tokens injected as cookies (same as test_e2e_attendance_admin.py).
No real user registration required.
"""

import os
import uuid

import pytest
import requests
from dotenv import load_dotenv
from playwright.sync_api import Page, expect

_dotenv_path = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path=_dotenv_path, override=False)
os.environ.setdefault("JWT_SECRET", "test-secret-not-for-production")

from app import config as _config  # noqa: E402
from app.auth.models import UserClaims  # noqa: E402
from app.auth.token import encode_token  # noqa: E402
from tests.e2e_support import complete_onboarding  # noqa: E402

_config.JWT_SECRET = os.environ["JWT_SECRET"]

BASE_URL = "http://localhost:5173"
API_BASE = "http://localhost:8000/api"


def _make_token(role: str, sub: str | None = None) -> str:
    claims = UserClaims(
        sub=sub or str(uuid.uuid4()),
        email=f"{role}_{uuid.uuid4().hex[:6]}@dojo.test",
        role=role,  # type: ignore[arg-type]
        is_active=True,
    )
    token = encode_token(claims)
    # Seed the acting user's Member profile so the RequireProfile gate does
    # not bounce every navigation to /onboarding before assertions run (#221).
    complete_onboarding(token)
    return token


def _cookie_dict(token: str) -> dict:
    return {"access_token": token}


def _inject_cookie(page: Page, token: str) -> None:
    page.context.add_cookies(
        [{"name": "access_token", "value": token, "url": BASE_URL}]
    )


def _create_member_via_api(
    admin_token: str, full_name: str, email: str | None = None
) -> str:
    parts = full_name.split(" ", 1)
    r = requests.post(
        f"{API_BASE}/members",
        cookies=_cookie_dict(admin_token),
        json={
            "email": email or f"member-{uuid.uuid4().hex[:8]}@dojo.test",
            "first_name": parts[0],
            "surname": parts[1] if len(parts) > 1 else parts[0],
            "dob": "1990-01-01",
            "join_date": "2024-01-01",
            "membership_status": "active",
            "is_coach": False,
            "is_first_aider": False,
        },
    )
    r.raise_for_status()
    return r.json()["id"]


# ---------------------------------------------------------------------------
# AC3 — Admin can create a member via the UI
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=False,
    reason="frontend member form still uses full_name — UI update is a separate issue from #158",
)
def test_admin_can_create_member_via_ui(page: Page) -> None:
    admin_token = _make_token("admin")
    _inject_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/members")
    page.wait_for_load_state("networkidle")
    page.get_by_role("button", name="Add member").click()
    email = f"new_ui_{uuid.uuid4().hex[:8]}@dojo.test"
    page.get_by_label("Email").fill(email)
    page.get_by_label("Full name").fill("UI Test Member")
    page.get_by_label("Date of birth").fill("1985-06-15")
    page.get_by_label("Join date").fill("2024-03-01")
    page.get_by_role("button", name="Create").click()
    expect(page.get_by_text("UI Test Member").first).to_be_visible(timeout=8000)


# ---------------------------------------------------------------------------
# AC4 — Admin sees full member profile
# ---------------------------------------------------------------------------


def test_admin_sees_full_member_profile(page: Page) -> None:
    admin_token = _make_token("admin")
    email = f"profile_{uuid.uuid4().hex[:8]}@dojo.test"
    member_id = _create_member_via_api(admin_token, "Profile Test Member", email)
    _inject_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/members/{member_id}")
    page.wait_for_load_state("networkidle")
    expect(page.get_by_role("heading", name="Profile Test Member")).to_be_visible(
        timeout=8000
    )
    expect(page.get_by_text(email)).to_be_visible()


# ---------------------------------------------------------------------------
# AC4 — Member can view own profile (redirect to own detail page)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=False,
    reason="member profile link requires member_id which is not yet surfaced in session",
)
def test_member_can_view_own_profile_only(page: Page) -> None:
    pytest.fail("member id not surfaced in session yet")


# ---------------------------------------------------------------------------
# AC5 — Admin can update a member field via the UI
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=False,
    reason="frontend member form/detail still reads full_name — UI update is a separate issue from #158",
)
def test_admin_can_update_member_via_ui(page: Page) -> None:
    admin_token = _make_token("admin")
    member_id = _create_member_via_api(admin_token, "Update Test Member")
    _inject_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/members/{member_id}")
    page.wait_for_load_state("networkidle")
    page.get_by_role("button", name="Edit").click()
    name_field = page.get_by_label("Full name")
    name_field.clear()
    name_field.fill("Updated Name")
    page.get_by_role("button", name="Save").click()
    expect(page.get_by_role("heading", name="Updated Name")).to_be_visible(timeout=8000)


# ---------------------------------------------------------------------------
# AC6 — Admin can change a member's status via the edit form (#228)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=False,
    reason="frontend member detail still reads full_name — UI update is a separate issue from #158",
)
def test_admin_can_change_member_status_via_ui(page: Page) -> None:
    admin_token = _make_token("admin")
    member_id = _create_member_via_api(admin_token, "Status Test Member")
    _inject_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/members/{member_id}")
    page.wait_for_load_state("networkidle")
    page.get_by_role("button", name="Edit").click()
    page.get_by_label("Membership status").click()
    page.get_by_role("option", name="Inactive").click()
    page.get_by_role("button", name="Save").click()
    expect(page.get_by_label("Membership status: inactive")).to_be_visible(timeout=8000)


# ---------------------------------------------------------------------------
# AC7 — Member list filter by status
# ---------------------------------------------------------------------------


def test_member_list_filter_by_status(page: Page) -> None:
    admin_token = _make_token("admin")
    suffix = uuid.uuid4().hex[:8]
    full_name = f"Filter Status {suffix}"
    _create_member_via_api(admin_token, full_name)
    _inject_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/members")
    page.wait_for_load_state("networkidle")
    page.get_by_role("combobox").click()
    page.get_by_role("option", name="Active").first.click()
    expect(page.get_by_text(full_name).first).to_be_visible(timeout=8000)
    page.get_by_role("combobox").click()
    page.get_by_role("option", name="Inactive").first.click()
    expect(page.get_by_text(full_name).first).not_to_be_visible(timeout=5000)


# ---------------------------------------------------------------------------
# AC7 — Member list search
# ---------------------------------------------------------------------------


def test_member_list_search_by_name_or_email(page: Page) -> None:
    admin_token = _make_token("admin")
    suffix = uuid.uuid4().hex[:8]
    full_name = f"Searchable {suffix}"
    email = f"searchable_{suffix}@dojo.test"
    _create_member_via_api(admin_token, full_name, email)
    _inject_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/members")
    page.wait_for_load_state("networkidle")
    page.get_by_placeholder("Search").fill(suffix)
    expect(page.get_by_text(full_name).first).to_be_visible(timeout=8000)
    page.get_by_placeholder("Search").clear()
    page.get_by_placeholder("Search").fill(email)
    expect(page.get_by_text(full_name).first).to_be_visible(timeout=5000)


# ---------------------------------------------------------------------------
# AC8 — Mobile viewport renders member list
# ---------------------------------------------------------------------------


def test_member_list_renders_on_mobile(page: Page) -> None:
    admin_token = _make_token("admin")
    suffix = uuid.uuid4().hex[:8]
    full_name = f"Mobile Test {suffix}"
    _create_member_via_api(admin_token, full_name)
    page.set_viewport_size({"width": 375, "height": 812})
    _inject_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/members")
    page.wait_for_load_state("networkidle")
    expect(page.get_by_role("button", name=f"View {full_name}")).to_be_visible(
        timeout=8000
    )


# ---------------------------------------------------------------------------
# AC8 — Desktop viewport renders member detail
# ---------------------------------------------------------------------------


def test_member_detail_renders_on_desktop(page: Page) -> None:
    admin_token = _make_token("admin")
    suffix = uuid.uuid4().hex[:8]
    full_name = f"Desktop Test {suffix}"
    member_id = _create_member_via_api(admin_token, full_name)
    page.set_viewport_size({"width": 1280, "height": 800})
    _inject_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/members/{member_id}")
    page.wait_for_load_state("networkidle")
    expect(page.get_by_role("heading", name=full_name)).to_be_visible(timeout=8000)
