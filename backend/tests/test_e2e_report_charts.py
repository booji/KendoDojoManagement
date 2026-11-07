"""Browser (Playwright) test for #560: the Charts tab on /reports.

An Admin opens the Charts tab and sees the grade distribution. The Admin's
own Member is active and has no Promotion, so Mukyū always has a bar; other
tests share the database, so counts are not asserted here
(test_grade_distribution.py covers them). The autouse e2e cleanup in
conftest.py (#568) removes the Admin and their Member afterwards, so they do
not leak into other tests' counts.
"""

import uuid

import pytest
from playwright.sync_api import Page, expect

from app.auth.models import AccountClaims
from tests.e2e_support import complete_onboarding, login_as

BASE_URL = "http://localhost:5173"


@pytest.fixture
def admin_claims():
    return AccountClaims(
        sub=str(uuid.uuid4()),
        email=f"admin_{uuid.uuid4().hex[:6]}@dojo.test",
        role="admin",
    )


def test_admin_sees_the_grade_distribution_chart(
    page: Page, admin_claims: AccountClaims
) -> None:
    token = login_as(admin_claims)
    complete_onboarding(token)
    page.context.add_cookies(
        [{"name": "access_token", "value": token, "url": BASE_URL}]
    )

    page.goto(f"{BASE_URL}/reports")
    page.get_by_role("tab", name="Charts").click()

    expect(page.get_by_role("checkbox", name="Active", exact=True)).to_be_checked()
    expect(page.get_by_role("heading", name="Grade distribution")).to_be_visible()
    expect(page.get_by_role("heading", name="Attendance Streaks")).to_be_visible()
    expect(
        page.get_by_role("heading", name="Attendance Rate", exact=True)
    ).to_be_visible()
    expect(page.locator(".recharts-bar-rectangle").first).to_be_visible()
    expect(
        page.locator("[data-slot=chart]").get_by_text("Mukyū", exact=True)
    ).to_be_visible()


def test_admin_sees_the_headcount_over_the_range(
    page: Page, admin_claims: AccountClaims
) -> None:
    # Other tests decide whether the range holds any Session, so this checks
    # the headcount loads (a chart or its empty state), not what it counts.
    token = login_as(admin_claims)
    complete_onboarding(token)
    page.context.add_cookies(
        [{"name": "access_token", "value": token, "url": BASE_URL}]
    )

    page.goto(f"{BASE_URL}/reports")
    page.get_by_role("tab", name="Charts").click()
    charts = page.get_by_role("tabpanel", name="Charts")

    expect(charts.get_by_label("From")).not_to_have_value("")
    expect(charts.get_by_role("heading", name="Headcount per Session")).to_be_visible()
    expect(
        charts.get_by_role("table", name="Headcount per Session").or_(
            charts.get_by_text("No held Sessions in this range.")
        )
    ).to_be_attached()
    expect(charts.get_by_role("alert")).to_have_count(0)
