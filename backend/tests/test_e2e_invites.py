"""E2E browser tests for issue #257 — Admin-issued invite tokens for passkey
registration.

One test per acceptance criterion from the issue. Promoted from red-phase
xfail stubs once the admin invites page (/settings/invites) and the public
landing page (/invite/:token) were implemented.

Two criteria are deliberately NOT asserted at the browser level:

AC9 (redemption responses are indistinguishable for valid/invalid/expired/
already-redeemed/revoked tokens -- same status code, same body shape) IS
browser-verifiable as a thin echo (the landing page renders the identical
generic failure copy regardless of *why* a token was rejected) and is kept
below. The stronger claim -- identical status code and body bytes -- is
already covered at the HTTP layer in backend/tests/test_invites.py
(`test_redeem_complete_status_and_body_identical_across_bad_token_reasons`).

AC10 (no timing asymmetry on the redemption path) is a wall-clock claim.
Headless Playwright cannot measure it meaningfully -- page-load and JS
execution overhead dwarf the ms-scale signal being defended against -- so it
stays `xfail(strict=False)`: present as a smoke check, allowed to fail or
pass without affecting CI either way. Real coverage is in
backend/tests/test_invites.py (`test_invite_redeem_begin_is_registered_as_
constant_time_path`, `..._valid_token_meets_configured_floor`,
`..._invalid_token_meets_configured_floor`,
`..._valid_vs_invalid_median_latency_converges`).

WebAuthn ceremony completion (navigator.credentials.create) requires a real
or CDP virtual authenticator, which this repo does not have (confirmed: no
virtual-authenticator helper exists anywhere in backend/tests -- the same gap
noted in test_e2e_setup.py's AC5 and test_e2e_passkey_nudge.py). Tests below
that need to get past the browser-side ceremony call reuse that file's
`_stub_navigator_credentials` technique: navigator.credentials.create is
replaced with a stub returning a syntactically-shaped but cryptographically
meaningless credential. This is safe for AC7/AC8/AC9 because the real backend
(invite_service.invite_redeem_complete) checks token usability *before*
touching the credential -- an already-redeemed or expired invite is rejected
on that precheck regardless of what the credential looks like, so the
assertion still exercises real single-use/expiry enforcement. It would NOT be
safe to use for a claim like "a valid token's registration succeeds", because
a garbage credential fails real cryptographic verification for every token --
that's exactly why AC6 below only asserts the registration button appears,
not that clicking it succeeds.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import os
import uuid

import asyncpg
import pytest
import requests
from playwright.sync_api import Page, expect

from app.auth.invite_service import hash_invite_token
from tests.e2e_support import API_URL, BASE_URL, authenticate, complete_onboarding

pytestmark = pytest.mark.e2e


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stub_navigator_credentials(page: Page) -> None:
    """Replace navigator.credentials.create with a stub returning a fake
    credential, so the ceremony can proceed past the (unavailable-in-headless)
    WebAuthn prompt. See module docstring for why this is safe to use only for
    already-rejected tokens, not to claim a valid registration succeeds."""
    page.add_init_script("""
        const fakeCredential = {
            id: "dGVzdC1jcmVkLWlk",
            rawId: new Uint8Array([116,101,115,116,45,99,114,101,100,45,105,100]).buffer,
            type: "public-key",
            response: {
                clientDataJSON: new Uint8Array([116,101,115,116]).buffer,
                attestationObject: new Uint8Array([116,101,115,116]).buffer,
                getTransports: () => [],
            },
            getClientExtensionResults: () => ({}),
        };
        Object.defineProperty(navigator, 'credentials', {
            value: {
                create: async () => fakeCredential,
                get: async () => fakeCredential,
                store: async () => {},
                preventSilentAccess: async () => {},
            },
            writable: true,
            configurable: true,
        });
    """)


def _real_login(role: str = "admin") -> str:
    """Create-or-get a real, DB-backed user via the test-only login endpoint
    and return the session token.

    Needed anywhere a forged-but-unbacked JWT (tests.e2e_support.make_token)
    won't do: invites.issued_by is a foreign key to users.id, so minting an
    invite as a user with no row in `users` fails the FK with a 500.
    """
    email = f"{role}-{uuid.uuid4().hex[:8]}@dojo.test"
    resp = requests.post(
        f"{API_URL}/auth/login/test",
        json={"email": email, "role": role},
        timeout=5,
    )
    resp.raise_for_status()
    return resp.cookies["access_token"]


def _login_admin_in_browser(page: Page) -> str:
    """Real DB-backed admin login (see _real_login), with the session cookie
    attached to the browser context and onboarding completed so RequireProfile
    doesn't redirect away from /settings/invites."""
    token = _real_login("admin")
    page.context.add_cookies(
        [
            {
                "name": "access_token",
                "value": token,
                "domain": "localhost",
                "path": "/",
                "httpOnly": True,
                "sameSite": "Strict",
            }
        ]
    )
    complete_onboarding(token)
    return token


def _mint_invite(email: str) -> str:
    """Mint an invite via the real admin API (no browser involved). Returns
    the plaintext token."""
    admin_token = _real_login("admin")
    resp = requests.post(
        f"{API_URL}/auth/admin/invites",
        json={"email": email, "first_name": "Test", "surname": "Invitee"},
        cookies={"access_token": admin_token},
        timeout=5,
    )
    resp.raise_for_status()
    return resp.json()["token"]


def _run_async(coro) -> None:
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(lambda: asyncio.run(coro)).result()


async def _update_invite_row(token: str, column: str, value: str) -> None:
    db_url = os.environ["DATABASE_URL"].replace(
        "postgresql+asyncpg://", "postgresql://"
    )
    conn = await asyncpg.connect(db_url)
    try:
        await conn.execute(
            f"UPDATE invites SET {column} = {value} WHERE token_hash = $1",
            hash_invite_token(token),
        )
    finally:
        await conn.close()


def _mark_invite_redeemed(token: str) -> None:
    """Directly flip redeemed_at in the DB -- bypasses the real registration
    ceremony (which can't run headless) while still exercising the real
    is_usable() precheck on redemption."""
    _run_async(_update_invite_row(token, "redeemed_at", "now()"))


def _mark_invite_expired(token: str) -> None:
    _run_async(_update_invite_row(token, "expires_at", "now() - interval '1 hour'"))


# ── AC1: Invite model persists a token hash, never plaintext ────────────────
#
# The storage guarantee itself is covered at the DB layer in
# backend/tests/test_invites.py (test_invite_model_has_field,
# test_invite_model_has_no_plaintext_token_field). This is the thin,
# browser-visible echo: minting an invite in the admin UI never renders
# anything hash-shaped alongside the plaintext link.


def test_admin_invite_ui_never_displays_a_token_hash(page: Page) -> None:
    _login_admin_in_browser(page)
    page.goto(f"{BASE_URL}/settings/invites")
    email = f"newmember-{uuid.uuid4().hex[:8]}@dojo.test"
    page.fill('[data-testid="invite-first-name-input"]', "Test")
    page.fill('[data-testid="invite-surname-input"]', "Invitee")
    page.fill('[data-testid="invite-email-input"]', email)
    page.click('[data-testid="invite-submit"]')
    page.wait_for_selector('[data-testid="invite-link"]', timeout=5000)
    link_text = page.text_content('[data-testid="invite-link"]')
    assert link_text is not None
    assert "$2" not in link_text  # no bcrypt-looking hash ever rendered


# ── AC2: Admin-only endpoint mints an invite, returns plaintext link once ───


def test_admin_can_issue_invite_and_sees_copyable_link_once(page: Page) -> None:
    _login_admin_in_browser(page)
    page.goto(f"{BASE_URL}/settings/invites")
    email = f"newmember-{uuid.uuid4().hex[:8]}@dojo.test"
    page.fill('[data-testid="invite-first-name-input"]', "Test")
    page.fill('[data-testid="invite-surname-input"]', "Invitee")
    page.fill('[data-testid="invite-email-input"]', email)
    page.click('[data-testid="invite-submit"]')
    page.wait_for_selector('[data-testid="invite-link"]', timeout=5000)
    link_text = page.text_content('[data-testid="invite-link"]')
    assert link_text is not None
    assert "/invite/" in link_text
    # Reloading the list must not show the link again -- it was shown once.
    page.reload()
    expect(page.locator('[data-testid="invite-link"]')).to_have_count(0)


# ── AC3: unauthenticated / non-admin rejected on every admin invite endpoint ─


def test_non_admin_cannot_reach_invites_settings_page(page: Page) -> None:
    authenticate(page, "member")
    page.goto(f"{BASE_URL}/settings/invites")
    # A member-role session must be shown a forbidden state, not the
    # invite-issuance form.
    page.wait_for_selector('[data-testid="forbidden"]', timeout=5000)
    assert page.locator('[data-testid="invite-email-input"]').count() == 0


# ── AC4: listing invites shows status, never a plaintext token ──────────────


def test_invite_list_shows_status_and_no_token(page: Page) -> None:
    admin_token = _login_admin_in_browser(page)
    email = f"list-{uuid.uuid4().hex[:8]}@dojo.test"
    resp = requests.post(
        f"{API_URL}/auth/admin/invites",
        json={"email": email, "first_name": "Test", "surname": "Invitee"},
        cookies={"access_token": admin_token},
        timeout=5,
    )
    resp.raise_for_status()

    page.goto(f"{BASE_URL}/settings/invites")
    row = page.locator('[data-testid="invite-row"]', has_text=email)
    expect(row).to_be_visible(timeout=5000)
    row_text = row.inner_text()
    assert any(s in row_text for s in ("Pending", "Redeemed", "Expired", "Revoked"))
    assert "/invite/" not in row_text


# ── AC5: revoking an invite makes it unusable; subsequent redemption fails ──


def test_admin_can_revoke_invite_from_list(page: Page) -> None:
    admin_token = _login_admin_in_browser(page)
    email = f"revoke-{uuid.uuid4().hex[:8]}@dojo.test"
    resp = requests.post(
        f"{API_URL}/auth/admin/invites",
        json={"email": email, "first_name": "Test", "surname": "Invitee"},
        cookies={"access_token": admin_token},
        timeout=5,
    )
    resp.raise_for_status()

    page.goto(f"{BASE_URL}/settings/invites")
    row = page.locator('[data-testid="invite-row"]', has_text=email)
    expect(row).to_be_visible(timeout=5000)
    row.locator('[data-testid="invite-revoke-button"]').click()
    expect(row.locator('[data-testid="invite-status-revoked"]')).to_be_visible(
        timeout=5000
    )


# ── AC6: redeeming a valid token offers passkey registration ────────────────
#
# Full ceremony completion needs a real/virtual authenticator (see module
# docstring) and is out of scope. This confirms the landing page recognises a
# genuinely pending, real invite and offers registration -- the button
# appearing is contingent on redeem/begin succeeding for a usable token.


def test_invite_landing_page_offers_passkey_registration_for_valid_token(
    page: Page,
) -> None:
    token = _mint_invite(f"valid-{uuid.uuid4().hex[:8]}@dojo.test")
    page.context.clear_cookies()
    page.goto(f"{BASE_URL}/invite/{token}")
    page.wait_for_selector('[data-testid="invite-register-button"]', timeout=5000)


# ── AC7: single use -- a second redemption with the same token fails ────────
#
# The original stub expected `invite-invalid` immediately on page load. The
# server deliberately returns an indistinguishable 200 from redeem/begin (AC9)
# -- the client cannot know a token is bad until a redemption is actually
# attempted -- so the landing page (correctly) only shows invite-invalid after
# a failed attempt, not on load. The stub was wrong here, not the UI; fixed
# below to click register first.


def test_invite_landing_page_shows_already_used_state(page: Page) -> None:
    token = _mint_invite(f"used-{uuid.uuid4().hex[:8]}@dojo.test")
    _mark_invite_redeemed(token)

    _stub_navigator_credentials(page)
    page.context.clear_cookies()
    page.goto(f"{BASE_URL}/invite/{token}")
    page.click('[data-testid="invite-register-button"]')
    page.wait_for_selector('[data-testid="invite-invalid"]', timeout=5000)


# ── AC8: expiry -- a token past expires_at fails ─────────────────────────────
#
# Same page-load-vs-click correction as AC7.


def test_invite_landing_page_shows_expired_state(page: Page) -> None:
    token = _mint_invite(f"expired-{uuid.uuid4().hex[:8]}@dojo.test")
    _mark_invite_expired(token)

    _stub_navigator_credentials(page)
    page.context.clear_cookies()
    page.goto(f"{BASE_URL}/invite/{token}")
    page.click('[data-testid="invite-register-button"]')
    page.wait_for_selector('[data-testid="invite-invalid"]', timeout=5000)


# ── AC9: redemption responses indistinguishable across valid/invalid/expired/
#         already-redeemed/revoked -- browser-visible echo only
#
# The strong claim (identical status code + body) is HTTP-level and covered
# in backend/tests/test_invites.py. This is the weakest, browser-observable
# echo of that guarantee: an unknown token and an expired token render the
# exact same generic failure copy. Also fixes the page-load-vs-click bug from
# the original stub.


def test_invite_landing_page_shows_same_generic_failure_for_any_bad_token(
    page: Page,
) -> None:
    _stub_navigator_credentials(page)
    page.context.clear_cookies()

    page.goto(f"{BASE_URL}/invite/unknown-token-{uuid.uuid4().hex}")
    page.click('[data-testid="invite-register-button"]')
    page.wait_for_selector('[data-testid="invite-invalid"]', timeout=5000)
    unknown_text = page.text_content('[data-testid="invite-invalid"]')

    expired_token = _mint_invite(f"cmp-{uuid.uuid4().hex[:8]}@dojo.test")
    _mark_invite_expired(expired_token)

    page.goto(f"{BASE_URL}/invite/{expired_token}")
    page.click('[data-testid="invite-register-button"]')
    page.wait_for_selector('[data-testid="invite-invalid"]', timeout=5000)
    expired_text = page.text_content('[data-testid="invite-invalid"]')

    assert unknown_text == expired_text


# ── AC10: no timing asymmetry on the redemption path -- not meaningfully
#          browser-verifiable
#
# See backend/tests/test_invites.py for the real timing coverage. Kept as
# xfail(strict=False), matching the established pattern in
# test_e2e_setup.py's AC5: present as a smoke check, but neither an
# unexpected pass nor an expected failure affects CI.


@pytest.mark.xfail(
    strict=False,
    reason=(
        "Wall-clock timing assertions are not meaningful in headless "
        "Playwright -- page-load and JS-execution overhead dwarf the ms-scale "
        "signal being defended against. Real coverage: backend/tests/"
        "test_invites.py::test_invite_redeem_begin_is_registered_as_constant_"
        "time_path and the floor/median-convergence tests."
    ),
)
def test_invite_landing_page_does_not_visibly_stall_for_bad_token(page: Page) -> None:
    _stub_navigator_credentials(page)
    page.context.clear_cookies()
    page.goto(f"{BASE_URL}/invite/unknown-token-{uuid.uuid4().hex}")
    page.click('[data-testid="invite-register-button"]')
    page.wait_for_selector('[data-testid="invite-invalid"]', timeout=1000)


# ── AC11: Admin UI can issue, list with status, and revoke ──────────────────
#
# Composite of AC2/AC4/AC5 -- covered individually there. This exercises the
# full round trip in one flow, matching the issue's own phrasing of AC11 as a
# single UI capability.


def test_admin_can_issue_list_and_revoke_invite_end_to_end(page: Page) -> None:
    _login_admin_in_browser(page)
    email = f"roundtrip-{uuid.uuid4().hex[:8]}@dojo.test"

    page.goto(f"{BASE_URL}/settings/invites")
    page.fill('[data-testid="invite-first-name-input"]', "Test")
    page.fill('[data-testid="invite-surname-input"]', "Invitee")
    page.fill('[data-testid="invite-email-input"]', email)
    page.click('[data-testid="invite-submit"]')
    page.wait_for_selector('[data-testid="invite-link"]', timeout=5000)

    page.reload()
    row = page.locator('[data-testid="invite-row"]', has_text=email)
    expect(row).to_be_visible(timeout=5000)
    assert "Pending" in row.inner_text()

    row.locator('[data-testid="invite-revoke-button"]').click()
    expect(row.locator('[data-testid="invite-status-revoked"]')).to_be_visible(
        timeout=5000
    )


# ── AC12: frontend invite landing page drives passkey registration ──────────
#
# Confirms the click is wired to the real redemption flow (registering state
# appears), not that the ceremony completes -- see module docstring.


def test_invite_landing_page_route_exists_and_drives_registration(page: Page) -> None:
    token = _mint_invite(f"drive-{uuid.uuid4().hex[:8]}@dojo.test")

    _stub_navigator_credentials(page)
    page.context.clear_cookies()
    page.goto(f"{BASE_URL}/invite/{token}")
    # CardTitle renders as a <div data-slot="card-title">, not a semantic
    # heading — use get_by_text so this doesn't depend on the element type
    # (same caveat as test_e2e_setup.py's setup-page checks).
    expect(page.get_by_text("Complete your registration")).to_be_visible(timeout=5000)
    page.click('[data-testid="invite-register-button"]')
    page.wait_for_selector('[data-testid="invite-register-in-progress"]', timeout=5000)
