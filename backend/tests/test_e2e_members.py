"""
Playwright browser tests for issue #6 — Member CRUD UI.

Admin setup: registers a user via API then promotes via direct SQLite write,
since there is no admin-creation endpoint in this slice.
"""

import sqlite3
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import Page, expect

BASE_URL = "http://localhost:5173"
API_BASE = "http://localhost:8000"
DB_PATH = Path(__file__).parents[2] / "backend" / "kendo.db"

_ADMIN_EMAIL = "e2e_admin_members@dojo.test"
_ADMIN_PASS = "Str0ng!Pass"
_MEMBER_EMAIL = "e2e_member_members@dojo.test"
_MEMBER_PASS = "Str0ng!Pass"


def _get_db_path() -> Path:
    """Find kendo.db — may be in backend/ or cwd."""
    candidates = [
        Path(__file__).parents[2] / "backend" / "kendo.db",
        Path(__file__).parents[1] / "kendo.db",
        Path("kendo.db"),
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError("kendo.db not found")


def _setup_admin(page: Page) -> None:
    """Register a user and promote to admin via DB, then log in via the browser."""
    # Register (ignore 409 if already exists)
    r = httpx.post(f"{API_BASE}/auth/register/password",
                   json={"email": _ADMIN_EMAIL, "password": _ADMIN_PASS})
    if r.status_code == 201:
        user_id = r.json()["sub"]
        db = _get_db_path()
        conn = sqlite3.connect(db)
        conn.execute("UPDATE users SET role='admin' WHERE id=?", (user_id,))
        conn.commit()
        conn.close()

    # Log in via browser to get session cookie
    page.goto(f"{BASE_URL}/login")
    page.get_by_label("Email").fill(_ADMIN_EMAIL)
    page.get_by_label("Password").fill(_ADMIN_PASS)
    page.get_by_role("button", name="Sign in").click()
    expect(page).to_have_url(f"{BASE_URL}/", timeout=8000)


def _setup_member(page: Page) -> None:
    """Register a plain member and log in via the browser."""
    httpx.post(f"{API_BASE}/auth/register/password",
               json={"email": _MEMBER_EMAIL, "password": _MEMBER_PASS})
    page.goto(f"{BASE_URL}/login")
    page.get_by_label("Email").fill(_MEMBER_EMAIL)
    page.get_by_label("Password").fill(_MEMBER_PASS)
    page.get_by_role("button", name="Sign in").click()
    expect(page).to_have_url(f"{BASE_URL}/", timeout=8000)


def _create_member_via_api(full_name: str, email: str) -> str:
    """Create a member via API using admin cookie; return member id."""
    client = httpx.Client()
    # Login as admin to get cookie
    r = client.post(f"{API_BASE}/auth/login/password",
                    json={"email": _ADMIN_EMAIL, "password": _ADMIN_PASS})
    r.raise_for_status()
    r2 = client.post(
        f"{API_BASE}/members",
        json={
            "email": email,
            "full_name": full_name,
            "dob": "1990-01-01",
            "join_date": "2024-01-01",
        },
    )
    if r2.status_code not in (201, 409):
        r2.raise_for_status()
    if r2.status_code == 201:
        return r2.json()["id"]
    # Already exists — find via email search (name may have changed from a prior run)
    r3 = client.get(f"{API_BASE}/members?search={email}")
    member_id = r3.json()[0]["id"]
    # Reset to known-good state in case a previous run modified it
    client.put(
        f"{API_BASE}/members/{member_id}",
        json={"membership_status": "active", "full_name": full_name},
    )
    return member_id


# ---------------------------------------------------------------------------
# AC3 — Admin can create a member via the UI
# ---------------------------------------------------------------------------

def test_admin_can_create_member_via_ui(page: Page) -> None:
    _setup_admin(page)
    page.goto(f"{BASE_URL}/members")
    page.get_by_role("button", name="Add member").click()
    page.get_by_label("Email").fill("new_ui_member@dojo.test")
    page.get_by_label("Full name").fill("UI Test Member")
    page.get_by_label("Date of birth").fill("1985-06-15")
    page.get_by_label("Join date").fill("2024-03-01")
    page.get_by_role("button", name="Create").click()
    expect(page.get_by_text("UI Test Member").first).to_be_visible(timeout=8000)


# ---------------------------------------------------------------------------
# AC4 — Admin sees full member profile
# ---------------------------------------------------------------------------

def test_admin_sees_full_member_profile(page: Page) -> None:
    _setup_admin(page)
    member_id = _create_member_via_api("Profile Test Member", "profile_test@dojo.test")
    page.goto(f"{BASE_URL}/members/{member_id}")
    expect(page.get_by_text("Profile Test Member")).to_be_visible(timeout=8000)
    expect(page.get_by_text("profile_test@dojo.test")).to_be_visible()


# ---------------------------------------------------------------------------
# AC4 — Member can view own profile (redirect to own detail page)
# ---------------------------------------------------------------------------

@pytest.mark.xfail(strict=False, reason="member profile link requires member_id which is not yet surfaced in session")
def test_member_can_view_own_profile_only(page: Page) -> None:
    _setup_member(page)
    # Members can see /profile but member CRUD detail requires the member's UUID
    # which is not yet surfaced in the auth session — mark as xfail until profile link is added
    pytest.fail("member id not surfaced in session yet")


# ---------------------------------------------------------------------------
# AC5 — Admin can update a member field via the UI
# ---------------------------------------------------------------------------

def test_admin_can_update_member_via_ui(page: Page) -> None:
    _setup_admin(page)
    member_id = _create_member_via_api("Update Test Member", "update_test@dojo.test")
    page.goto(f"{BASE_URL}/members/{member_id}")
    page.get_by_role("button", name="Edit").click()
    name_field = page.get_by_label("Full name")
    name_field.clear()
    name_field.fill("Updated Name")
    page.get_by_role("button", name="Save").click()
    expect(page.get_by_text("Updated Name")).to_be_visible(timeout=8000)


# ---------------------------------------------------------------------------
# AC6 — Admin can deactivate a member via UI
# ---------------------------------------------------------------------------

def test_admin_can_deactivate_member_via_ui(page: Page) -> None:
    _setup_admin(page)
    member_id = _create_member_via_api("Deactivate Test Member", "deactivate_test@dojo.test")
    page.goto(f"{BASE_URL}/members/{member_id}")
    page.get_by_role("button", name="Deactivate", exact=True).click()
    # Confirm dialog
    page.get_by_role("button", name="Confirm").click()
    expect(page.get_by_label("Membership status: inactive")).to_be_visible(timeout=8000)


# ---------------------------------------------------------------------------
# AC7 — Member list filter by status
# ---------------------------------------------------------------------------

def test_member_list_filter_by_status(page: Page) -> None:
    _setup_admin(page)
    _create_member_via_api("Filter Status Member", "filter_status@dojo.test")
    page.goto(f"{BASE_URL}/members")
    # shadcn Select — click trigger then click option (not native <select>)
    page.get_by_role("combobox").click()
    page.get_by_role("option", name="Active").first.click()
    expect(page.get_by_text("Filter Status Member").first).to_be_visible(timeout=8000)
    page.get_by_role("combobox").click()
    page.get_by_role("option", name="Inactive").first.click()
    expect(page.get_by_text("Filter Status Member").first).not_to_be_visible(timeout=5000)


# ---------------------------------------------------------------------------
# AC7 — Member list search
# ---------------------------------------------------------------------------

def test_member_list_search_by_name_or_email(page: Page) -> None:
    _setup_admin(page)
    _create_member_via_api("Searchable Member", "searchable@dojo.test")
    page.goto(f"{BASE_URL}/members")
    page.get_by_placeholder("Search").fill("Searchable")
    expect(page.get_by_text("Searchable Member").first).to_be_visible(timeout=8000)
    page.get_by_placeholder("Search").clear()
    page.get_by_placeholder("Search").fill("searchable@dojo.test")
    expect(page.get_by_text("Searchable Member").first).to_be_visible(timeout=5000)


# ---------------------------------------------------------------------------
# AC8 — Mobile viewport renders member list
# ---------------------------------------------------------------------------

def test_member_list_renders_on_mobile(page: Page) -> None:
    page.set_viewport_size({"width": 375, "height": 812})
    _setup_admin(page)
    _create_member_via_api("Mobile Test Member", "mobile_test@dojo.test")
    page.goto(f"{BASE_URL}/members")
    # On mobile the card renders as role="button" with the member name in the label.
    expect(page.get_by_role("button", name="View Mobile Test Member")).to_be_visible(timeout=8000)


# ---------------------------------------------------------------------------
# AC8 — Desktop viewport renders member detail
# ---------------------------------------------------------------------------

def test_member_detail_renders_on_desktop(page: Page) -> None:
    page.set_viewport_size({"width": 1280, "height": 800})
    _setup_admin(page)
    member_id = _create_member_via_api("Desktop Test Member", "desktop_test@dojo.test")
    page.goto(f"{BASE_URL}/members/{member_id}")
    expect(page.get_by_text("Desktop Test Member")).to_be_visible(timeout=8000)
