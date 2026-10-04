"""E2E browser tests for issue #40 — Second passkey nudge.

Acceptance criteria:
  AC1: After first passkey registration (0→1), a modal is shown explaining
       lockout risk and offering "Add another passkey" / "Maybe later".
  AC2: The modal is NOT shown on subsequent registrations (only 0→1 trigger).
  AC3: Settings > Security shows a banner ("You have 1 passkey — consider
       adding a backup") when the user's passkey count is exactly 1.
  AC4: The banner is NOT shown when the user has 2 or more passkeys.

Notes on AC1/AC2:
  WebAuthn passkey creation requires navigator.credentials.create(), a browser
  API that requires hardware or a virtual authenticator — it cannot be driven
  by Playwright in headless Chromium without CTAP2 emulation. To exercise the
  nudge modal we mock the passkey-complete API response at the network layer:
  the frontend reads show_nudge from that response and opens/suppresses the
  modal accordingly.  The mock also covers the passkeys list and security-status
  calls that follow a successful registration so the UI settles cleanly.
"""

from __future__ import annotations

import json
import uuid

import pytest
import requests
from playwright.sync_api import Page, Route, expect

from tests.e2e_support import complete_onboarding

BASE_URL = "http://localhost:5173"
API_URL = "http://localhost:8000/api"

pytestmark = pytest.mark.e2e


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _register_and_login(page: Page) -> tuple[str, str]:
    """Create a fresh test user, inject the auth cookie, return (email, token)."""
    email = f"nudge-{uuid.uuid4().hex[:8]}@dojo.test"
    resp = requests.post(
        f"{API_URL}/auth/login/test",
        json={"email": email, "role": "admin"},
    )
    resp.raise_for_status()
    token = resp.cookies["access_token"]
    page.context.add_cookies(
        [
            {
                "name": "access_token",
                "value": token,
                "domain": "localhost",
                "path": "/",
                "httpOnly": True,
                "sameSite": "Strict",
            }
        ]
    )
    complete_onboarding(token)
    return email, token


def _mock_passkey_begin(page: Page) -> None:
    """Intercept the passkey-begin call so the browser never reaches the WebAuthn prompt."""

    def handle(route: Route) -> None:
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "publicKey": {
                        "challenge": "dGVzdC1jaGFsbGVuZ2U",
                        "rp": {"name": "Kendo Dojo", "id": "localhost"},
                        "user": {
                            "id": "dXNlci1pZA",
                            "name": "test@dojo.test",
                            "displayName": "test@dojo.test",
                        },
                        "pubKeyCredParams": [{"type": "public-key", "alg": -7}],
                        "timeout": 60000,
                        "attestation": "none",
                        "excludeCredentials": [],
                        "authenticatorSelection": {
                            "residentKey": "preferred",
                            "userVerification": "preferred",
                        },
                    }
                }
            ),
        )

    page.route("**/api/auth/passkeys/register/begin", handle)


def _mock_passkey_complete(page: Page, *, show_nudge: bool) -> None:
    """Intercept the passkey-complete call, returning show_nudge as requested."""

    def handle(route: Route) -> None:
        route.fulfill(
            status=201,
            content_type="application/json",
            body=json.dumps(
                {
                    "sub": str(uuid.uuid4()),
                    "email": "test@dojo.test",
                    "role": "member",
                    "is_active": True,
                    "theme": "system",
                    "show_nudge": show_nudge,
                }
            ),
        )

    page.route("**/api/auth/passkeys/register/complete", handle)


def _mock_security_status(page: Page, passkey_count: int) -> None:
    """Intercept security-status to return a controlled passkey_count."""

    def handle(route: Route) -> None:
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"passkey_count": passkey_count}),
        )

    page.route("**/api/auth/security-status", handle)


def _mock_passkeys_list(page: Page, passkeys: list[dict]) -> None:
    """Intercept the passkeys list endpoint."""

    def handle(route: Route) -> None:
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(passkeys),
        )

    page.route("**/api/auth/passkeys", handle)


def _stub_navigator_credentials(page: Page) -> None:
    """Replace navigator.credentials.create with a stub that returns a fake credential,
    allowing the frontend's performPasskeyRegistration to proceed past the WebAuthn prompt.
    """
    page.add_init_script("""
        const fakeCredential = {
            id: "dGVzdC1jcmVkLWlk",
            rawId: new Uint8Array([116,101,115,116,45,99,114,101,100,45,105,100]).buffer,
            type: "public-key",
            response: {
                clientDataJSON: new Uint8Array([116,101,115,116]).buffer,
                attestationObject: new Uint8Array([116,101,115,116]).buffer,
                getTransports: () => [],
            },
            getClientExtensionResults: () => ({}),
        };
        Object.defineProperty(navigator, 'credentials', {
            value: {
                create: async () => fakeCredential,
                get: async () => fakeCredential,
                store: async () => {},
                preventSilentAccess: async () => {},
            },
            writable: true,
            configurable: true,
        });
    """)


# ---------------------------------------------------------------------------
# AC1 — Modal appears after first passkey registration (0 → 1)
# ---------------------------------------------------------------------------


def test_nudge_modal_shown_after_first_passkey_registration(page: Page) -> None:
    """After the first passkey is registered (show_nudge=True from the API), a nudge
    modal appears with the lockout-risk message and both action buttons.
    """
    _register_and_login(page)

    # Stub WebAuthn hardware and mock API responses
    _stub_navigator_credentials(page)
    _mock_passkey_begin(page)
    _mock_passkey_complete(page, show_nudge=True)
    # After registration, the component reloads passkeys + security-status
    _mock_passkeys_list(page, [])
    _mock_security_status(page, passkey_count=1)

    page.goto(f"{BASE_URL}/settings")

    # The Security card must be visible
    expect(page.get_by_text("Security", exact=True).first).to_be_visible()

    # Trigger passkey registration via the "Add a passkey" button
    page.get_by_role("button", name="Add a passkey").click()

    # The nudge modal should appear
    expect(page.get_by_role("dialog")).to_be_visible()
    expect(page.get_by_role("heading", name="Add a backup passkey")).to_be_visible()

    # Modal must contain lockout-risk text
    expect(page.get_by_text("locked out", exact=False)).to_be_visible()

    # Both action buttons must be present
    expect(page.get_by_role("button", name="Add another passkey")).to_be_visible()
    expect(page.get_by_role("button", name="Maybe later")).to_be_visible()


# ---------------------------------------------------------------------------
# AC2 — Modal is NOT shown after second (or later) passkey registration
# ---------------------------------------------------------------------------


def test_nudge_modal_not_shown_after_second_passkey_registration(page: Page) -> None:
    """When show_nudge=False is returned (subsequent registration), the modal must not
    appear. The Settings page remains in its normal state.
    """
    _register_and_login(page)

    _stub_navigator_credentials(page)
    _mock_passkey_begin(page)
    _mock_passkey_complete(page, show_nudge=False)
    _mock_passkeys_list(page, [])
    _mock_security_status(page, passkey_count=2)

    page.goto(f"{BASE_URL}/settings")

    expect(page.get_by_text("Security", exact=True).first).to_be_visible()

    page.get_by_role("button", name="Add a passkey").click()

    # No dialog should be visible after a non-nudge registration
    page.wait_for_timeout(800)  # allow any async state updates to settle
    expect(page.get_by_role("dialog")).not_to_be_visible()


# ---------------------------------------------------------------------------
# AC3 — Settings > Security shows a banner when passkey count is exactly 1
# ---------------------------------------------------------------------------


def test_security_settings_shows_single_passkey_banner(page: Page) -> None:
    """Settings > Security shows a non-blocking banner when the user has exactly
    1 passkey.  The banner text includes 'You have 1 passkey' and mentions a backup.
    The banner must be visible on page load without any user interaction.
    """
    _register_and_login(page)

    # Mock API: 1 passkey registered
    _mock_security_status(page, passkey_count=1)
    _mock_passkeys_list(
        page,
        [
            {
                "id": str(uuid.uuid4()),
                "label": "MacBook Touch ID",
                "aaguid": None,
                "created_at": "2026-01-01T10:00:00",
                "last_used_at": None,
            }
        ],
    )

    page.goto(f"{BASE_URL}/settings")

    # Banner is visible — role="alert" on the warning div
    banner = page.get_by_role("alert").filter(has_text="1 passkey")
    expect(banner).to_be_visible()

    # Banner text explains the backup recommendation
    expect(banner).to_contain_text("consider adding a backup")


# ---------------------------------------------------------------------------
# AC4 — Banner is NOT shown when the user has 2 or more passkeys
# ---------------------------------------------------------------------------


def test_security_settings_no_banner_when_two_or_more_passkeys(page: Page) -> None:
    """Settings > Security must NOT show the single-passkey banner when the user
    has 2 or more passkeys registered.
    """
    _register_and_login(page)

    # Mock API: 2 passkeys registered
    _mock_security_status(page, passkey_count=2)
    pk_id1 = str(uuid.uuid4())
    pk_id2 = str(uuid.uuid4())
    _mock_passkeys_list(
        page,
        [
            {
                "id": pk_id1,
                "label": "MacBook Touch ID",
                "aaguid": None,
                "created_at": "2026-01-01T10:00:00",
                "last_used_at": None,
            },
            {
                "id": pk_id2,
                "label": "iPhone Face ID",
                "aaguid": None,
                "created_at": "2026-02-01T10:00:00",
                "last_used_at": None,
            },
        ],
    )

    page.goto(f"{BASE_URL}/settings")

    # Security card must still load
    expect(page.get_by_text("Security", exact=True).first).to_be_visible()

    # The single-passkey banner must NOT be present
    expect(page.get_by_role("alert").filter(has_text="1 passkey")).not_to_be_visible()
