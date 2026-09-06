"""
Browser (Playwright) e2e tests for issue #160 — onboarding page and profile gate.

ACs covered:
  AC5: Authenticated user with no member record is redirected to /onboarding
       from protected routes.
  AC6: Authenticated user with incomplete member record (missing first_name/
       surname/dob) is redirected to /onboarding.
  AC7: Authenticated user with complete profile is NOT redirected.
  AC8: /onboarding route is accessible without a complete profile (not self-blocking).
  AC9: After successful onboarding submit, user lands on /.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import os
import uuid

import asyncpg
import requests
from playwright.sync_api import Page, expect

BASE_URL = "http://localhost:5173"
API_URL = "http://localhost:8000/api"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _test_login(email: str, role: str = "member") -> tuple[str, str]:
    """Create-or-get a user via the test-login endpoint.

    Returns (token_value, user_id).
    """
    resp = requests.post(
        f"{API_URL}/auth/login/test",
        json={"email": email, "role": role},
        timeout=5,
    )
    assert resp.ok, f"test login failed: {resp.status_code} {resp.text}"
    token = resp.cookies["access_token"]
    user_id = resp.json()["sub"]
    return token, user_id


def _inject_cookie(page: Page, token: str) -> None:
    """Inject the access_token cookie into the Playwright browser context."""
    page.context.add_cookies(
        [{"name": "access_token", "value": token, "url": BASE_URL}]
    )


def _ensure_seeded() -> None:
    """Ensure at least one user exists so the backend treats the instance as populated.

    Without at least one user the frontend redirects unauthenticated visitors
    to /setup instead of /login, which breaks protected-route assertions.
    """
    _test_login(f"e2e_onboard_seed_{uuid.uuid4().hex[:8]}@dojo.test", "admin")


def _insert_incomplete_member(user_id: str) -> None:
    """Insert a member row with no dob, linked to user_id, via asyncpg.

    The member has first_name + surname but dob=NULL — this makes
    RequireProfile's ``!member.dob`` check truthy → redirect to /onboarding.
    """
    db_url = os.environ["DATABASE_URL"].replace(
        "postgresql+asyncpg://", "postgresql://"
    )

    async def _insert() -> None:
        conn = await asyncpg.connect(db_url)
        try:
            member_id = str(uuid.uuid4())
            email = f"incomplete_{uuid.uuid4().hex[:8]}@dojo.test"
            await conn.execute(
                """
                INSERT INTO members
                    (id, email, first_name, surname, dob,
                     join_date, membership_status,
                     is_coach, is_first_aider, user_id)
                VALUES
                    ($1, $2, $3, $4, NULL,
                     '2024-01-01', 'active',
                     FALSE, FALSE, $5)
                """,
                member_id,
                email,
                "Incomplete",
                "Member",
                user_id,
            )
        finally:
            await conn.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(lambda: asyncio.run(_insert())).result()


def _insert_complete_member(user_id: str, email: str) -> None:
    """Insert a fully-complete member row linked to user_id via asyncpg."""
    db_url = os.environ["DATABASE_URL"].replace(
        "postgresql+asyncpg://", "postgresql://"
    )

    async def _insert() -> None:
        conn = await asyncpg.connect(db_url)
        try:
            member_id = str(uuid.uuid4())
            await conn.execute(
                """
                INSERT INTO members
                    (id, email, first_name, surname, dob,
                     join_date, membership_status,
                     is_coach, is_first_aider, user_id)
                VALUES
                    ($1, $2, $3, $4, $5,
                     '2024-01-01', 'active',
                     FALSE, FALSE, $6)
                """,
                member_id,
                email,
                "Complete",
                "Member",
                "1990-06-15",
                user_id,
            )
        finally:
            await conn.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(lambda: asyncio.run(_insert())).result()


# ---------------------------------------------------------------------------
# AC5 — No member record → redirect to /onboarding
# ---------------------------------------------------------------------------


def test_no_member_record_redirects_to_onboarding(page: Page) -> None:
    """AC5: authenticated user with no member record is redirected to /onboarding
    when accessing a protected route (/)."""
    _ensure_seeded()
    email = f"e2e_ac5_{uuid.uuid4().hex[:8]}@dojo.test"
    token, _user_id = _test_login(email)
    _inject_cookie(page, token)

    page.goto(f"{BASE_URL}/")
    expect(page).to_have_url(f"{BASE_URL}/onboarding", timeout=8000)


# ---------------------------------------------------------------------------
# AC6 — Incomplete member record → redirect to /onboarding
# ---------------------------------------------------------------------------


def test_incomplete_member_record_redirects_to_onboarding(page: Page) -> None:
    """AC6: authenticated user whose member record is missing dob is redirected
    to /onboarding."""
    _ensure_seeded()
    email = f"e2e_ac6_{uuid.uuid4().hex[:8]}@dojo.test"
    token, user_id = _test_login(email)
    _insert_incomplete_member(user_id)
    _inject_cookie(page, token)

    page.goto(f"{BASE_URL}/")
    expect(page).to_have_url(f"{BASE_URL}/onboarding", timeout=8000)


# ---------------------------------------------------------------------------
# AC7 — Complete profile → NOT redirected to /onboarding
# ---------------------------------------------------------------------------


def test_complete_profile_not_redirected(page: Page) -> None:
    """AC7: authenticated user with a complete member profile (first_name + surname
    + dob all present) is NOT redirected to /onboarding."""
    _ensure_seeded()
    email = f"e2e_ac7_{uuid.uuid4().hex[:8]}@dojo.test"
    token, user_id = _test_login(email)
    _insert_complete_member(user_id, email)
    _inject_cookie(page, token)

    page.goto(f"{BASE_URL}/")
    page.wait_for_load_state("networkidle")
    # Must remain on / (or some non-onboarding protected route), not /onboarding
    expect(page).not_to_have_url(f"{BASE_URL}/onboarding", timeout=8000)


# ---------------------------------------------------------------------------
# AC8 — /onboarding accessible without complete profile (no redirect loop)
# ---------------------------------------------------------------------------


def test_onboarding_route_accessible_without_complete_profile(page: Page) -> None:
    """AC8: /onboarding is itself accessible when the member profile is incomplete —
    the gate must not redirect /onboarding back to /onboarding (infinite loop)."""
    _ensure_seeded()
    email = f"e2e_ac8_{uuid.uuid4().hex[:8]}@dojo.test"
    token, _user_id = _test_login(email)
    # No member record — profile is incomplete
    _inject_cookie(page, token)

    page.goto(f"{BASE_URL}/onboarding")
    # Page must load and show the form, not redirect away or loop
    expect(page).to_have_url(f"{BASE_URL}/onboarding", timeout=8000)
    expect(page.get_by_text("Complete your profile")).to_be_visible(timeout=8000)


# ---------------------------------------------------------------------------
# AC9 — Successful onboarding submit lands on /
# ---------------------------------------------------------------------------


def test_successful_onboarding_submit_lands_on_home(page: Page) -> None:
    """AC9: after filling in and submitting the onboarding form successfully,
    the user is navigated to / (the home/dashboard page)."""
    _ensure_seeded()
    email = f"e2e_ac9_{uuid.uuid4().hex[:8]}@dojo.test"
    token, _user_id = _test_login(email)
    # No member record — will trigger onboarding
    _inject_cookie(page, token)

    page.goto(f"{BASE_URL}/onboarding")
    expect(page).to_have_url(f"{BASE_URL}/onboarding", timeout=8000)

    # Fill required fields
    page.get_by_label("First name", exact=False).fill("Jane")
    page.get_by_label("Surname", exact=False).fill("Smith")
    page.get_by_label("Date of birth", exact=False).fill("1990-06-15")

    page.get_by_role("button", name="Save and continue").click()

    # After successful submit, user should land on /
    expect(page).to_have_url(f"{BASE_URL}/", timeout=10000)
