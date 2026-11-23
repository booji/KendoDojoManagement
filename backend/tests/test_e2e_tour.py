"""Browser (Playwright) tests for #609: the guided tour.

Each role's test walks the whole tour on a desktop viewport and fails if a
step's target is missing. driver.js shows a step whose element it cannot find
as a centred popover over a dummy element, which would otherwise break a step
silently, so every step but the deliberately targetless ones must highlight a
real element.

Every other e2e test runs with the tour marked as seen (conftest.py); these
opt out with the ``tour`` marker.
"""

import uuid

import pytest
import requests
from playwright.sync_api import Page, Route, expect

from tests.e2e_support import API_URL, authenticate

BASE_URL = "http://localhost:5173"

pytestmark = pytest.mark.tour

# (title, has a target). A Member has no Grades page, so that step is a
# centred note; the Admin's points at the Grades sub-page of Admin Settings.
MEMBER_STEPS = [
    ("Dashboard", True),
    ("Sessions", True),
    ("Calendar feed", True),
    ("My Attendance", True),
    ("Grades", False),
    ("Settings", True),
]
ADMIN_STEPS = [
    ("Dashboard", True),
    ("Sessions", True),
    ("Calendar feed", True),
    ("My Attendance", True),
    ("Grades", True),
    ("Settings", True),
    ("Create a Session or Series", True),
    ("Members", True),
    ("Reports", True),
    ("Admin Settings", True),
]

DESKTOP = {"width": 1280, "height": 800}


def _popover_title(page: Page):
    return page.locator(".driver-popover-title")


def _walk(page: Page, steps: list[tuple[str, bool]]) -> None:
    for i, (title, has_target) in enumerate(steps):
        expect(_popover_title(page)).to_have_text(title)
        active = page.locator(".driver-active-element")
        expect(active).to_have_count(1)
        if has_target:
            assert active.get_attribute("id") != "driver-dummy-element", (
                f"step {i + 1} ({title}) lost its target"
            )
        page.locator(".driver-popover-next-btn").click()
    expect(page.locator(".driver-popover")).to_have_count(0)


def _seen(page: Page) -> str | None:
    return page.evaluate("() => localStorage.getItem('tour_seen')")


def test_member_first_sign_in_walks_the_member_tour(page: Page) -> None:
    page.set_viewport_size(DESKTOP)
    authenticate(page, "member")
    page.goto(BASE_URL)

    _walk(page, MEMBER_STEPS)

    assert _seen(page) == "1"
    page.goto(BASE_URL)
    expect(page.get_by_role("link", name="Sessions").first).to_be_visible()
    page.wait_for_timeout(500)
    expect(page.locator(".driver-popover")).to_have_count(0)


def test_admin_walks_member_and_admin_steps_under_the_production_csp(
    page: Page,
) -> None:
    # Same harness as test_e2e_report_charts.py (#607): Vite's own preamble
    # and injected <style>s get a nonce; anything the tour injects does not,
    # so it is blocked exactly as in production.
    nonce = uuid.uuid4().hex
    csp = (
        requests.get(API_URL).headers["Content-Security-Policy"]
        + f"; script-src 'self' 'nonce-{nonce}'; style-src 'self' 'nonce-{nonce}'"
    )

    def with_csp(route: Route) -> None:
        response = route.fetch()
        html = response.text().replace("<script", f'<script nonce="{nonce}"')
        html = html.replace(
            "<head>", f'<head><meta property="csp-nonce" nonce="{nonce}">', 1
        )
        headers = {k: v for k, v in response.headers.items() if k != "content-length"}
        route.fulfill(
            response=response,
            body=html,
            headers={**headers, "content-security-policy": csp},
        )

    page.route(f"{BASE_URL}/", with_csp)
    page.add_init_script(
        """
        window.__cspViolations = [];
        document.addEventListener("securitypolicyviolation", (e) => {
          window.__cspViolations.push(`${e.effectiveDirective} ${e.sourceFile}`);
        });
        """
    )
    page.set_viewport_size(DESKTOP)
    authenticate(page, "admin")
    page.goto(f"{BASE_URL}/")

    _walk(page, ADMIN_STEPS)

    assert page.evaluate("() => window.__cspViolations") == []


def test_skipping_ends_the_tour_and_settings_replays_it(page: Page) -> None:
    page.set_viewport_size(DESKTOP)
    authenticate(page, "member")
    page.goto(BASE_URL)
    expect(_popover_title(page)).to_have_text("Dashboard")

    page.locator(".driver-popover-close-btn").click()
    expect(page.locator(".driver-popover")).to_have_count(0)
    assert _seen(page) == "1"

    page.goto(f"{BASE_URL}/settings")
    page.get_by_role("button", name="Take the tour").click()
    expect(_popover_title(page)).to_have_text("Dashboard")


def test_on_mobile_a_nav_item_step_is_a_centred_popover(page: Page) -> None:
    page.set_viewport_size({"width": 375, "height": 740})
    authenticate(page, "member")
    page.goto(BASE_URL)

    expect(_popover_title(page)).to_have_text("Dashboard")
    expect(page.locator("#driver-dummy-element")).to_have_count(1)


def test_tour_waits_for_the_device_passkey_offer(page: Page) -> None:
    # #612's dialog after a cross-device sign-in must not stack with the tour.
    page.set_viewport_size(DESKTOP)
    authenticate(page, "member")
    page.goto(BASE_URL)
    page.evaluate("() => sessionStorage.setItem('device_passkey_offer', '1')")
    page.reload()

    dialog = page.get_by_role("dialog", name="Add a passkey on this device?")
    expect(dialog).to_be_visible()
    page.wait_for_timeout(500)
    expect(page.locator(".driver-popover")).to_have_count(0)

    dialog.get_by_role("button", name="Not now").click()
    expect(_popover_title(page)).to_have_text("Dashboard")
