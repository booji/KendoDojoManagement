"""Browser (Playwright) test for #560: the Charts tab on /reports.

An Admin opens the Charts tab and sees the grade distribution. The Admin's
own Member is active and has no Promotion, so Mukyū always has a bar; other
tests share the database, so counts are not asserted here
(test_grade_distribution.py covers them).
"""

import uuid

from playwright.sync_api import Page, expect

from app.auth.models import AccountClaims
from tests.e2e_support import complete_onboarding, login_as

BASE_URL = "http://localhost:5173"


def test_admin_sees_the_grade_distribution_chart(page: Page) -> None:
    claims = AccountClaims(
        sub=str(uuid.uuid4()),
        email=f"admin_{uuid.uuid4().hex[:6]}@dojo.test",
        role="admin",
    )
    token = login_as(claims)
    complete_onboarding(token)
    page.context.add_cookies(
        [{"name": "access_token", "value": token, "url": BASE_URL}]
    )

    page.goto(f"{BASE_URL}/reports")
    page.get_by_role("tab", name="Charts").click()

    expect(page.get_by_role("checkbox", name="Active", exact=True)).to_be_checked()
    expect(page.get_by_role("heading", name="Grade distribution")).to_be_visible()
    expect(page.locator(".recharts-bar-rectangle").first).to_be_visible()
    expect(
        page.locator("[data-slot=chart]").get_by_text("Mukyū", exact=True)
    ).to_be_visible()
