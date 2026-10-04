"""E2E browser tests for admin-issued recovery tokens (issue #42).

AC4: passkey count in member list — deferred (requires backend schema change).
AC5: Admin member detail view has a "Generate recovery token" button, and
     it issues a token for that Member's Account (#445: the endpoint takes the
     Member id the page has, not an Account id).
"""

from __future__ import annotations

import json
import os
import uuid

import pytest
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
API_URL = "http://localhost:8000/api"


# ── helpers ────────────────────────────────────────────────────────────────────


def _make_token(role: str) -> str:
    claims = AccountClaims(
        sub=str(uuid.uuid4()),
        email=f"{role}-{uuid.uuid4().hex[:6]}@dojo.test",
        role=role,  # type: ignore[arg-type]
        is_active=True,
    )
    return encode_token(claims)


def _set_cookie(page: Page, token: str) -> None:
    page.goto(BASE_URL)
    page.context.add_cookies(
        [{"name": "access_token", "value": token, "url": BASE_URL}]
    )


def _api_headers(token: str) -> dict:
    return {"Cookie": f"access_token={token}"}


def _create_member(page: Page, token: str) -> str:
    payload = {
        "email": f"member-{uuid.uuid4().hex[:8]}@dojo.test",
        "first_name": "Test",
        "surname": f"Member {uuid.uuid4().hex[:6]}",
        "dob": "1990-01-01",
        "join_date": "2024-01-01",
    }
    resp = page.request.post(
        f"{API_URL}/members",
        headers={**_api_headers(token), "Content-Type": "application/json"},
        data=json.dumps(payload),
    )
    assert resp.status == 201, f"Member create failed: {resp.text()}"
    return resp.json()["id"]


# ── AC4 — Admin member list shows passkey count ───────────────────────────────


@pytest.mark.skip(
    reason="AC4: passkey count in member list requires backend schema change — deferred to a follow-up issue"
)
def test_admin_member_list_shows_passkey_count(page: Page) -> None:
    pass


# ── AC5 — Admin member detail has generate recovery token button ──────────────


def test_admin_member_detail_has_generate_recovery_token_button(page: Page) -> None:
    admin_token = _make_token("admin")
    # The acting admin needs their own Member profile, or RequireProfile bounces
    # every navigation to /onboarding before the member detail page renders (#221).
    complete_onboarding(admin_token)
    member_id = _create_member(page, admin_token)

    _set_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/members/{member_id}")
    page.wait_for_load_state("networkidle")

    expect(page.get_by_role("button", name="Generate recovery token")).to_be_visible()


def _token_dialog(page: Page):
    return page.get_by_role("dialog", name="Recovery token", exact=True)


def _generate_token_for_a_registered_member(page: Page) -> str:
    """Drive the member page's generate flow; the plaintext token shown."""
    admin_token = _make_token("admin")
    complete_onboarding(admin_token)
    # A Member who has registered: complete_onboarding makes their forged
    # subject a real Account, so there is an Account to recover.
    member_id = complete_onboarding(_make_token("member"))["id"]

    _set_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/members/{member_id}")
    page.wait_for_load_state("networkidle")
    page.get_by_role("button", name="Generate recovery token").click()
    page.get_by_role("button", name="Generate token").click()

    shown = _token_dialog(page).get_by_label("Recovery token", exact=True)
    expect(shown).to_be_visible()
    token = shown.inner_text().strip()
    assert len(token) > 8
    return token


def test_admin_generate_recovery_token_shows_plaintext_once(page: Page) -> None:
    token = _generate_token_for_a_registered_member(page)

    _token_dialog(page).get_by_label("Close", exact=True).click()

    expect(_token_dialog(page)).to_have_count(0)
    expect(page.get_by_text(token)).to_have_count(0)
    # Starting the flow again does not bring the old token back.
    page.get_by_role("button", name="Generate recovery token").click()
    expect(page.get_by_role("dialog", name="Generate recovery token?")).to_be_visible()
    expect(page.get_by_text(token)).to_have_count(0)


def test_admin_generate_recovery_token_has_copy_to_clipboard(page: Page) -> None:
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    token = _generate_token_for_a_registered_member(page)

    page.get_by_role("button", name="Copy token to clipboard").click()

    expect(page.get_by_text("Copied!")).to_be_visible()
    assert page.evaluate("navigator.clipboard.readText()") == token
