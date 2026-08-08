"""
Playwright E2E browser test stubs for issue #258 — bounded session recurrence
(end_date).

One test per browser-observable acceptance criterion. All marked
@pytest.mark.xfail(strict=True) during the red phase. Remove xfail and replace
the body with real Playwright assertions once the frontend is implemented.

Not stubbed here (not observable in a browser — see TDD agent report):
  - AC4: GET /sessions performs no writes / no per-template query loop. This
    is a backend/repository-call-count property with no UI signal.
  - AC6: the Alembic migration and its backfill. Purely a data-layer concern
    with no UI surface.
"""

import pytest
from playwright.sync_api import Page

BASE_URL = "http://localhost:5173"


# ---------------------------------------------------------------------------
# AC1 — end_date is required and bounded (start_date < end_date <= start_date
# + 6 months); violations surface as a validation error in the create dialog.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="not yet implemented")
def test_create_dialog_rejects_end_date_beyond_six_month_cap(page: Page) -> None:
    pytest.fail("not implemented")


# ---------------------------------------------------------------------------
# AC2 — creating a template with an end date generates sessions across the
# full start_date..end_date range in one pass, visible in the calendar.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="not yet implemented")
def test_creating_template_populates_sessions_for_full_date_range(
    page: Page,
) -> None:
    pytest.fail("not implemented")


# ---------------------------------------------------------------------------
# AC3 — editing a template's recurrence regenerates only the delta; an
# individually-edited session's custom title survives the regeneration.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="not yet implemented")
def test_editing_recurrence_preserves_individually_edited_session(
    page: Page,
) -> None:
    pytest.fail("not implemented")


# ---------------------------------------------------------------------------
# AC5 — the extend action bumps a template's expiry date and generates the
# newly-covered sessions, visible without a page reload confusion.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="not yet implemented")
def test_extend_action_bumps_expiry_date_shown_on_template(page: Page) -> None:
    pytest.fail("not implemented")


# ---------------------------------------------------------------------------
# AC7 — the create/edit template dialog has an end-date picker, and the
# template card/detail view shows the expiry date.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="not yet implemented")
def test_template_dialog_has_end_date_picker_and_expiry_is_shown(
    page: Page,
) -> None:
    pytest.fail("not implemented")
