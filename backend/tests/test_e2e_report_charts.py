"""Browser (Playwright) test for #560: the Charts tab on /reports.

An Admin opens the Charts tab and sees the grade distribution. The Admin's
own Member is active and has no Promotion, so Mukyū always has a bar; other
tests share the database, so counts are not asserted here
(test_grade_distribution.py covers them). The Admin and their Member are
removed afterwards, so they do not leak into other tests' counts.
"""

import asyncio
import concurrent.futures
import os
import uuid

import asyncpg
import pytest
from playwright.sync_api import Page, expect

from app.auth.models import AccountClaims
from tests.e2e_support import complete_onboarding, login_as

BASE_URL = "http://localhost:5173"


async def _remove_account_async(email: str) -> None:
    db_url = os.environ["DATABASE_URL"].replace(
        "postgresql+asyncpg://", "postgresql://"
    )
    conn = await asyncpg.connect(db_url)
    try:
        # Accounts before the Members they belong to (accounts.member_id is
        # ON DELETE RESTRICT, #432). Auth Sessions go with the Account.
        rows = await conn.fetch("SELECT id FROM members WHERE email = $1", email)
        member_ids = [r["id"] for r in rows]
        await conn.execute(
            "DELETE FROM accounts WHERE member_id = ANY($1::uuid[])", member_ids
        )
        await conn.execute("DELETE FROM members WHERE id = ANY($1::uuid[])", member_ids)
    finally:
        await conn.close()


@pytest.fixture
def admin_claims():
    claims = AccountClaims(
        sub=str(uuid.uuid4()),
        email=f"admin_{uuid.uuid4().hex[:6]}@dojo.test",
        role="admin",
    )
    yield claims
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(lambda: asyncio.run(_remove_account_async(claims.email))).result()


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
    expect(page.locator(".recharts-bar-rectangle").first).to_be_visible()
    expect(
        page.locator("[data-slot=chart]").get_by_text("Mukyū", exact=True)
    ).to_be_visible()
