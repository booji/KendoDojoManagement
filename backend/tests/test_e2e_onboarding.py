"""
Browser (Playwright) e2e tests for issue #160 — onboarding page and profile gate.

ACs covered (AC5, "no member record", went with #432: every Account belongs to
a Member, so there is always a record and the gate is about its fields):
  AC6: Authenticated user with incomplete member record (missing first_name/
       surname/dob) is redirected to /onboarding.
  AC7: Authenticated user with complete profile is NOT redirected.
  AC8: /onboarding route is accessible without a complete profile (not self-blocking).
  AC9: After successful onboarding submit, user lands on /.
"""

from __future__ import annotations

import uuid

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


def _complete_profile(token: str) -> None:
    """Give the caller's Member the date of birth onboarding asks for."""
    resp = requests.put(
        f"{API_URL}/users/me/member",
        json={"dob": "1990-06-15"},
        cookies={"access_token": token},
        timeout=5,
    )
    assert resp.ok, f"profile update failed: {resp.status_code} {resp.text}"


# ---------------------------------------------------------------------------
# AC6 — Incomplete member record → redirect to /onboarding
# ---------------------------------------------------------------------------


def test_incomplete_member_record_redirects_to_onboarding(page: Page) -> None:
    """AC6: authenticated user whose member record is missing dob is redirected
    to /onboarding."""
    _ensure_seeded()
    email = f"e2e_ac6_{uuid.uuid4().hex[:8]}@dojo.test"
    # Test login creates the Member with a name but no date of birth, which is
    # what a newly invited or newly claimed Account starts with (#432).
    token, _user_id = _test_login(email)
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
    token, _user_id = _test_login(email)
    _complete_profile(token)
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
    # The Member has no date of birth yet — profile is incomplete
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
    # The Member has no date of birth yet — will trigger onboarding
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
