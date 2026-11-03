"""
E2E tests for issue #555 — dialogs ignore outside clicks; sheets do not.

An Admin half-way through Add Member who clicks the page behind the dialog
must not lose what they typed. Esc and the close button still dismiss it.
"""

from playwright.sync_api import Page, expect

from tests.e2e_support import BASE_URL, authenticate


def _open_add_member(page: Page) -> None:
    authenticate(page, "admin")
    page.goto(f"{BASE_URL}/members")
    page.get_by_role("button", name="Add member").click()
    expect(page.get_by_role("dialog")).to_be_visible()


def test_outside_click_leaves_dialog_open_with_its_input(page: Page) -> None:
    _open_add_member(page)
    page.get_by_label("First name").fill("Half Typed")

    page.mouse.click(5, 5)

    expect(page.get_by_role("dialog")).to_be_visible()
    expect(page.get_by_label("First name")).to_have_value("Half Typed")


def test_escape_still_closes_dialog(page: Page) -> None:
    _open_add_member(page)

    page.keyboard.press("Escape")

    expect(page.get_by_role("dialog")).not_to_be_visible()


def test_close_button_still_closes_dialog(page: Page) -> None:
    _open_add_member(page)

    page.get_by_role("dialog").get_by_role("button", name="Close").click()

    expect(page.get_by_role("dialog")).not_to_be_visible()


def test_more_sheet_still_closes_on_outside_click(page: Page) -> None:
    authenticate(page, "admin")
    page.set_viewport_size({"width": 375, "height": 667})
    page.goto(BASE_URL)
    page.get_by_role("button", name="More navigation items").click()
    expect(page.get_by_role("button", name="Log out")).to_be_visible()

    page.mouse.click(187, 20)

    expect(page.get_by_role("button", name="Log out")).not_to_be_visible()
