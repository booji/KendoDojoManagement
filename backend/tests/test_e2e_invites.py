"""E2E browser test stubs for issue #257 — Admin-issued invite tokens for
passkey registration.

Red-phase stubs only: one per acceptance criterion in the issue. Nothing
under Admin Settings or a `/invite/{token}` landing page exists yet, so every
test here fails on the first `page.goto` / selector wait. Per the tdd skill's
xfail lifecycle, these are `xfail(strict=True)` markers that MUST be promoted
to real assertions (and the marker removed) once the UI is implemented --
never left as permanent xfail.

AC9 (redemption responses are indistinguishable for valid/invalid/expired/
already-redeemed/revoked tokens -- same status code, same body shape) and
AC10 (no timing asymmetry on the redemption path) are HTTP/timing-level
claims, not something a headless browser can observe or usefully assert on:
a browser only ever sees "the landing page did or didn't let me register,"
not the underlying response status code or wall-clock latency. Both are
already covered at the HTTP layer in backend/tests/test_invites.py
(`test_redeem_complete_status_and_body_identical_across_bad_token_reasons`,
`test_invite_redeem_begin_is_registered_as_constant_time_path`, and the
floor/median-convergence tests). Stubs are still included below so the
acceptance-criteria-to-test mapping stays 1:1, but they are written as thin
placeholders and should not be expected to gain meaningful browser assertions
even after promotion -- see each docstring.
"""

from __future__ import annotations

import pytest

# ── AC1: Invite model persists a token hash, never plaintext ────────────────
#
# Not browser-observable at all -- it's a DB-storage guarantee, already
# covered by backend/tests/test_invites.py::test_invite_model_has_field and
# ::test_invite_model_has_no_plaintext_token_field. Included here only to
# keep the 1:1 mapping; expect this one to stay a thin smoke check even after
# promotion (e.g. "minting an invite in the admin UI does not display any
# hash-looking value alongside the link").


@pytest.mark.xfail(strict=True, reason="AC1: admin invite UI not yet implemented")
def test_admin_invite_ui_never_displays_a_token_hash(page) -> None:
    page.goto("http://localhost:5173/settings/invites")
    page.click('[data-testid="invite-email-input"]')
    page.fill('[data-testid="invite-email-input"]', "newmember@dojo.test")
    page.click('[data-testid="invite-submit"]')
    page.wait_for_selector('[data-testid="invite-link"]', timeout=5000)
    link_text = page.text_content('[data-testid="invite-link"]')
    assert "$2" not in link_text  # no bcrypt-looking hash ever rendered


# ── AC2: Admin-only endpoint mints an invite, returns plaintext link once ───


@pytest.mark.xfail(strict=True, reason="AC2: invite issuance UI not yet implemented")
def test_admin_can_issue_invite_and_sees_copyable_link_once(page) -> None:
    page.goto("http://localhost:5173/settings/invites")
    page.fill('[data-testid="invite-email-input"]', "newmember@dojo.test")
    page.click('[data-testid="invite-submit"]')
    page.wait_for_selector('[data-testid="invite-link"]', timeout=5000)
    link_text = page.text_content('[data-testid="invite-link"]')
    assert "/invite/" in link_text
    # Reloading the list must not show the link again -- it was shown once.
    page.reload()
    assert page.locator('[data-testid="invite-link"]').count() == 0


# ── AC3: unauthenticated / non-admin rejected on every admin invite endpoint ─


@pytest.mark.xfail(
    strict=True, reason="AC3: invite settings page access control not yet implemented"
)
def test_non_admin_cannot_reach_invites_settings_page(page) -> None:
    page.goto("http://localhost:5173/settings/invites")
    # A member-role session must be redirected away, or shown a forbidden
    # state -- not the invite issuance form.
    page.wait_for_selector('[data-testid="forbidden"]', timeout=5000)


# ── AC4: listing invites shows status, never a plaintext token ──────────────


@pytest.mark.xfail(strict=True, reason="AC4: invite list UI not yet implemented")
def test_invite_list_shows_status_and_no_token(page) -> None:
    page.goto("http://localhost:5173/settings/invites")
    page.wait_for_selector('[data-testid="invite-row"]', timeout=5000)
    row_text = page.text_content('[data-testid="invite-row"]')
    assert any(s in row_text for s in ("Pending", "Redeemed", "Expired", "Revoked"))
    assert "/invite/" not in row_text


# ── AC5: revoking an invite makes it unusable; subsequent redemption fails ──


@pytest.mark.xfail(strict=True, reason="AC5: invite revoke UI not yet implemented")
def test_admin_can_revoke_invite_from_list(page) -> None:
    page.goto("http://localhost:5173/settings/invites")
    page.click('[data-testid="invite-revoke-button"]')
    page.wait_for_selector('[data-testid="invite-status-revoked"]', timeout=5000)


# ── AC6: redeeming a valid token completes passkey registration and creates/
#         links the Member ─────────────────────────────────────────────────
#
# Real WebAuthn ceremony completion needs a virtual authenticator, which is
# out of scope for headless Chromium here (same caveat as the existing
# passkey e2e suite). This stub only reaches the landing page and confirms
# registration UI is offered for a valid token.


@pytest.mark.xfail(strict=True, reason="AC6: invite landing page not yet implemented")
def test_invite_landing_page_offers_passkey_registration_for_valid_token(
    page,
) -> None:
    page.goto("http://localhost:5173/invite/some-valid-token")
    page.wait_for_selector('[data-testid="invite-register-button"]', timeout=5000)


# ── AC7: single use -- a second redemption with the same token fails ────────


@pytest.mark.xfail(strict=True, reason="AC7: invite landing page not yet implemented")
def test_invite_landing_page_shows_already_used_state(page) -> None:
    page.goto("http://localhost:5173/invite/an-already-redeemed-token")
    page.wait_for_selector('[data-testid="invite-invalid"]', timeout=5000)


# ── AC8: expiry -- a token past expires_at fails ─────────────────────────────


@pytest.mark.xfail(strict=True, reason="AC8: invite landing page not yet implemented")
def test_invite_landing_page_shows_expired_state(page) -> None:
    page.goto("http://localhost:5173/invite/an-expired-token")
    page.wait_for_selector('[data-testid="invite-invalid"]', timeout=5000)


# ── AC9: redemption responses indistinguishable across valid/invalid/expired/
#         already-redeemed/revoked -- HTTP/timing-level, not browser-verifiable
#
# See backend/tests/test_invites.py::
#   test_redeem_complete_status_and_body_identical_across_bad_token_reasons
# for the real assertion. This stub only checks that the landing page shows
# the SAME generic failure copy for an unknown token and an expired one --
# the weakest, browser-visible echo of the underlying HTTP guarantee. It
# cannot assert on status codes or exact response bodies.


@pytest.mark.xfail(strict=True, reason="AC9: invite landing page not yet implemented")
def test_invite_landing_page_shows_same_generic_failure_for_any_bad_token(
    page,
) -> None:
    page.goto("http://localhost:5173/invite/unknown-token-xyz")
    page.wait_for_selector('[data-testid="invite-invalid"]', timeout=5000)
    unknown_text = page.text_content('[data-testid="invite-invalid"]')

    page.goto("http://localhost:5173/invite/an-expired-token")
    page.wait_for_selector('[data-testid="invite-invalid"]', timeout=5000)
    expired_text = page.text_content('[data-testid="invite-invalid"]')

    assert unknown_text == expired_text


# ── AC10: no timing asymmetry on the redemption path -- HTTP/timing-level,
#          not browser-verifiable
#
# See backend/tests/test_invites.py::
#   test_invite_redeem_begin_is_registered_as_constant_time_path
#   test_invite_redeem_begin_valid_token_meets_configured_floor
#   test_invite_redeem_begin_invalid_token_meets_configured_floor
#   test_invite_redeem_begin_valid_vs_invalid_median_latency_converges
# A headless browser cannot measure wall-clock response latency meaningfully
# (page-load overhead, JS execution, and scheduling noise dwarf the ~ms-scale
# signal being defended against). This stub is included only to keep the
# acceptance-criteria mapping 1:1; it is not expected to become a real timing
# assertion even after promotion -- it should stay a smoke check that the
# landing page doesn't visibly stall on one path vs another.


@pytest.mark.xfail(strict=True, reason="AC10: invite landing page not yet implemented")
def test_invite_landing_page_does_not_visibly_stall_for_bad_token(page) -> None:
    page.goto("http://localhost:5173/invite/unknown-token-xyz")
    page.wait_for_selector('[data-testid="invite-invalid"]', timeout=1000)


# ── AC11: Admin UI can issue, list with status, and revoke ──────────────────
#
# Composite of AC2/AC4/AC5 above -- covered individually there. This stub
# exercises the full round trip in one flow, matching the issue's own
# phrasing of AC11 as a single UI capability.


@pytest.mark.xfail(
    strict=True, reason="AC11: admin invite management UI not yet implemented"
)
def test_admin_can_issue_list_and_revoke_invite_end_to_end(page) -> None:
    page.goto("http://localhost:5173/settings/invites")
    page.fill('[data-testid="invite-email-input"]', "roundtrip@dojo.test")
    page.click('[data-testid="invite-submit"]')
    page.wait_for_selector('[data-testid="invite-link"]', timeout=5000)

    page.reload()
    page.wait_for_selector('[data-testid="invite-row"]', timeout=5000)
    row_text = page.text_content('[data-testid="invite-row"]')
    assert "roundtrip@dojo.test" in row_text
    assert "Pending" in row_text

    page.click('[data-testid="invite-revoke-button"]')
    page.wait_for_selector('[data-testid="invite-status-revoked"]', timeout=5000)


# ── AC12: frontend invite landing page drives passkey registration ──────────


@pytest.mark.xfail(strict=True, reason="AC12: invite landing page not yet implemented")
def test_invite_landing_page_route_exists_and_drives_registration(page) -> None:
    page.goto("http://localhost:5173/invite/some-valid-token")
    expect_heading = page.get_by_role("heading", name="Complete your registration")
    expect_heading.wait_for(timeout=5000)
    page.click('[data-testid="invite-register-button"]')
    # Kicks off the WebAuthn ceremony -- headless Chromium has no
    # authenticator, so this only confirms the click is wired to *something*
    # observable rather than a no-op button.
    page.wait_for_selector('[data-testid="invite-register-in-progress"]', timeout=5000)
