"""
Playwright browser tests for issue #25 — Member self-update API.

These are API-only endpoints (no frontend UI in this issue).
Stubs are marked xfail(strict=True) to reserve test slots for a future
UI implementation; promote to real assertions once a UI exists.
"""

import pytest
from playwright.sync_api import Page

# ---------------------------------------------------------------------------
# AC1 — GET /users/me/member visible in UI (placeholder)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True, reason="not implemented: no UI for self-update in this issue"
)
def test_member_can_view_own_profile_via_self_update_page(page: Page) -> None:
    pytest.fail("not implemented")


# ---------------------------------------------------------------------------
# AC2 — PUT /users/me/member update visible in UI (placeholder)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True, reason="not implemented: no UI for self-update in this issue"
)
def test_member_can_update_own_profile_fields(page: Page) -> None:
    pytest.fail("not implemented")


# ---------------------------------------------------------------------------
# AC4 — First-save onboarding via UI (placeholder)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True, reason="not implemented: no UI for self-update in this issue"
)
def test_member_onboarding_creates_profile(page: Page) -> None:
    pytest.fail("not implemented")
