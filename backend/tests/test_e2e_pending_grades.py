"""
E2E browser test stubs for issue #147 — Admin global pending grade queue page.

These tests are marked xfail(strict=True) as red-phase placeholders.
They must be promoted to real Playwright assertions once the frontend
implementation is complete.

Acceptance criteria exercised here:
  7. Admin can see the pending queue section on the Grades admin page
  8. Approve action removes the row from the queue
  9. Reject action removes the row from the queue
"""

import pytest

pytestmark = pytest.mark.anyio


@pytest.mark.xfail(strict=True, reason="not implemented")
def test_admin_sees_pending_queue_on_grades_page() -> None:
    """AC7/AC4(UI): Admin navigates to Grades admin page and sees the pending queue section.

    When there are pending grade submissions, the section is visible and lists
    each row with: member name, proposed grade, proposed date (or 'not provided').
    """
    pytest.fail("not implemented")


@pytest.mark.xfail(strict=True, reason="not implemented")
def test_approve_action_removes_row_from_queue() -> None:
    """AC6/AC8: Clicking Approve on a pending row calls the approve endpoint and
    removes the row from the queue without a page reload.
    """
    pytest.fail("not implemented")


@pytest.mark.xfail(strict=True, reason="not implemented")
def test_reject_action_removes_row_from_queue() -> None:
    """AC6/AC9: Clicking Reject on a pending row calls the reject/delete endpoint and
    removes the row from the queue without a page reload.
    """
    pytest.fail("not implemented")
