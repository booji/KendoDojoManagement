"""E2E stub tests for issue #101 — Rate limiting UI behaviour.

These are xfail stubs (red phase). They must be promoted to real Playwright
assertions once implementation is complete and the UI is updated.
"""

from __future__ import annotations

import pytest


@pytest.mark.xfail(strict=True, reason="not implemented")
def test_rate_limit_ui_shows_retry_after(page) -> None:
    """UI must display a human-readable 'try again in N seconds' message
    after the user is rate-limited on the login page.
    """
    pytest.fail("not implemented")


@pytest.mark.xfail(strict=True, reason="not implemented")
def test_account_lockout_ui_shows_clear_message(page) -> None:
    """UI must display 'Account temporarily locked' (or equivalent) when the
    account is locked out, clearly distinguishing it from a wrong-password error.
    """
    pytest.fail("not implemented")
