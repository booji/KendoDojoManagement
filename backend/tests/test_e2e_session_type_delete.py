"""
E2E browser tests for issue #176 — Guard type deletion when referenced by a segment.

Acceptance criteria:
  1. Deleting a session type referenced by any segment is rejected with a clear error.
  2. Deleting an unreferenced session type succeeds.
  3. Test covers both the referenced and unreferenced cases.

All tests are marked xfail(strict=True) in the red phase — remove xfail and
replace bodies with real Playwright assertions once the UI is implemented.
"""

from __future__ import annotations

import pytest


@pytest.mark.xfail(strict=True, reason="not implemented")
def test_admin_can_delete_unreferenced_session_type(page) -> None:
    """AC2: Admin can delete a session type that is not referenced by any segment."""
    pytest.fail("not implemented")


@pytest.mark.xfail(strict=True, reason="not implemented")
def test_delete_session_type_shows_error_when_referenced_by_segment(page) -> None:
    """AC1: Attempting to delete a session type used by a segment shows a clear error to the admin."""
    pytest.fail("not implemented")


@pytest.mark.xfail(strict=True, reason="not implemented")
def test_referenced_session_type_remains_after_failed_delete(page) -> None:
    """AC3: After a failed delete attempt (409), the type still appears in the settings list."""
    pytest.fail("not implemented")
