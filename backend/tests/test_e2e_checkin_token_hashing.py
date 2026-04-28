"""
E2E stubs for issue #100 — Check-in token hashing + used_at idempotency.

Each test is marked xfail(strict=True) — they are red-phase placeholders.
Replace the body with real Playwright assertions once the feature is
implemented and both servers are running.

AC8: End-to-end check-in flow unchanged from member perspective.
"""

from __future__ import annotations

import pytest


@pytest.mark.xfail(strict=True, reason="not implemented")
def test_e2e_member_can_scan_qr_and_check_in(page) -> None:  # type: ignore[no-untyped-def]
    """AC8: A member navigates to a check-in URL (/checkin/<token>) and
    is checked in successfully — the same observable flow as before token
    hashing was introduced.
    """
    pytest.fail("not implemented")
