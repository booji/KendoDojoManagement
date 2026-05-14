import pytest

pytestmark = pytest.mark.anyio


@pytest.mark.xfail(strict=True, reason="e2e not yet implemented")
async def test_submit_grade_button_visible_on_own_page():
    """AC8: 'Submit my grade' button appears only on the member's own detail page."""
    pytest.fail("stub")


@pytest.mark.xfail(strict=True, reason="e2e not yet implemented")
async def test_pending_entry_shows_awaiting_confirmation_badge():
    """AC9: Pending grade entries show an 'awaiting confirmation' badge in history list."""
    pytest.fail("stub")
