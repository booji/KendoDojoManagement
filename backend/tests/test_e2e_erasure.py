"""
Playwright browser tests for issue #229 — GDPR erasure UI.

Auth pattern: synthetic JWT tokens injected as cookies (same as
test_e2e_members.py / test_e2e_attendance_admin.py). No real user
registration required.

Acceptance criteria covered, one test each:
  1. "Delete permanently" affordance only visible when member is Archived.
  2. Typed-name confirmation is required before the erase action is enabled.
  3. After erasing, the member displays as "Deleted member".
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
from app.auth.models import AccountClaims  # noqa: E402
from app.auth.token import encode_token  # noqa: E402
from tests.e2e_support import complete_onboarding  # noqa: E402

_config.JWT_SECRET = os.environ["JWT_SECRET"]

BASE_URL = "http://localhost:5173"
API_BASE = "http://localhost:8000/api"


def _make_token(role: str, sub: str | None = None) -> str:
    claims = AccountClaims(
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


def _ensure_admin_profile(admin_token: str) -> None:
    """Give the admin a complete own-member record.

    RequireProfile (frontend App.tsx) redirects any authenticated user whose
    own member record is incomplete to /onboarding — including admins.
    Synthetic admin tokens have no Account behind them, so tests that navigate
    to admin-gated pages make one (with its Member) first.
    """
    complete_onboarding(
        admin_token, first_name="Admin", surname="Test", dob="1980-01-01"
    )


def _create_member_via_api(
    admin_token: str,
    first_name: str,
    surname: str,
    *,
    membership_status: str = "active",
    email: str | None = None,
) -> str:
    r = requests.post(
        f"{API_BASE}/members",
        cookies=_cookie_dict(admin_token),
        json={
            "email": email or f"member-{uuid.uuid4().hex[:8]}@dojo.test",
            "first_name": first_name,
            "surname": surname,
            "dob": "1990-01-01",
            "join_date": "2024-01-01",
            "membership_status": membership_status,
            "is_coach": False,
            "is_first_aider": False,
        },
    )
    r.raise_for_status()
    return r.json()["id"]


def _archive_member_via_api(admin_token: str, member_id: str) -> None:
    r = requests.put(
        f"{API_BASE}/members/{member_id}",
        cookies=_cookie_dict(admin_token),
        json={"membership_status": "archived"},
    )
    r.raise_for_status()


# ---------------------------------------------------------------------------
# AC1 — "Delete permanently" only visible once the member is Archived
# ---------------------------------------------------------------------------


def test_delete_permanently_only_visible_when_archived(page: Page) -> None:
    admin_token = _make_token("admin")
    _ensure_admin_profile(admin_token)
    suffix = uuid.uuid4().hex[:8]
    full_name = f"Erasure ActiveTest{suffix}"
    member_id = _create_member_via_api(
        admin_token, "Erasure", f"ActiveTest{suffix}", membership_status="active"
    )
    _inject_cookie(page, admin_token)

    # The delete button's accessible name is "Delete {full name} permanently"
    # (see MemberDetailPage.tsx aria-label), so match on that exact label
    # rather than a substring of the visible "Delete permanently" text.
    delete_button = page.get_by_role("button", name=f"Delete {full_name} permanently")

    page.goto(f"{BASE_URL}/members/{member_id}")
    page.wait_for_load_state("networkidle")
    expect(delete_button).not_to_be_visible()

    _archive_member_via_api(admin_token, member_id)
    page.reload()
    page.wait_for_load_state("networkidle")
    expect(delete_button).to_be_visible(timeout=8000)


# ---------------------------------------------------------------------------
# AC2 — Typed-name confirmation gates the erase action
# ---------------------------------------------------------------------------


def test_erase_requires_typed_name_confirmation(page: Page) -> None:
    admin_token = _make_token("admin")
    _ensure_admin_profile(admin_token)
    suffix = uuid.uuid4().hex[:8]
    full_name = f"Erasure ConfirmTest{suffix}"
    member_id = _create_member_via_api(
        admin_token, "Erasure", f"ConfirmTest{suffix}", membership_status="archived"
    )
    _inject_cookie(page, admin_token)

    page.goto(f"{BASE_URL}/members/{member_id}")
    page.wait_for_load_state("networkidle")
    page.get_by_role("button", name=f"Delete {full_name} permanently").click()

    confirm_button = page.get_by_role(
        "button", name="Confirm delete member permanently"
    )
    expect(confirm_button).to_be_disabled()

    page.get_by_label("Type the member's name to confirm").fill(full_name)
    expect(confirm_button).to_be_enabled()


# ---------------------------------------------------------------------------
# AC3 — After erasing, the member displays as "Deleted member"
# ---------------------------------------------------------------------------


def test_member_shows_as_deleted_member_after_erase(page: Page) -> None:
    admin_token = _make_token("admin")
    _ensure_admin_profile(admin_token)
    suffix = uuid.uuid4().hex[:8]
    full_name = f"Erasure EraseTest{suffix}"
    member_id = _create_member_via_api(
        admin_token, "Erasure", f"EraseTest{suffix}", membership_status="archived"
    )
    _inject_cookie(page, admin_token)

    page.goto(f"{BASE_URL}/members/{member_id}")
    page.wait_for_load_state("networkidle")
    page.get_by_role("button", name=f"Delete {full_name} permanently").click()
    page.get_by_label("Type the member's name to confirm").fill(full_name)
    page.get_by_role("button", name="Confirm delete member permanently").click()

    expect(page.get_by_text("Deleted member").first).to_be_visible(timeout=8000)
