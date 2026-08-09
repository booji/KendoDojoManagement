"""E2E browser test stubs for issue #300 — Passkey register-begin leaks
registration status through user.id stability.

Red-phase stubs only (tdd skill convention): every test below is
`xfail(strict=True)` with a `pytest.fail("not implemented")` body, reserving
one test slot per acceptance criterion. The QA agent promotes each to a real
Playwright assertion once the fix lands, or removes/escalates the ones that
turn out not to be genuinely browser-verifiable.

Real backend defect (see backend/tests/test_passkey_enumeration.py and
backend/tests/test_invites.py for the load-bearing coverage):
`register_passkey_begin` returns the persisted `User.id` as
`publicKey.user.id` -- stable forever for a known email -- while
`_decoy_register_response` mints a fresh `uuid4()` per call for an unknown
one. Two POSTs plus one field comparison classifies any email.
`invite_redeem_begin` / `invite_service._decoy_response` have the same
real-stable / decoy-random pairing, keyed on invite token instead of email.

Per-AC browser-verifiability assessment (see individual docstrings below):

  AC1 (stable-on-both-or-random-on-both)  -- NOT genuinely browser-verifiable.
      This is a claim about the raw JSON value of publicKey.user.id across
      two HTTP responses. A WebAuthn ceremony cannot complete in headless
      Chromium without a virtual authenticator (no such helper exists in
      this repo -- see test_e2e_invites.py's module docstring), so the
      browser can only ever observe "the ceremony was offered", never the
      raw field value that carries the oracle. Real coverage:
      test_passkey_enumeration.py::test_register_begin_decoy_user_id_stable_
      then_secret_dependent and its real-path counterpart.

  AC2 (holds for both register_passkey_begin AND invite_redeem_begin) --
      same limitation as AC1, doubled. NOT genuinely browser-verifiable for
      the same reason; kept as a single combined stub rather than two, since
      neither half can be exercised any more meaningfully than the other in
      a browser. Real coverage: the same test above plus
      test_invites.py::test_redeem_begin_decoy_user_id_stable_then_secret_
      dependent.

  AC3 (decoy not derivable without server secret) -- NOT browser-verifiable.
      The browser has no way to observe or vary JWT_SECRET; this is a
      server-internal derivation property. Real coverage: the same two
      tests above (both assert the id changes when JWT_SECRET is
      monkeypatched).

  AC4 (decoy paths write no DB rows) -- NOT browser-verifiable. Row counts
      are a DB-layer concern with no UI surface at all. Real coverage:
      test_passkey_enumeration.py::test_register_begin_decoy_path_writes_no_
      db_rows and test_invites.py::test_redeem_begin_expired_token_writes_
      no_user_row (both pre-existing, unweakened by this issue).

  AC5 (#239 shape / #255 timing / #267 size guarantees still hold) -- the
      weakest of the six to approximate in a browser: the register form can
      be driven for both an authorized and an unauthorized email and shown
      to reach the same generic next-step UI, which is the browser-visible
      echo of the shape guarantee (same pattern as
      test_e2e_invites.py::test_invite_landing_page_shows_same_generic_
      failure_for_any_bad_token). Timing and byte-for-byte size are not
      meaningfully measurable in headless Playwright (see that file's AC10
      note) -- those stay HTTP-level only. Kept as a stub here since the
      shape half is at least attemptable; promote or downgrade to
      xfail(strict=False) once real assertions are written, matching the
      established timing-caveat pattern.

  AC6 (regression test asserts stability across TWO calls, not one) -- NOT a
      browser-observable *behaviour* at all: it is a statement about test
      design (test_register_begin_authorized_and_unauthorized_shapes_match's
      single-call gap), not something the running app exposes differently.
      There is no UI action that corresponds to "assert on two calls instead
      of one" -- that is purely a property of how the HTTP-layer test is
      written. Kept as a stub only for symmetry with the other five ACs;
      expect this one to be removed rather than promoted, with a comment
      pointing at the HTTP-layer test that actually encodes the two-call
      requirement (test_register_begin_decoy_user_id_stable_then_secret_
      dependent, which fails specifically because it compares two calls).
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e


# ── AC1 ───────────────────────────────────────────────────────────────────


@pytest.mark.xfail(
    strict=True,
    reason=(
        "not implemented -- and see module docstring: this AC is a raw "
        "JSON-field stability claim across two HTTP responses, not "
        "genuinely observable through a WebAuthn ceremony headless "
        "Chromium cannot complete. Real coverage is at the HTTP layer."
    ),
)
def test_register_begin_user_id_never_stable_on_one_path_and_random_on_other(
    page: Page,
) -> None:
    pytest.fail("not implemented")


# ── AC2 ───────────────────────────────────────────────────────────────────


@pytest.mark.xfail(
    strict=True,
    reason=(
        "not implemented -- same limitation as AC1, for both "
        "register_passkey_begin and invite_redeem_begin. Real coverage is "
        "at the HTTP layer in test_passkey_enumeration.py and "
        "test_invites.py."
    ),
)
def test_stability_guarantee_holds_for_both_register_and_invite_redeem(
    page: Page,
) -> None:
    pytest.fail("not implemented")


# ── AC3 ───────────────────────────────────────────────────────────────────


@pytest.mark.xfail(
    strict=True,
    reason=(
        "not implemented -- and not browser-verifiable at all: the browser "
        "has no way to observe or vary the server's JWT_SECRET. Real "
        "coverage is at the HTTP layer via monkeypatched config.JWT_SECRET."
    ),
)
def test_decoy_user_id_is_not_derivable_from_email_alone(page: Page) -> None:
    pytest.fail("not implemented")


# ── AC4 ───────────────────────────────────────────────────────────────────


@pytest.mark.xfail(
    strict=True,
    reason=(
        "not implemented -- and not browser-verifiable: DB row counts have "
        "no UI surface. Real coverage is at the HTTP/DB layer."
    ),
)
def test_decoy_paths_still_write_no_db_rows(page: Page) -> None:
    pytest.fail("not implemented")


# ── AC5 ───────────────────────────────────────────────────────────────────


@pytest.mark.xfail(
    strict=True,
    reason=(
        "not implemented -- the shape half (authorized vs unauthorized "
        "email reach the same generic next-step UI) is attemptable in a "
        "browser; the timing and byte-for-byte size halves are not "
        "meaningfully measurable in headless Playwright and stay "
        "HTTP-level only, matching test_e2e_invites.py's AC10 precedent."
    ),
)
def test_register_form_reaches_same_next_step_for_authorized_and_unauthorized_email(
    page: Page,
) -> None:
    pytest.fail("not implemented")


# ── AC6 ───────────────────────────────────────────────────────────────────


@pytest.mark.xfail(
    strict=True,
    reason=(
        "not implemented -- and likely not promotable at all: this AC "
        "describes a gap in how an existing HTTP-layer test was written "
        "(single-call comparison), not a behaviour the running app exposes "
        "differently in a browser. Expect this to be removed once the "
        "HTTP-layer two-call regression test "
        "(test_register_begin_decoy_user_id_stable_then_secret_dependent) "
        "is confirmed failing for the right reason, rather than promoted "
        "to a real Playwright assertion."
    ),
)
def test_two_call_regression_is_exercised_not_just_single_call_width(
    page: Page,
) -> None:
    pytest.fail("not implemented")
