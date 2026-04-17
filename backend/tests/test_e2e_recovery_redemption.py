"""E2E browser tests for issue #41 — Recovery code redemption UI.

AC4: After successful redemption, frontend redirects to passkey registration
     with banner "You're using a recovery session — please register your
     passkey to restore full access."
AC8: After completing passkey registration via recovery session, UI shows
     a soft recommendation to review and remove stale passkeys.
"""

from __future__ import annotations

import pytest


@pytest.mark.xfail(strict=True, reason="AC4: frontend not yet implemented")
def test_recovery_session_redirects_to_passkey_registration(page) -> None:
    """After redeeming a recovery code the UI navigates to passkey registration."""
    page.goto("http://localhost:5173/recovery/redeem")
    page.fill('[data-testid="recovery-email"]', "musashi@dojo.test")
    page.fill('[data-testid="recovery-code"]', "abcd-efgh-ijkl")
    page.click('[data-testid="recovery-submit"]')
    page.wait_for_url("**/passkey/register**", timeout=5000)


@pytest.mark.xfail(strict=True, reason="AC4: recovery banner not yet implemented")
def test_recovery_session_banner_visible_after_redemption(page) -> None:
    """Banner is shown after successful redemption: correct copy."""
    page.goto("http://localhost:5173/recovery/redeem")
    page.fill('[data-testid="recovery-email"]', "musashi@dojo.test")
    page.fill('[data-testid="recovery-code"]', "abcd-efgh-ijkl")
    page.click('[data-testid="recovery-submit"]')
    page.wait_for_selector('[data-testid="recovery-session-banner"]', timeout=5000)
    banner_text = page.text_content('[data-testid="recovery-session-banner"]')
    assert (
        "You're using a recovery session" in banner_text
        and "register your passkey" in banner_text
    )


@pytest.mark.xfail(
    strict=True, reason="AC8: stale passkey recommendation not yet implemented"
)
def test_passkey_registration_via_recovery_shows_stale_passkey_recommendation(
    page,
) -> None:
    """After completing passkey registration via recovery, a soft recommendation
    to review and remove stale passkeys is displayed."""
    # Navigate straight to the post-registration state
    page.goto("http://localhost:5173/passkey/register")
    # Complete the registration flow (stubbed: just check post-success state)
    page.wait_for_selector('[data-testid="stale-passkey-recommendation"]', timeout=5000)
    text = page.text_content('[data-testid="stale-passkey-recommendation"]')
    assert "stale passkey" in text.lower() or "remove" in text.lower()
