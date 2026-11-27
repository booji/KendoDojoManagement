"""
Playwright browser tests for issue #45 — Admin Personal Settings parity.

Acceptance criteria covered here (criteria 6-9):
  6. The admin nav renders both a "Settings" link (href=/settings) and an
     "Admin Settings" link (href=/admin/settings).
  7. Visiting /settings as an admin renders the Personal Details view/edit UI
     (not a blank stub).
  8. Visiting /admin/settings as an admin renders the Admin Settings page
     (any non-blank content or heading).
  9. Visiting /admin/settings as a regular member is redirected (not accessible).
"""

import uuid

import pytest
from playwright.sync_api import Page, expect

from app.auth.schemas import AccountClaims
from tests.e2e_support import (
    complete_onboarding,
    login_as,
)

BASE_URL = "http://localhost:5173"


# ── helpers ────────────────────────────────────────────────────────────────


def _make_token(role: str) -> str:
    claims = AccountClaims(
        sub=str(uuid.uuid4()),
        email=f"{role}-{uuid.uuid4().hex[:6]}@dojo.test",
        role=role,  # type: ignore[arg-type]
    )
    token = login_as(claims)
    # Seed the acting user's Member profile so the RequireProfile gate does
    # not bounce every navigation to /onboarding before assertions run (#221).
    complete_onboarding(token)
    return token


def _inject_cookie(page: Page, token: str) -> None:
    page.goto(BASE_URL)
    page.context.add_cookies(
        [{"name": "access_token", "value": token, "url": BASE_URL}]
    )


# ── AC6 — Admin nav renders both Settings and Admin Settings links ─────────


def test_admin_nav_has_settings_and_admin_settings_links(page: Page) -> None:
    token = _make_token("admin")
    _inject_cookie(page, token)

    page.goto(f"{BASE_URL}/")

    # Personal Settings link → /settings
    settings_link = page.get_by_role("link", name="Settings", exact=True)
    expect(settings_link).to_be_visible()
    expect(settings_link).to_have_attribute("href", "/settings")

    # Admin Settings link → /admin/settings
    admin_settings_link = page.get_by_role("link", name="Admin Settings")
    expect(admin_settings_link).to_be_visible()
    expect(admin_settings_link).to_have_attribute("href", "/admin/settings")


# ── AC7 — /settings as admin renders Personal Details UI ──────────────────


def test_admin_settings_page_renders_personal_details(page: Page) -> None:
    token = _make_token("admin")
    _inject_cookie(page, token)

    page.goto(f"{BASE_URL}/settings")

    expect(page.get_by_role("heading", name="Settings")).to_be_visible()
    expect(page.get_by_text("Personal Details")).to_be_visible()


# ── AC8 — /admin/settings renders Admin Settings page ─────────────────────


def test_admin_settings_page_renders_non_blank_content(page: Page) -> None:
    token = _make_token("admin")
    _inject_cookie(page, token)

    page.goto(f"{BASE_URL}/admin/settings")

    expect(page.get_by_role("heading", name="Admin Settings")).to_be_visible()


def test_admin_settings_shows_the_running_version(page: Page) -> None:
    """#556: the test servers are not a release build, so the Version is dev."""
    token = _make_token("admin")
    _inject_cookie(page, token)

    page.goto(f"{BASE_URL}/admin/settings")

    expect(page.get_by_text("Version dev", exact=True)).to_be_visible()


# ── AC9 — /admin/settings is not accessible to a regular member ───────────


def test_admin_settings_page_redirects_regular_member(page: Page) -> None:
    token = _make_token("member")
    _inject_cookie(page, token)

    page.goto(f"{BASE_URL}/admin/settings")

    # RequireAdmin guard redirects non-admins to /
    expect(page).not_to_have_url(f"{BASE_URL}/admin/settings")


# ── #610 — Admin Settings sub-pages ────────────────────────────────────────

SUB_PAGES = [
    ("General", "/admin/settings/general", "Dojo Branding"),
    ("Session Types", "/admin/settings/session-types", "Session Types"),
    ("Federations", "/admin/settings/federations", "Federations"),
    ("Invites", "/admin/settings/invites", "Invites"),
    ("Grades", "/admin/settings/grades", "Grade management"),
]


def test_admin_settings_lands_on_general(page: Page) -> None:
    _inject_cookie(page, _make_token("admin"))

    page.goto(f"{BASE_URL}/admin/settings")

    expect(page).to_have_url(f"{BASE_URL}/admin/settings/general")
    expect(page.get_by_role("heading", name="Check-in Window")).to_be_visible()


@pytest.mark.parametrize("width", [1280, 375])
def test_sub_nav_opens_each_sub_page_and_marks_it_current(
    page: Page, width: int
) -> None:
    page.set_viewport_size({"width": width, "height": 800})
    _inject_cookie(page, _make_token("admin"))
    page.goto(f"{BASE_URL}/admin/settings")
    sub_nav = page.get_by_role("navigation", name="Admin Settings sections")

    for label, path, heading in SUB_PAGES:
        link = sub_nav.get_by_role("link", name=label, exact=True)
        link.click()
        expect(page).to_have_url(f"{BASE_URL}{path}")
        expect(page.get_by_role("heading", name=heading, exact=True)).to_be_visible()
        expect(link).to_have_attribute("aria-current", "page")
        expect(sub_nav.locator("[aria-current='page']")).to_have_count(1)


def test_non_admin_is_redirected_from_every_sub_page(page: Page) -> None:
    _inject_cookie(page, _make_token("member"))

    for _label, path, _heading in SUB_PAGES:
        page.goto(f"{BASE_URL}{path}")
        expect(page).to_have_url(f"{BASE_URL}/")


@pytest.mark.parametrize("old_path", ["/settings/invites", "/grades"])
def test_old_paths_are_gone(page: Page, old_path: str) -> None:
    _inject_cookie(page, _make_token("admin"))

    page.goto(f"{BASE_URL}{old_path}", wait_until="networkidle")

    # No route matches, so the app renders nothing at all.
    expect(page.locator("#root > *")).to_have_count(0)


def test_admin_nav_has_no_grades_item(page: Page) -> None:
    page.set_viewport_size({"width": 1280, "height": 800})
    _inject_cookie(page, _make_token("admin"))
    page.goto(f"{BASE_URL}/")

    sidebar = page.locator("[data-slot='sidebar']")
    expect(sidebar.get_by_role("link", name="Members", exact=True)).to_be_visible()
    expect(sidebar.get_by_role("link", name="Grades", exact=True)).to_have_count(0)
