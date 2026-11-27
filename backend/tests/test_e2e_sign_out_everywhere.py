"""E2e for #487: "Sign out everywhere" on the user's own Settings page.

One Account, two signed-in devices: signing out everywhere from one ends both,
and the browser that asked lands on /login.
"""

import uuid

import pytest
import requests
from playwright.sync_api import Page, expect

from app.auth.schemas import AccountClaims
from tests.e2e_support import API_URL, BASE_URL, complete_onboarding, login_as


def _me_status(token: str) -> int:
    return requests.get(
        f"{API_URL}/auth/me", cookies={"access_token": token}
    ).status_code


def _on_settings(page: Page, width: int = 1280) -> AccountClaims:
    """Sign a new Member in, in this browser, and open their Settings page."""
    claims = AccountClaims(
        sub=str(uuid.uuid4()),
        email=f"everywhere-{uuid.uuid4().hex[:6]}@dojo.test",
        role="member",
    )
    token = login_as(claims)
    complete_onboarding(token)
    page.set_viewport_size({"width": width, "height": 800})
    page.context.add_cookies(
        [{"name": "access_token", "value": token, "url": BASE_URL}]
    )
    page.goto(f"{BASE_URL}/settings")
    page.get_by_role("button", name="Sign out everywhere").click()
    return claims


def _this_device(page: Page) -> str:
    return next(
        c["value"] for c in page.context.cookies() if c["name"] == "access_token"
    )


@pytest.mark.parametrize("width", [375, 1280])
def test_sign_out_everywhere_ends_every_device(page: Page, width: int) -> None:
    claims = _on_settings(page, width)
    this_device = _this_device(page)
    other_device = login_as(claims)
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_role("button", name="Cancel")).to_be_focused()

    dialog.get_by_role("button", name="Sign out everywhere").click()

    expect(page).to_have_url(f"{BASE_URL}/login")
    assert _me_status(this_device) == 401
    assert _me_status(other_device) == 401


def test_cancelling_keeps_the_user_signed_in(page: Page) -> None:
    _on_settings(page)

    page.get_by_role("dialog").get_by_role("button", name="Cancel").click()

    expect(page.get_by_role("dialog")).to_be_hidden()
    expect(page).to_have_url(f"{BASE_URL}/settings")
    assert _me_status(_this_device(page)) == 200


def test_a_failed_sign_out_leaves_the_user_where_they_are(page: Page) -> None:
    """Nothing was signed out, so landing on /login would strand a user who is
    in fact still signed in. They stay put and see why."""
    page.route("**/api/auth/sign-out-everywhere", lambda route: route.abort())
    _on_settings(page)
    dialog = page.get_by_role("dialog")

    dialog.get_by_role("button", name="Sign out everywhere").click()

    expect(dialog.get_by_role("alert")).to_be_visible()
    expect(page).to_have_url(f"{BASE_URL}/settings")
    assert _me_status(_this_device(page)) == 200
