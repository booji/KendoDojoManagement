"""
E2E (Playwright) tests for issue #146 — Admin approve/reject pending grade submissions.

Acceptance criteria covered:
  AC6 — Admin sees approve/reject buttons on pending entries in member detail page
  AC7 — Clicking approve updates grade card without page reload
  AC8 — Clicking reject removes entry from history without page reload
"""

from __future__ import annotations

import os
import uuid

import requests
from dotenv import load_dotenv
from playwright.sync_api import Page, expect

_dotenv_path = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path=_dotenv_path, override=False)
os.environ.setdefault("JWT_SECRET", "test-secret-not-for-production")

from app import config as _config  # noqa: E402
from app.auth.models import UserClaims  # noqa: E402
from app.auth.token import encode_token  # noqa: E402

_config.JWT_SECRET = os.environ["JWT_SECRET"]

BASE_URL = "http://localhost:5173"
API_BASE = "http://localhost:8000"


def _make_token(role: str, sub: str | None = None) -> str:
    claims = UserClaims(
        sub=sub or str(uuid.uuid4()),
        email=f"{role}_{uuid.uuid4().hex[:6]}@dojo.test",
        role=role,  # type: ignore[arg-type]
        is_active=True,
    )
    return encode_token(claims)


def _cookie_dict(token: str) -> dict:
    return {"access_token": token}


def _inject_cookie(page: Page, token: str) -> None:
    page.context.add_cookies(
        [{"name": "access_token", "value": token, "url": BASE_URL}]
    )


def _create_member_via_api(admin_token: str, full_name: str) -> str:
    """Create a member via admin API and return the member ID."""
    r = requests.post(
        f"{API_BASE}/members",
        cookies=_cookie_dict(admin_token),
        json={
            "email": f"member-{uuid.uuid4().hex[:8]}@dojo.test",
            "full_name": full_name,
            "dob": "1990-01-01",
            "join_date": "2024-01-01",
            "membership_status": "active",
            "is_coach": False,
            "is_first_aider": False,
            "parental_consent_obtained": False,
        },
    )
    r.raise_for_status()
    return r.json()["id"]


def _create_linked_member_via_api(member_token: str, full_name: str) -> str:
    """Create a member record linked to the member token's sub via PUT /users/me/member."""
    r = requests.put(
        f"{API_BASE}/users/me/member",
        cookies=_cookie_dict(member_token),
        json={"full_name": full_name},
    )
    r.raise_for_status()
    return r.json()["id"]


def _propose_grade_via_api(member_token: str, member_id: str, grade: str = "ROKKYUU") -> str:
    """Submit a grade proposal as the member and return the entry ID."""
    r = requests.post(
        f"{API_BASE}/members/{member_id}/grades/propose",
        cookies=_cookie_dict(member_token),
        json={"grade": grade},
    )
    r.raise_for_status()
    return r.json()["id"]


def _setup_pending_grade(full_name: str) -> tuple[str, str, str]:
    """
    Create a member with a pending grade proposal.

    Returns (admin_token, member_id, entry_id).
    """
    admin_token = _make_token("admin")
    member_sub = str(uuid.uuid4())
    member_token = _make_token("member", sub=member_sub)

    # Create a member record linked to member_sub via self-service endpoint
    member_id = _create_linked_member_via_api(member_token, full_name)

    # Propose a grade as the member
    entry_id = _propose_grade_via_api(member_token, member_id)

    return admin_token, member_id, entry_id


# ---------------------------------------------------------------------------
# AC6 — Admin view shows approve/reject buttons on pending entries
# ---------------------------------------------------------------------------


def test_admin_sees_approve_and_reject_buttons_on_pending_entry(page: Page) -> None:
    """Admin member-detail view: pending grade entries show Approve and Reject buttons."""
    admin_token, member_id, _entry_id = _setup_pending_grade("AC6 Pending Grade Member")

    _inject_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/members/{member_id}")
    page.wait_for_load_state("networkidle")

    # Expand grade history
    toggle = page.locator("button", has_text="grade history")
    expect(toggle).to_be_visible(timeout=8000)
    toggle.click()

    # The history list should appear
    expect(page.locator("#grade-history-list")).to_be_visible(timeout=5000)

    # Approve and Reject buttons must be visible for the pending entry
    approve_btn = page.get_by_role("button", name=lambda n: "Approve" in n if n else False).first
    # Use aria-label pattern from the implementation: "Approve {display_name}"
    approve_btn = page.locator('button[aria-label^="Approve"]').first
    reject_btn = page.locator('button[aria-label^="Reject"]').first

    expect(approve_btn).to_be_visible(timeout=5000)
    expect(reject_btn).to_be_visible(timeout=5000)


# ---------------------------------------------------------------------------
# AC7 — Clicking approve updates grade card without page reload
# ---------------------------------------------------------------------------


def test_approve_updates_grade_card_without_reload(page: Page) -> None:
    """Clicking Approve on a pending entry updates the member's grade card in place."""
    admin_token, member_id, _entry_id = _setup_pending_grade("AC7 Approve Grade Member")

    _inject_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/members/{member_id}")
    page.wait_for_load_state("networkidle")

    # Plant a sentinel to detect page reloads
    page.evaluate("window.__noReload = true")

    # Expand grade history
    toggle = page.locator("button", has_text="grade history")
    expect(toggle).to_be_visible(timeout=8000)
    toggle.click()
    expect(page.locator("#grade-history-list")).to_be_visible(timeout=5000)

    # Confirm "awaiting confirmation" badge is visible before approving
    expect(page.locator("text=awaiting confirmation")).to_be_visible(timeout=5000)

    # Click Approve
    approve_btn = page.locator('button[aria-label^="Approve"]').first
    expect(approve_btn).to_be_visible(timeout=5000)
    approve_btn.click()

    # The "awaiting confirmation" badge must disappear without a full page reload
    expect(page.locator("text=awaiting confirmation")).not_to_be_visible(timeout=8000)

    # Confirm no page reload occurred
    sentinel = page.evaluate("window.__noReload")
    assert sentinel is True, "Page was reloaded — approval must update in place"


# ---------------------------------------------------------------------------
# AC8 — Clicking reject removes entry from history without page reload
# ---------------------------------------------------------------------------


def test_reject_removes_entry_from_history_without_reload(page: Page) -> None:
    """Clicking Reject on a pending entry removes it from the history list in place."""
    admin_token, member_id, _entry_id = _setup_pending_grade("AC8 Reject Grade Member")

    _inject_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/members/{member_id}")
    page.wait_for_load_state("networkidle")

    # Plant a sentinel to detect page reloads
    page.evaluate("window.__noReload = true")

    # Expand grade history
    toggle = page.locator("button", has_text="grade history")
    expect(toggle).to_be_visible(timeout=8000)
    toggle.click()
    expect(page.locator("#grade-history-list")).to_be_visible(timeout=5000)

    # Record the entry count before rejecting
    entries_before = page.locator("#grade-history-list li").count()
    assert entries_before >= 1, "Expected at least one history entry before rejection"

    # Click Reject
    reject_btn = page.locator('button[aria-label^="Reject"]').first
    expect(reject_btn).to_be_visible(timeout=5000)
    reject_btn.click()

    # The entry must disappear from the list without a full page reload
    entries_after_locator = page.locator("#grade-history-list li")
    # Wait for the count to drop
    page.wait_for_function(
        f"document.querySelectorAll('#grade-history-list li').length < {entries_before}",
        timeout=8000,
    )

    entries_after = entries_after_locator.count()
    assert entries_after < entries_before, (
        f"Expected fewer history entries after rejection, got {entries_after} (was {entries_before})"
    )

    # Confirm no page reload occurred
    sentinel = page.evaluate("window.__noReload")
    assert sentinel is True, "Page was reloaded — rejection must update in place"
