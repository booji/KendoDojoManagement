"""
E2E tests for issue #555 — the browser tab shows the dojo name.

Signed in, the tab shows the name from Dojo Settings; on the sign-in page,
the name the public branding endpoint gives. Otherwise it reads
"Kendo Dojo Management" — never Vite's "frontend" or the "My Dojo"
placeholder.
"""

import uuid

import requests
from playwright.sync_api import Page, expect

from tests.e2e_support import API_URL, BASE_URL, authenticate, make_token

FALLBACK = "Kendo Dojo Management"


def _set_dojo(token: str, **payload) -> None:
    requests.put(
        f"{API_URL}/settings/dojo", json=payload, cookies={"access_token": token}
    ).raise_for_status()


def test_sign_in_page_without_a_public_name_shows_the_fallback(page: Page) -> None:
    _set_dojo(make_token("admin"), login_show_name=False)

    page.goto(f"{BASE_URL}/login")
    page.wait_for_load_state("networkidle")

    expect(page).to_have_title(FALLBACK)


def test_sign_in_page_shows_the_public_dojo_name(page: Page) -> None:
    name = f"Title Dojo {uuid.uuid4().hex[:6]}"
    _set_dojo(make_token("admin"), dojo_name=name, login_show_name=True)

    page.goto(f"{BASE_URL}/login")

    expect(page).to_have_title(name)


def test_signed_in_tab_shows_the_dojo_settings_name(page: Page) -> None:
    # login_show_name off: the name can only come from Dojo Settings.
    token = authenticate(page, "admin")
    name = f"Title Dojo {uuid.uuid4().hex[:6]}"
    _set_dojo(token, dojo_name=name, login_show_name=False)

    page.goto(BASE_URL)

    expect(page).to_have_title(name)
