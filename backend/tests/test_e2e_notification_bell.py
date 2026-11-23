"""
E2E (Playwright) tests for issue #611 — the notification bell.

The bell lists what is waiting for the user's action, derived live from
GET /grades/pending. Other tests leave pending Grades behind, so these assert
on this test's own Member rather than on an exact count.
"""

from __future__ import annotations

import re
import uuid

import requests
from playwright.sync_api import Page, expect

from tests.test_e2e_grade_approval import (
    API_BASE,
    BASE_URL,
    _cookie_dict,
    _inject_cookie,
    _make_token,
    _setup_pending_grade,
)

BELL = re.compile(r"^Notifications, \d+ pending$")


def test_admin_bell_lists_pending_grade_and_drops_it_once_approved(
    page: Page,
) -> None:
    name = f"Bell {uuid.uuid4().hex[:6]}"
    admin_token, member_id, entry_id = _setup_pending_grade(f"{name} Member")

    _inject_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/")

    page.get_by_role("button", name=BELL).click()
    item = page.get_by_role("link", name=re.compile(name))
    expect(item).to_have_attribute("href", "/admin/settings/grades")

    requests.post(
        f"{API_BASE}/members/{member_id}/grades/{entry_id}/approve",
        cookies=_cookie_dict(admin_token),
    ).raise_for_status()

    # A route change refreshes the bell.
    page.keyboard.press("Escape")
    page.get_by_role("link", name="Members").first.click()
    page.get_by_role("button", name=re.compile(r"^Notifications")).click()
    expect(page.get_by_role("link", name=re.compile(name))).to_have_count(0)


def test_admin_bell_sits_in_mobile_top_bar(page: Page) -> None:
    admin_token, _member_id, _entry_id = _setup_pending_grade("Mobile Bell Member")

    page.set_viewport_size({"width": 390, "height": 844})
    _inject_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/")

    expect(page.locator("header").get_by_role("button", name=BELL)).to_be_visible()


def test_member_sees_no_bell(page: Page) -> None:
    _inject_cookie(page, _make_token("member"))
    page.goto(f"{BASE_URL}/")

    expect(page.get_by_role("link", name="Sessions").first).to_be_visible()
    expect(
        page.get_by_role("button", name=re.compile(r"^Notifications"))
    ).to_have_count(0)
