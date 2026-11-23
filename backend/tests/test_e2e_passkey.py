"""E2E tests for passkey UI visibility on the register and login pages."""

import json

import pytest
from playwright.sync_api import Page, Route, expect

from tests.e2e_support import authenticate

BASE_URL = "http://localhost:5173"


def test_e2e_register_page_asks_for_an_invite(page: Page) -> None:
    """Members join by invite only (#472): /register offers no registration
    and tells the visitor to ask their dojo for an invite."""
    page.goto(f"{BASE_URL}/register")
    expect(page.get_by_text("ask your dojo for an invite")).to_be_visible()
    expect(page.get_by_role("button", name="Register with passkey")).to_have_count(0)
    expect(page.locator("input[type='email']")).to_have_count(0)


def test_e2e_passkey_login_button_visible(page: Page) -> None:
    """Login page should show a passkey option as the primary action."""
    page.goto(f"{BASE_URL}/login")
    expect(page.get_by_role("button", name="Sign in with passkey")).to_be_visible()


def test_e2e_login_page_explains_signing_in_from_a_phone(page: Page) -> None:
    """A Member whose passkey is on their phone is told to use the browser's
    phone-or-tablet option and scan the QR code (#612)."""
    page.goto(f"{BASE_URL}/login")
    expect(page.get_by_text("Your passkey is on your phone?")).to_be_visible()


# ── Offer a passkey for this device after a cross-device sign-in (#612) ──────
#
# No virtual authenticator here (see test_e2e_invites.py), so the ceremony is
# stubbed: navigator.credentials.get returns a credential reporting the given
# authenticatorAttachment, and the login endpoints are fulfilled at the
# network layer. The session itself is a real cookie from the test login.


def _sign_in_with_attachment(page: Page, attachment: str | None) -> None:
    attachment_js = json.dumps(attachment)
    page.add_init_script(f"""
        const buf = () => new Uint8Array([1, 2, 3]).buffer;
        const cred = {{
            id: "Y3JlZA", rawId: buf(), type: "public-key",
            response: {{ clientDataJSON: buf(), authenticatorData: buf(), signature: buf() }},
            getClientExtensionResults: () => ({{}}),
        }};
        const attachment = {attachment_js};
        if (attachment !== null) cred.authenticatorAttachment = attachment;
        Object.defineProperty(navigator, "credentials", {{
            value: {{ get: async () => cred, create: async () => cred }},
            configurable: true,
        }});
    """)

    def fulfil(body: dict) -> object:
        def handle(route: Route) -> None:
            route.fulfill(
                status=200, content_type="application/json", body=json.dumps(body)
            )

        return handle

    page.route(
        "**/api/auth/login/passkey/begin",
        fulfil({"publicKey": {"challenge": "AQID", "userVerification": "required"}}),
    )
    page.route("**/api/auth/login/passkey/complete", fulfil({"detail": "ok"}))

    page.goto(f"{BASE_URL}/login")
    page.get_by_label("Email").fill("member@dojo.test")
    page.get_by_role("button", name="Sign in with passkey").click()
    page.wait_for_url(f"{BASE_URL}/")


def _expect_no_device_prompt(page: Page) -> None:
    # The shell is up, so the prompt would have rendered by now. (An open
    # modal hides the shell from role queries, so this also fails if it did.)
    expect(page.get_by_role("link", name="Sessions").first).to_be_visible()
    expect(_device_prompt(page)).to_have_count(0)


def _device_prompt(page: Page):
    return page.get_by_role("dialog", name="Add a passkey on this device?")


def test_e2e_cross_platform_sign_in_offers_a_passkey_for_this_device(
    page: Page,
) -> None:
    authenticate(page, role="member")
    _sign_in_with_attachment(page, "cross-platform")
    expect(_device_prompt(page)).to_be_visible()
    expect(page.get_by_role("button", name="Add passkey")).to_be_visible()


@pytest.mark.parametrize("attachment", ["platform", None])
def test_e2e_no_device_passkey_offer_without_cross_platform(
    page: Page, attachment: str | None
) -> None:
    """A platform sign-in, or a browser that omits authenticatorAttachment,
    gets no prompt."""
    authenticate(page, role="member")
    _sign_in_with_attachment(page, attachment)
    _expect_no_device_prompt(page)


def test_e2e_dismissed_device_passkey_offer_stays_dismissed(page: Page) -> None:
    authenticate(page, role="member")
    _sign_in_with_attachment(page, "cross-platform")
    page.get_by_role("button", name="Not now").click()
    expect(_device_prompt(page)).to_have_count(0)

    page.unroute("**/api/auth/login/passkey/**")
    _sign_in_with_attachment(page, "cross-platform")
    _expect_no_device_prompt(page)
