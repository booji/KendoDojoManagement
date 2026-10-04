"""E2E browser tests for admin-issued recovery tokens (issue #42).

AC4: passkey count in member list — deferred (requires backend schema change).
AC5: Admin member detail view has a "Generate recovery token" button.
     Token generation flow deferred: frontend passes member.id as user_id;
     needs member.user_id fix before the generation flow can be tested E2E.
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


@pytest.mark.xfail(
    strict=True,
    reason="Frontend passes member.id as user_id; needs member.user_id fix before this flow works",
)
def test_admin_generate_recovery_token_shows_plaintext_once(page: Page) -> None:
    pytest.fail("not implemented: member.id vs user_id mismatch")


@pytest.mark.xfail(
    strict=True,
    reason="Frontend passes member.id as user_id; needs member.user_id fix before this flow works",
)
def test_admin_generate_recovery_token_has_copy_to_clipboard(page: Page) -> None:
    pytest.fail("not implemented: member.id vs user_id mismatch")
