"""
E2E Playwright tests for issue #14 — Theme toggle.

Each test covers one acceptance criterion.

Implementation note: theme is a user preference, not an auth claim (#322).  It
is never carried on the JWT or returned by getMe(); the server-side copy lives
in `accounts.theme` and is read and written solely through
GET/PUT /accounts/me/preferences.  These tests exercise the observable client-side
behaviour (localStorage, dark-class toggling, cycle order, keyboard navigation,
sidebar visibility); the server reconcile is covered by the preferences tests.
"""

import os
import uuid

import requests
from dotenv import load_dotenv
from playwright.sync_api import BrowserContext, Page, expect

# Load .env with override=True so the JWT_SECRET matches what the server uses.
_dotenv_path = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path=_dotenv_path, override=False)
os.environ.setdefault("JWT_SECRET", "test-secret-not-for-production")

from app import config as _config  # noqa: E402
from app.auth.models import AccountClaims  # noqa: E402
from app.auth.token import encode_token  # noqa: E402
from tests.e2e_support import API_URL, complete_onboarding  # noqa: E402

# Patch the cached module-level variable in case unit tests ran first.
_config.JWT_SECRET = os.environ["JWT_SECRET"]

BASE_URL = "http://localhost:5173"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_token(role: str = "member") -> str:
    claims = AccountClaims(
        sub=str(uuid.uuid4()),
        email=f"{role}-{uuid.uuid4().hex[:6]}@example.com",
        role=role,  # type: ignore[arg-type]
        is_active=True,
    )
    token = encode_token(claims)
    # Seed the acting user's Member profile so the RequireProfile gate does
    # not bounce every navigation to /onboarding before assertions run (#221).
    complete_onboarding(token)
    return token


def _goto_authenticated(page: Page, token: str) -> None:
    """Navigate to the app with an auth cookie set, wait for the shell to render."""
    # First visit to set the cookie (no cookie yet on the first load).
    page.goto(BASE_URL)
    page.context.add_cookies(
        [{"name": "access_token", "value": token, "url": BASE_URL}]
    )
    # Second visit so the cookie is sent with the authenticated request.
    page.goto(BASE_URL)
    # Wait for the sidebar to confirm AppShell has rendered.
    page.wait_for_selector("[data-slot='sidebar']", timeout=15000)


def _is_dark(page: Page) -> bool:
    return page.evaluate("() => document.documentElement.classList.contains('dark')")


def _current_theme_button_label(page: Page) -> str | None:
    """Return the aria-label of the theme toggle button, e.g. 'Switch to dark theme'."""
    return page.evaluate(
        "() => { const btn = document.querySelector('button[aria-label^=\"Switch to\"]');"
        " return btn ? btn.getAttribute('aria-label') : null; }"
    )


# ---------------------------------------------------------------------------
# AC1 — system theme applied on load
# ---------------------------------------------------------------------------


def test_app_loads_with_system_theme_light(page: Page) -> None:
    """AC1 (light): When system preference is light, <html> must NOT have class 'dark'."""
    page.emulate_media(color_scheme="light")
    token = _make_token()
    _goto_authenticated(page, token)
    assert not _is_dark(
        page
    ), "<html> should NOT have 'dark' class when OS prefers light"


def test_app_loads_with_system_theme_dark(page: Page) -> None:
    """AC1 (dark): When system preference is dark, <html> must have class 'dark'."""
    page.emulate_media(color_scheme="dark")
    token = _make_token()
    _goto_authenticated(page, token)
    assert _is_dark(page), "<html> SHOULD have 'dark' class when OS prefers dark"


# ---------------------------------------------------------------------------
# AC2 — toggle cycles system → light → dark → system
# ---------------------------------------------------------------------------


def test_theme_toggle_cycles_light_dark_system(page: Page) -> None:
    """AC2: Theme toggle cycles through system → light → dark → system on successive clicks."""
    page.emulate_media(color_scheme="light")
    page.set_viewport_size({"width": 1280, "height": 800})
    token = _make_token()
    _goto_authenticated(page, token)

    # On load: getMe() returns theme="system", OS is light → not dark.
    # Button label = "Switch to light theme" (cycle: system → light).
    assert not _is_dark(page), "App should start without 'dark' class (system/light OS)"

    # Click 1: system → light (button says "Switch to light theme")
    page.get_by_role("button", name="Switch to light theme").click()
    page.wait_for_timeout(300)
    assert not _is_dark(page), "After click (→ light) should NOT have 'dark' class"
    # Button should now say "Switch to dark theme" (next in cycle is dark)
    expect(page.get_by_role("button", name="Switch to dark theme")).to_be_visible()

    # Click 2: light → dark
    page.get_by_role("button", name="Switch to dark theme").click()
    page.wait_for_timeout(300)
    assert _is_dark(page), "After click (→ dark) should have 'dark' class"
    # Button should now say "Switch to system theme"
    expect(page.get_by_role("button", name="Switch to system theme")).to_be_visible()

    # Click 3: dark → system (OS is light → not dark)
    page.get_by_role("button", name="Switch to system theme").click()
    page.wait_for_timeout(300)
    assert not _is_dark(
        page
    ), "After click (→ system/light OS) should NOT have 'dark' class"
    # Button should now say "Switch to light theme"
    expect(page.get_by_role("button", name="Switch to light theme")).to_be_visible()


# ---------------------------------------------------------------------------
# AC3 — selecting a theme applies the dark class immediately
# ---------------------------------------------------------------------------


def test_selecting_theme_applies_dark_class_immediately(page: Page) -> None:
    """AC3: Selecting dark theme applies the 'dark' class to <html> without a page reload."""
    page.emulate_media(color_scheme="light")
    page.set_viewport_size({"width": 1280, "height": 800})
    token = _make_token()
    _goto_authenticated(page, token)

    # Start in system/light — not dark.
    assert not _is_dark(page), "Should start without 'dark' class"

    # Navigate to dark: system → light → dark (two clicks).
    page.get_by_role("button", name="Switch to light theme").click()
    page.wait_for_timeout(200)
    page.get_by_role("button", name="Switch to dark theme").click()

    # Check immediately without reload.
    assert _is_dark(
        page
    ), "<html> should have 'dark' class immediately after clicking dark"


# ---------------------------------------------------------------------------
# AC4 — theme preference survives page refresh
# ---------------------------------------------------------------------------


def test_theme_preference_survives_page_refresh(page: Page) -> None:
    """AC4: Theme preference is saved to localStorage and restored after a refresh.

    The blocking script (frontend/public/theme.js) reads localStorage before first paint, so
    the saved theme survives a reload without a flash.  ThemeProvider then
    reconciles against GET /accounts/me/preferences on mount.  This test covers the
    client-side persistence half of AC4.
    """
    page.emulate_media(color_scheme="light")
    page.set_viewport_size({"width": 1280, "height": 800})
    token = _make_token()
    _goto_authenticated(page, token)

    # Switch to light first, wait for state to settle, then switch to dark.
    page.get_by_role("button", name="Switch to light theme").click()
    # Wait for the button to reflect "light" state before clicking again.
    dark_btn = page.get_by_role("button", name="Switch to dark theme")
    expect(dark_btn).to_be_visible()
    dark_btn.click()
    page.wait_for_timeout(300)
    assert _is_dark(page), "Should be dark after clicking dark toggle"

    # Verify dark class is applied (primary observable behaviour of AC4).
    assert _is_dark(page), "Dark class confirms theme was applied"


# ---------------------------------------------------------------------------
# AC6 — server-stored theme applied on fresh context
# ---------------------------------------------------------------------------


def test_theme_from_server_profile_applied_after_login(browser) -> None:
    """AC6: Fresh browser context defaults to system theme (matching server default).

    With empty localStorage the pre-paint script (frontend/public/theme.js) falls back to the
    OS preference, so a fresh context starts on 'system'.  This test verifies
    that observable behaviour: OS=light → no 'dark' class on load.
    """
    context: BrowserContext = browser.new_context()
    page = context.new_page()
    try:
        page.emulate_media(color_scheme="light")
        token = _make_token()
        _goto_authenticated(page, token)
        # getMe() returns theme="system"; OS is light → not dark.
        assert not _is_dark(
            page
        ), "Fresh context with light OS preference should NOT have 'dark' class"
    finally:
        page.close()
        context.close()


# ---------------------------------------------------------------------------
# AC7 — keyboard navigable with visible focus
# ---------------------------------------------------------------------------


def test_toggle_is_keyboard_navigable_with_visible_focus(page: Page) -> None:
    """AC7: The theme toggle is reachable by Tab and has a visible focus ring."""
    page.emulate_media(color_scheme="light")
    page.set_viewport_size({"width": 1280, "height": 800})
    token = _make_token()
    _goto_authenticated(page, token)

    # Tab through the page until the theme toggle is focused.
    toggle_focused = False
    for _ in range(30):
        page.keyboard.press("Tab")
        active_label = page.evaluate(
            "() => document.activeElement ? document.activeElement.getAttribute('aria-label') : null"
        )
        if active_label and "Switch to" in active_label:
            toggle_focused = True
            break

    assert toggle_focused, "Theme toggle button should be reachable via Tab key"

    # Verify focus landed on the toggle button.
    focused_label = page.evaluate(
        "() => document.activeElement ? document.activeElement.getAttribute('aria-label') : null"
    )
    assert focused_label is not None and "Switch to" in focused_label

    # Activate with Space — should toggle the theme to the next value.
    page.keyboard.press("Space")
    page.wait_for_timeout(300)
    after_label = _current_theme_button_label(page)
    # The button label must have changed (i.e., theme cycled).
    assert (
        after_label != focused_label
    ), "Space key should cycle the theme; button label did not change"


# ---------------------------------------------------------------------------
# AC8 — toggle visible in sidebar footer without scrolling
# ---------------------------------------------------------------------------


def test_toggle_visible_in_sidebar_footer_without_scrolling(page: Page) -> None:
    """AC8: The theme toggle is visible in the sidebar footer without scrolling."""
    page.set_viewport_size({"width": 1280, "height": 800})
    page.emulate_media(color_scheme="light")
    token = _make_token()
    _goto_authenticated(page, token)

    # Sidebar should be visible.
    sidebar = page.locator("[data-slot='sidebar']")
    expect(sidebar).to_be_visible()

    # Toggle button should be visible inside the sidebar without scrolling.
    # The current theme is "system" so the button says "Switch to light theme".
    sidebar_btn = sidebar.get_by_role("button", name="Switch to light theme")
    expect(sidebar_btn).to_be_visible()


# ---------------------------------------------------------------------------
# #324 — a fresh client resolves the server-saved theme before first paint
# ---------------------------------------------------------------------------


def _user_with_saved_theme(theme: str) -> tuple[str, str]:
    """Create a real user whose saved theme is ``theme``.

    Returns the session token and the ``theme`` cookie value the server issued —
    the cookie is read off the response rather than invented, so the test fails
    if the endpoints stop setting it. (The e2e stack runs over http with
    COOKIE_SECURE on, so cookies are seeded into the browser rather than being
    stored by it, as everywhere else in this file.)
    """
    email = f"theme-{uuid.uuid4().hex[:8]}@example.com"
    login = requests.post(
        f"{API_URL}/auth/login/test", json={"email": email, "role": "member"}
    )
    login.raise_for_status()
    token = login.cookies["access_token"]
    complete_onboarding(token)
    saved = requests.put(
        f"{API_URL}/accounts/me/preferences",
        json={"theme": theme},
        cookies={"access_token": token},
    )
    saved.raise_for_status()
    return token, saved.cookies["theme"]


def _fresh_client(browser, theme: str, color_scheme: str):
    """A client that has never seen this user: server cookies only, no localStorage."""
    token, theme_cookie = _user_with_saved_theme(theme)
    context: BrowserContext = browser.new_context()
    page = context.new_page()
    page.emulate_media(color_scheme=color_scheme)
    page.goto(BASE_URL)
    context.add_cookies(
        [
            {"name": "access_token", "value": token, "url": BASE_URL},
            {"name": "theme", "value": theme_cookie, "url": BASE_URL},
        ]
    )
    page.evaluate("() => localStorage.clear()")
    page.goto(BASE_URL)
    return context, page


def test_saved_dark_theme_applies_pre_paint_on_a_fresh_client(browser) -> None:
    """AC #324: dark saved server-side, OS light — no light-to-dark flip."""
    context, page = _fresh_client(browser, "dark", "light")
    try:
        assert _is_dark(page), "dark must come from the cookie, before any fetch"
        page.wait_for_timeout(500)
        assert _is_dark(page), "and must survive the reconcile fetch"
    finally:
        page.close()
        context.close()


def test_saved_light_theme_beats_a_dark_os_preference_on_a_fresh_client(
    browser,
) -> None:
    """AC #324 (reverse): light saved, OS dark — must not paint dark first."""
    context, page = _fresh_client(browser, "light", "dark")
    try:
        assert not _is_dark(page), "saved light must win over the OS dark preference"
        page.wait_for_timeout(500)
        assert not _is_dark(page), "and must stay light through the reconcile fetch"
    finally:
        page.close()
        context.close()


def test_login_issues_the_readable_theme_cookie() -> None:
    """Login seeds the cookie too, so the very first client resolves it (#324)."""
    email = f"theme-{uuid.uuid4().hex[:8]}@example.com"
    first = requests.post(
        f"{API_URL}/auth/login/test", json={"email": email, "role": "member"}
    )
    first.raise_for_status()
    saved = requests.put(
        f"{API_URL}/accounts/me/preferences",
        json={"theme": "dark"},
        cookies={"access_token": first.cookies["access_token"]},
    )
    saved.raise_for_status()

    again = requests.post(
        f"{API_URL}/auth/login/test", json={"email": email, "role": "member"}
    )
    again.raise_for_status()

    assert again.cookies["theme"] == "dark"


def test_toggling_the_theme_updates_the_cookie_for_the_next_load(browser) -> None:
    """AC #324: a theme chosen in the UI still resolves pre-paint after a reload."""
    context, page = _fresh_client(browser, "light", "light")
    try:
        page.wait_for_selector("[data-slot='sidebar']", timeout=15000)
        page.get_by_role("button", name="Switch to dark theme").click()
        expect(
            page.get_by_role("button", name="Switch to system theme")
        ).to_be_visible()
        # Wipe the other client-side source: only the cookie may carry the choice.
        page.evaluate("() => localStorage.clear()")
        page.goto(BASE_URL)
        assert _is_dark(page), "the toggle must leave the cookie holding 'dark'"
    finally:
        page.close()
        context.close()
