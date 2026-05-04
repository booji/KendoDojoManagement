"""
Playwright E2E browser test stubs for issue #124 — Multi-federation membership numbers.

One test per acceptance criterion. All marked @pytest.mark.xfail(strict=True) during
the red phase. Remove xfail and replace the body with real Playwright assertions after
implementation.
"""

import pytest
from playwright.sync_api import Page

BASE_URL = "http://localhost:5173"


# ---------------------------------------------------------------------------
# AC1 — Members can add multiple federation memberships
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="not yet implemented")
def test_member_can_add_federation_membership(page: Page) -> None:
    pytest.fail("not implemented")


# ---------------------------------------------------------------------------
# AC2 — Federation list pre-populated (FIK affiliates, 67 entries) and selectable
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="not yet implemented")
def test_federation_list_is_pre_populated_and_selectable(page: Page) -> None:
    pytest.fail("not implemented")


# ---------------------------------------------------------------------------
# AC3 — Members can enter a membership number (free text, max 100 chars)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="not yet implemented")
def test_membership_number_input_accepts_free_text(page: Page) -> None:
    pytest.fail("not implemented")


# ---------------------------------------------------------------------------
# AC4 — Members can optionally record a renewal date
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="not yet implemented")
def test_renewal_date_is_optional_on_federation_membership(page: Page) -> None:
    pytest.fail("not implemented")


# ---------------------------------------------------------------------------
# AC5 — Visual warning when renewal_date expiring soon or expired; no warning if no date
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="not yet implemented")
def test_expired_renewal_date_shows_warning(page: Page) -> None:
    pytest.fail("not implemented")


@pytest.mark.xfail(strict=True, reason="not yet implemented")
def test_expiring_soon_renewal_date_shows_warning(page: Page) -> None:
    pytest.fail("not implemented")


@pytest.mark.xfail(strict=True, reason="not yet implemented")
def test_no_renewal_date_shows_no_warning(page: Page) -> None:
    pytest.fail("not implemented")


# ---------------------------------------------------------------------------
# AC6 — Members can edit existing federation memberships
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="not yet implemented")
def test_member_can_edit_federation_membership(page: Page) -> None:
    pytest.fail("not implemented")


# ---------------------------------------------------------------------------
# AC7 — Members can remove a federation membership
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="not yet implemented")
def test_member_can_remove_federation_membership(page: Page) -> None:
    pytest.fail("not implemented")


# ---------------------------------------------------------------------------
# AC8 — Pinned federations float to top of selection lists
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="not yet implemented")
def test_pinned_federations_appear_at_top_of_selection_list(page: Page) -> None:
    pytest.fail("not implemented")


# ---------------------------------------------------------------------------
# AC9 — Admins can manage memberships on any member via /members/{id}/federations
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="not yet implemented")
def test_admin_can_manage_federation_membership_on_any_member(page: Page) -> None:
    pytest.fail("not implemented")


# ---------------------------------------------------------------------------
# AC10 — Members can manage their own via /users/me/federations; cannot access others'
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="not yet implemented")
def test_member_can_manage_own_federations_via_me_endpoint_ui(page: Page) -> None:
    pytest.fail("not implemented")


@pytest.mark.xfail(strict=True, reason="not yet implemented")
def test_member_cannot_see_other_members_federation_records(page: Page) -> None:
    pytest.fail("not implemented")


# ---------------------------------------------------------------------------
# AC11 — Admins can add new federations to the catalogue
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="not yet implemented")
def test_admin_can_add_new_federation_to_catalogue(page: Page) -> None:
    pytest.fail("not implemented")


# ---------------------------------------------------------------------------
# AC12 — Admins can edit federation metadata
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="not yet implemented")
def test_admin_can_edit_federation_metadata(page: Page) -> None:
    pytest.fail("not implemented")


# ---------------------------------------------------------------------------
# AC13 — Admins can pin/unpin a federation
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="not yet implemented")
def test_admin_can_pin_federation(page: Page) -> None:
    pytest.fail("not implemented")


@pytest.mark.xfail(strict=True, reason="not yet implemented")
def test_admin_can_unpin_federation(page: Page) -> None:
    pytest.fail("not implemented")


# ---------------------------------------------------------------------------
# AC14 — Admins can deactivate a federation (soft-delete)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="not yet implemented")
def test_admin_can_deactivate_federation(page: Page) -> None:
    pytest.fail("not implemented")


# ---------------------------------------------------------------------------
# AC15 — Admins can reactivate a deactivated federation
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="not yet implemented")
def test_admin_can_reactivate_federation(page: Page) -> None:
    pytest.fail("not implemented")


# ---------------------------------------------------------------------------
# AC16 — GET /federations ordering and filtering reflected in UI
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="not yet implemented")
def test_federation_list_shows_pinned_first_then_alphabetical(page: Page) -> None:
    pytest.fail("not implemented")


@pytest.mark.xfail(strict=True, reason="not yet implemented")
def test_federation_list_supports_type_filter(page: Page) -> None:
    pytest.fail("not implemented")


@pytest.mark.xfail(strict=True, reason="not yet implemented")
def test_federation_list_supports_search_by_name_prefix(page: Page) -> None:
    pytest.fail("not implemented")


# ---------------------------------------------------------------------------
# AC17 — GET /federations requires any authenticated user
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="not yet implemented")
def test_unauthenticated_user_cannot_see_federation_list(page: Page) -> None:
    pytest.fail("not implemented")


# ---------------------------------------------------------------------------
# AC18 — Renewal date status is a computed field (not stored)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="not yet implemented")
def test_renewal_status_badge_matches_computed_server_value(page: Page) -> None:
    pytest.fail("not implemented")


# ---------------------------------------------------------------------------
# AC19 — Inactive federations hidden from list in UI
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="not yet implemented")
def test_deactivated_federation_not_shown_in_selection_list(page: Page) -> None:
    pytest.fail("not implemented")


# ---------------------------------------------------------------------------
# AC20 — federation_number no longer shown on member profile
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="not yet implemented")
def test_member_profile_has_no_legacy_federation_number_field(page: Page) -> None:
    pytest.fail("not implemented")
