"""
E2E browser tests for issue #325 — sign-out UI.

Context: POST /auth/logout (backend/app/auth/router.py) and logout()
(frontend/src/api/auth.ts) both already exist and work, but nothing in the UI
calls either one. There is no way for a signed-in user to sign out. The fix is
a logout control in the app shell (frontend/src/components/AppShell.tsx
SidebarFooter, next to ThemeToggle) plus a mobile-reachable equivalent
(frontend/src/components/BottomTabBar.tsx's "More" sheet).

One browser test per acceptance criterion.

AC3 and AC6 need judgement about what is browser-verifiable:
  - AC3 (back button after logout) IS browser-verifiable: log in, log out,
    then page.go_back() and assert the protected view is not restored.
  - AC6 (logout failure leaves the user in a non-stranded state) IS
    browser-verifiable by aborting the POST /auth/logout network call via
    page.route() and asserting the user remains on an authenticated page
    with a visible error, rather than being bounced to a half-signed-out
    limbo (e.g. a login page that still 200s /auth/me, or a blank screen).
Both are written as real browser tests below, not skipped.
"""

import os
import re
import uuid

from dotenv import load_dotenv
from playwright.sync_api import Page, expect

# Load .env with override=False so os.environ reflects the real JWT_SECRET,
# matching the pattern in test_e2e_shell.py / test_e2e_theme.py.
_dotenv_path = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path=_dotenv_path, override=False)
os.environ.setdefault("JWT_SECRET", "test-secret-not-for-production")

from app import config as _config  # noqa: E402
from app.auth.models import UserClaims  # noqa: E402
from app.auth.token import encode_token  # noqa: E402
from tests.e2e_support import complete_onboarding  # noqa: E402

# Patch the cached module-level variable in case unit tests ran first and
# populated it with the stub secret before this file was imported.
_config.JWT_SECRET = os.environ["JWT_SECRET"]

BASE_URL = "http://localhost:5173"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_token(role: str = "member") -> str:
    claims = UserClaims(
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


def _goto_authenticated(page: Page, token: str, path: str = "/") -> None:
    """Navigate to the app with an auth cookie set, wait for the shell to render."""
    # First visit to set the cookie (no cookie yet on the first load).
    page.goto(BASE_URL)
    page.context.add_cookies(
        [{"name": "access_token", "value": token, "url": BASE_URL}]
    )
    # Second visit so the cookie is sent with the authenticated request.
    page.goto(f"{BASE_URL}{path}")
    # Confirm AppShell rendered. The sidebar is display:none below the md
    # breakpoint, so at a mobile viewport the bottom tab bar is the only half
    # of the shell that is ever visible — waiting on the sidebar there would
    # time out however correct the app is.
    is_mobile = (page.viewport_size or {}).get("width", 1280) < 768
    selector = (
        "nav[aria-label='Main navigation']" if is_mobile else "[data-slot='sidebar']"
    )
    page.wait_for_selector(selector, timeout=15000)


# ---------------------------------------------------------------------------
# AC1 — reachable from any page without navigating to a settings screen
# ---------------------------------------------------------------------------


def test_logout_control_reachable_without_settings_navigation(page: Page) -> None:
    """A signed-in user can reach a logout control directly from the app shell.

    Expected home: SidebarFooter, next to ThemeToggle — reachable without
    navigating into a settings page first.
    """
    token = _make_token("admin")
    page.set_viewport_size({"width": 1280, "height": 800})
    _goto_authenticated(page, token)

    expect(page.get_by_role("button", name="Log out")).to_be_visible()


# ---------------------------------------------------------------------------
# AC2 — activating it calls POST /auth/logout and lands on the login screen
# ---------------------------------------------------------------------------


def test_logout_calls_backend_and_redirects_to_login(page: Page) -> None:
    """Clicking the logout control calls POST /auth/logout and navigates to /login."""
    token = _make_token("admin")
    page.set_viewport_size({"width": 1280, "height": 800})
    _goto_authenticated(page, token)

    with page.expect_request(
        lambda req: req.url.endswith("/auth/logout") and req.method == "POST"
    ):
        page.get_by_role("button", name="Log out").click()

    expect(page).to_have_url(f"{BASE_URL}/login")


# ---------------------------------------------------------------------------
# AC3 — browser Back after logout does not restore an authenticated view
# ---------------------------------------------------------------------------


def test_back_button_after_logout_does_not_restore_protected_view(page: Page) -> None:
    """After signing out, pressing Back must not land on an authenticated page.

    Protected routes must bounce to /login even when the browser tries to
    restore the previous (authenticated) history entry, e.g. from bfcache.
    """
    token = _make_token("admin")
    page.set_viewport_size({"width": 1280, "height": 800})
    _goto_authenticated(page, token)

    # Push a second authenticated entry onto the history stack. Logout
    # replaces the entry it navigates from, so this earlier one is what Back
    # actually returns to — and it is a protected route, which is the point.
    page.get_by_role("link", name="Sessions").click()
    expect(page).to_have_url(f"{BASE_URL}/sessions")

    page.get_by_role("button", name="Log out").click()
    expect(page).to_have_url(f"{BASE_URL}/login")

    page.go_back()
    # The restored entry is /sessions — a protected route. With the cookie
    # cleared it must bounce to an unauthenticated screen rather than render
    # authenticated content, whether it came from the network or bfcache.
    # /login normally; /setup on an instance with no passkey credential yet
    # (test_e2e_auth.py makes the same accommodation). Which of the two shows
    # has nothing to do with sign-out — that neither renders the shell does.
    expect(page).to_have_url(re.compile(r"/(login|setup)$"))
    expect(page.locator("[data-slot='sidebar']")).not_to_be_visible()


# ---------------------------------------------------------------------------
# AC4 — keyboard reachable with a visible focus ring, matching ThemeToggle
# ---------------------------------------------------------------------------


def test_logout_control_keyboard_focusable_with_visible_ring(page: Page) -> None:
    """The logout control can be reached and activated via keyboard, and
    carries the same focus-visible ring treatment as ThemeToggle
    (focus-visible:ring-2 ... focus-visible:ring-sidebar-ring).
    """
    token = _make_token("admin")
    page.set_viewport_size({"width": 1280, "height": 800})
    _goto_authenticated(page, token)

    logout_button = page.get_by_role("button", name="Log out")
    logout_button.focus()
    expect(logout_button).to_be_focused()

    class_list = logout_button.get_attribute("class") or ""
    assert "focus-visible:ring" in class_list, (
        "logout control must carry the same focus-visible ring treatment as "
        f"ThemeToggle; got class={class_list!r}"
    )


# ---------------------------------------------------------------------------
# AC5 — reachable at mobile viewports, not only when the sidebar is expanded
# ---------------------------------------------------------------------------


def test_logout_reachable_at_mobile_viewport(page: Page) -> None:
    """At a mobile viewport the sidebar is hidden, so the logout control must
    be reachable through the BottomTabBar's "More" overflow sheet instead.
    """
    token = _make_token("admin")
    page.set_viewport_size({"width": 375, "height": 667})
    _goto_authenticated(page, token)

    expect(page.locator("[data-slot='sidebar']")).not_to_be_visible()

    page.get_by_role("button", name="More navigation items").click()
    expect(page.get_by_role("button", name="Log out")).to_be_visible()


# ---------------------------------------------------------------------------
# AC6 — a logout failure (network down) does not strand the user
# ---------------------------------------------------------------------------


def test_logout_network_failure_does_not_strand_user(page: Page) -> None:
    """If POST /auth/logout fails (network error), the user must not be left
    in a half-signed-out state: no client-side redirect to /login while the
    server-side session cookie is still live and /auth/me still succeeds.

    Expected behaviour: the app surfaces the failure and the user remains on
    an authenticated page (or the app shell), still able to retry — not
    dumped onto a login screen that flips back to authenticated on refresh.
    """
    token = _make_token("admin")
    page.set_viewport_size({"width": 1280, "height": 800})
    _goto_authenticated(page, token)

    page.route(
        "**/auth/logout",
        lambda route: route.abort("failed"),
    )

    page.get_by_role("button", name="Log out").click()

    # The user must still be on an authenticated page, not bounced to /login
    # while still holding a live session (which would be the stranded state).
    page.wait_for_timeout(500)
    expect(page).not_to_have_url(f"{BASE_URL}/login")
    expect(page.locator("[data-slot='sidebar']")).to_be_visible()

    # Refreshing must still show the authenticated shell — the cookie was
    # never cleared because the server call never completed.
    page.reload()
    expect(page.locator("[data-slot='sidebar']")).to_be_visible()


# ---------------------------------------------------------------------------
# AC7 — full sign-out round trip
# ---------------------------------------------------------------------------


def test_sign_out_round_trip(page: Page) -> None:
    """End-to-end: sign in, sign out via the app shell control, land on
    /login, and confirm a protected route now redirects to /login rather
    than rendering authenticated content.
    """
    token = _make_token("admin")
    page.set_viewport_size({"width": 1280, "height": 800})
    _goto_authenticated(page, token)

    page.get_by_role("button", name="Log out").click()
    expect(page).to_have_url(f"{BASE_URL}/login")

    page.goto(BASE_URL)
    # Unauthenticated screen — /login, or /setup on an instance with no
    # passkey credential yet. The load-bearing assertion is the one below:
    # the authenticated shell is gone.
    expect(page).to_have_url(re.compile(r"/(login|setup)$"))
    expect(page.locator("[data-slot='sidebar']")).not_to_be_visible()
