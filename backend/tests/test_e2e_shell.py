"""
E2E tests for Issue #13 — AppShell & role-aware navigation.
"""

import re
import uuid

import pytest
from playwright.sync_api import Page, expect

from app.auth.schemas import AccountClaims
from tests.e2e_support import (
    complete_onboarding,
    login_as,
)

BASE_URL = "http://localhost:5173"
API_URL = "http://localhost:8000/api"


# ---------------------------------------------------------------------------
# Auth fixtures — set an access_token cookie so the app treats the browser
# as authenticated for the given role.
# ---------------------------------------------------------------------------


def _make_token(role: str) -> str:
    claims = AccountClaims(
        sub=str(uuid.uuid4()),
        email=f"{role}-{uuid.uuid4().hex[:6]}@example.com",
        role=role,  # type: ignore[arg-type]
    )
    token = login_as(claims)
    # Seed the acting user's Member profile so the RequireProfile gate does
    # not bounce every navigation to /onboarding before assertions run (#221).
    complete_onboarding(token)
    return token


@pytest.fixture()
def member_page(page: Page) -> Page:
    """Page pre-authenticated as a member role user."""
    token = _make_token("member")
    page.goto(BASE_URL)
    page.context.add_cookies(
        [
            {
                "name": "access_token",
                "value": token,
                "url": BASE_URL,
            }
        ]
    )
    # Navigate to the app now that the cookie is set so getMe() succeeds.
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")
    return page


@pytest.fixture()
def admin_page(page: Page) -> Page:
    """Page pre-authenticated as an admin role user."""
    token = _make_token("admin")
    page.goto(BASE_URL)
    page.context.add_cookies(
        [
            {
                "name": "access_token",
                "value": token,
                "url": BASE_URL,
            }
        ]
    )
    # Navigate to the app now that the cookie is set so getMe() succeeds.
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")
    return page


# ---------------------------------------------------------------------------
# Tests — one per acceptance criterion
# ---------------------------------------------------------------------------


def test_appshell_absent_on_login_page(page: Page) -> None:
    """AC1: AppShell wraps all routes except /login and /register.

    Shell (sidebar / tab bar) must not be present on the login page.
    """
    page.goto(f"{BASE_URL}/login")
    page.wait_for_load_state("networkidle")

    # The sidebar element must not be present on the login page.
    expect(page.locator("[data-slot='sidebar']")).not_to_be_visible()

    # The bottom tab bar must not be present on the login page.
    expect(page.get_by_role("navigation", name="Main navigation")).not_to_be_visible()


def test_sidebar_visible_at_desktop_width(admin_page: Page) -> None:
    """AC2: Sidebar is visible at 1280px viewport width."""
    admin_page.set_viewport_size({"width": 1280, "height": 800})
    # shadcn Sidebar renders with data-slot="sidebar"
    sidebar = admin_page.locator("[data-slot='sidebar']")
    expect(sidebar).to_be_visible()


def test_bottom_tab_bar_visible_at_mobile_width(member_page: Page) -> None:
    """AC3: Bottom tab bar is visible at 375px viewport width."""
    member_page.set_viewport_size({"width": 375, "height": 667})
    tab_bar = member_page.get_by_role("navigation", name="Main navigation")
    expect(tab_bar).to_be_visible()


def test_member_nav_has_no_restricted_links(member_page: Page) -> None:
    """AC4: Member nav contains no links to Members, Grades, Reports, or Settings."""
    # Check at desktop width (sidebar visible)
    member_page.set_viewport_size({"width": 1280, "height": 800})
    sidebar = member_page.locator("[data-slot='sidebar']")
    expect(sidebar).to_be_visible()

    restricted = ["Members", "Grades", "Reports", "Settings"]
    for label in restricted:
        expect(sidebar.get_by_role("link", name=label)).not_to_be_attached()


def test_admin_nav_contains_all_six_sections(admin_page: Page) -> None:
    """AC5: Admin nav contains all 6 sections:
    Dashboard, Members, Sessions, My Attendance, Reports, Settings.
    (Grades moved under Admin Settings in #610.)
    """
    admin_page.set_viewport_size({"width": 1280, "height": 800})
    sidebar = admin_page.locator("[data-slot='sidebar']")
    expect(sidebar).to_be_visible()

    all_sections = [
        "Dashboard",
        "Members",
        "Sessions",
        "My Attendance",
        "Reports",
        "Settings",
    ]
    for label in all_sections:
        expect(sidebar.get_by_role("link", name=label, exact=True)).to_be_visible()


def test_active_nav_item_is_visually_distinct(admin_page: Page) -> None:
    """AC6: Active nav item is visually distinct from inactive items.

    The active link carries aria-current="page" which drives the visual style.
    """
    admin_page.set_viewport_size({"width": 1280, "height": 800})
    sidebar = admin_page.locator("[data-slot='sidebar']")
    expect(sidebar).to_be_visible()

    # The root path "/" is the Dashboard, which should be active at load.
    active_link = sidebar.locator("[aria-current='page']")
    expect(active_link).to_be_visible()

    # Navigate to Members and verify aria-current moves to that link.
    sidebar.get_by_role("link", name="Members").click()
    admin_page.wait_for_load_state("networkidle")
    members_link = sidebar.get_by_role("link", name="Members")
    expect(members_link).to_have_attribute("aria-current", "page")

    # Dashboard should no longer be active.
    dashboard_link = sidebar.get_by_role("link", name="Dashboard")
    expect(dashboard_link).not_to_have_attribute("aria-current", "page")


def test_bottom_tab_bar_touch_targets_are_44px(member_page: Page) -> None:
    """AC7: Bottom tab bar touch targets are at least 44x44 px.

    Measured via JS getBoundingClientRect on each tab bar link/button.
    """
    member_page.set_viewport_size({"width": 375, "height": 667})

    # Collect all interactive elements within the bottom tab bar nav.
    sizes = member_page.evaluate("""() => {
        const nav = document.querySelector("nav[aria-label='Main navigation']");
        if (!nav) return null;
        const items = Array.from(nav.querySelectorAll("a, button"));
        return items.map(el => {
            const rect = el.getBoundingClientRect();
            return { width: rect.width, height: rect.height, label: el.getAttribute('aria-label') };
        });
    }""")

    assert sizes is not None, "Bottom tab bar nav not found in the DOM"
    assert len(sizes) > 0, "No tab bar items found"

    for item in sizes:
        assert item["height"] >= 44, (
            f"Tab bar item '{item.get('label')}' height {item['height']}px < 44px"
        )
        assert item["width"] >= 44, (
            f"Tab bar item '{item.get('label')}' width {item['width']}px < 44px"
        )


def test_sidebar_header_shows_my_dojo(admin_page: Page) -> None:
    """AC8: Sidebar header shows the configured dojo name.

    The name defaults to 'My Dojo' but is global mutable state other e2e tests
    change, so assert whatever the API currently reports rather than the literal
    default (which would be order-dependent).
    """
    admin_page.set_viewport_size({"width": 1280, "height": 800})
    dojo_name = admin_page.request.get(f"{API_URL}/settings/dojo").json()["dojo_name"]
    sidebar = admin_page.locator("[data-slot='sidebar']")
    expect(sidebar).to_be_visible()
    expect(sidebar.get_by_text(dojo_name)).to_be_visible()


# ---------------------------------------------------------------------------
# Issue #12 E2E tests — promoted from xfail stubs
# ---------------------------------------------------------------------------


def test_sidebar_renders_on_desktop_viewport(admin_page: Page) -> None:
    """Issue #12: Sidebar navigation is present at 1280px wide desktop viewport."""
    admin_page.set_viewport_size({"width": 1280, "height": 800})
    sidebar = admin_page.locator("[data-slot='sidebar']")
    expect(sidebar).to_be_visible()


def test_bottom_tab_bar_renders_on_mobile_viewport(member_page: Page) -> None:
    """Issue #12: Bottom tab bar navigation is present at 375px wide mobile viewport."""
    member_page.set_viewport_size({"width": 375, "height": 667})
    tab_bar = member_page.get_by_role("navigation", name="Main navigation")
    expect(tab_bar).to_be_visible()


def test_my_attendance_tab_label_fits_one_line_at_375px(member_page: Page) -> None:
    """Issue #572: in the 375px bottom tab bar the My Attendance tab's label
    sits on one line, unclipped, like its neighbours."""
    member_page.set_viewport_size({"width": 375, "height": 667})
    tab = member_page.get_by_role("navigation", name="Main navigation").get_by_role(
        "link", name="My Attendance"
    )
    expect(tab).to_be_visible()

    metrics = tab.locator("span").evaluate(
        """el => ({
            height: el.getBoundingClientRect().height,
            lineHeight: parseFloat(getComputedStyle(el).lineHeight),
            scrollWidth: el.scrollWidth,
            clientWidth: el.clientWidth,
            text: el.textContent,
        })"""
    )
    assert metrics["height"] <= metrics["lineHeight"] * 1.5, metrics
    assert metrics["scrollWidth"] <= metrics["clientWidth"], metrics


def test_member_nav_excludes_restricted_sections(member_page: Page) -> None:
    """Issue #12: Member nav does NOT contain Members, Grades, Reports, Settings links."""
    member_page.set_viewport_size({"width": 1280, "height": 800})
    sidebar = member_page.locator("[data-slot='sidebar']")
    expect(sidebar).to_be_visible()

    for label in ["Members", "Grades", "Reports", "Settings"]:
        expect(sidebar.get_by_role("link", name=label)).not_to_be_attached()


def test_member_nav_opens_my_attendance(member_page: Page) -> None:
    """Issue #572: the Member nav's My Attendance link opens the Member's own
    Attendance history, with a pointer to check-in on the Sessions page."""
    member_page.set_viewport_size({"width": 1280, "height": 800})
    sidebar = member_page.locator("[data-slot='sidebar']")
    sidebar.get_by_role("link", name="My Attendance", exact=True).click()

    expect(member_page).to_have_url(re.compile(r"/attendance$"))
    expect(
        member_page.get_by_role("heading", name="My Attendance", level=1)
    ).to_be_visible()
    expect(member_page.get_by_role("link", name="Sessions page")).to_be_visible()


def test_admin_nav_contains_all_sections(admin_page: Page) -> None:
    """Issue #12: Admin nav contains Dashboard, Members, Sessions, My Attendance,
    Reports, Settings. (Grades moved under Admin Settings in #610.)"""
    admin_page.set_viewport_size({"width": 1280, "height": 800})
    sidebar = admin_page.locator("[data-slot='sidebar']")
    expect(sidebar).to_be_visible()

    for label in [
        "Dashboard",
        "Members",
        "Sessions",
        "My Attendance",
        "Reports",
        "Settings",
    ]:
        expect(sidebar.get_by_role("link", name=label, exact=True)).to_be_visible()


def test_theme_toggle_cycles_light_dark_system(admin_page: Page) -> None:
    """Issue #12: Theme toggle cycles through themes and applies the correct
    dark class to the html element when dark mode is selected.

    The test is state-agnostic: it finds the current toggle button and cycles
    until dark mode is reached, verifying the html.dark class is applied and
    then removed on the next click.
    """
    admin_page.set_viewport_size({"width": 1280, "height": 800})
    admin_page.wait_for_load_state("networkidle")

    # Find the theme toggle button — it always has an aria-label "Switch to X theme".
    toggle = admin_page.locator("button[aria-label^='Switch to']")
    expect(toggle).to_be_visible()

    # Cycle through all three states (at most 3 clicks) to reach dark mode.
    reached_dark = False
    for _ in range(3):
        label: str = toggle.get_attribute("aria-label") or ""
        if label == "Switch to dark theme":
            # Current theme is light — click to go dark.
            toggle.click()
            admin_page.wait_for_function(
                "() => document.documentElement.classList.contains('dark')"
            )
            html_classes: str = admin_page.evaluate(
                "() => document.documentElement.className"
            )
            assert "dark" in html_classes, (
                f"Expected 'dark' class after toggling to dark, got: {html_classes}"
            )
            # Click again (dark → system/light) — dark class should be removed.
            toggle.click()
            admin_page.wait_for_function(
                "() => !document.documentElement.classList.contains('dark')"
            )
            html_classes = admin_page.evaluate(
                "() => document.documentElement.className"
            )
            assert "dark" not in html_classes, (
                f"Expected no 'dark' class after leaving dark mode, got: {html_classes}"
            )
            reached_dark = True
            break
        # Not at the right starting point — click once and try again.
        toggle.click()
        admin_page.wait_for_load_state("domcontentloaded")

    assert reached_dark, "Theme toggle never entered dark mode within 3 clicks"


def test_dojo_name_appears_in_sidebar_header(admin_page: Page) -> None:
    """Issue #12: The configured dojo name is shown in the sidebar header.

    The dojo name defaults to 'My Dojo' when no settings have been configured.
    """
    admin_page.set_viewport_size({"width": 1280, "height": 800})
    # Dojo name is global mutable state; assert whatever the API currently
    # reports rather than the literal default (order-dependent otherwise).
    dojo_name = admin_page.request.get(f"{API_URL}/settings/dojo").json()["dojo_name"]
    sidebar = admin_page.locator("[data-slot='sidebar']")
    expect(sidebar).to_be_visible()
    expect(sidebar.get_by_text(dojo_name)).to_be_visible()
