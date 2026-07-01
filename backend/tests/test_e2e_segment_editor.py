"""E2E tests for issue #175 — multi-segment, multi-type create/edit form.

One test per acceptance criterion (AC1–AC6). Promoted from xfail stubs to real
Playwright assertions against the live UI at http://localhost:5173.

Auth/cookie setup and API-seeding pattern mirrors test_e2e_segments.py.
"""

from __future__ import annotations

import json
import os
import uuid

import pytest
from dotenv import load_dotenv
from playwright.sync_api import Page, expect

_dotenv_path = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path=_dotenv_path, override=False)
os.environ.setdefault("JWT_SECRET", "test-secret-not-for-production")

from app import config as _config  # noqa: E402
from app.auth.models import UserClaims  # noqa: E402
from app.auth.token import encode_token  # noqa: E402

_config.JWT_SECRET = os.environ["JWT_SECRET"]

BASE_URL = "http://localhost:5173"
API_URL = "http://localhost:8000"


# ---------------------------------------------------------------------------
# Auth helpers (same pattern as test_e2e_segments.py)
# ---------------------------------------------------------------------------


def _make_token(role: str) -> str:
    claims = UserClaims(
        sub=str(uuid.uuid4()),
        email=f"{role}-{uuid.uuid4().hex[:6]}@dojo.test",
        role=role,  # type: ignore[arg-type]
        is_active=True,
    )
    return encode_token(claims)


def _set_cookie(page: Page, token: str) -> None:
    page.goto(BASE_URL)
    page.context.add_cookies(
        [{"name": "access_token", "value": token, "url": BASE_URL}]
    )


def _api_headers(token: str) -> dict:
    return {"Cookie": f"access_token={token}"}


def _seed_profile(page: Page, token: str) -> None:
    """Create the member record linked to ``token``'s sub via PUT /users/me/member.

    Authenticated app routes (/sessions, /sessions/:id) sit behind the
    ``RequireProfile`` gate, which redirects to /onboarding when the caller has
    no member profile. Seeding a profile lets the test reach the real page.
    Mirrors the helper used by the other passing nav e2e tests
    (test_e2e_settings.py, test_e2e_grade_approval.py).
    """
    resp = page.request.put(
        f"{API_URL}/users/me/member",
        headers={**_api_headers(token), "Content-Type": "application/json"},
        data=json.dumps(
            {"first_name": "Test", "surname": "Admin", "dob": "1990-01-01"}
        ),
    )
    assert resp.status in (200, 201), f"Profile seed failed: {resp.status} {resp.text()}"


def _get_type_ids(page: Page, admin_token: str, count: int = 2) -> list[str]:
    resp = page.request.get(
        f"{API_URL}/session-types", headers=_api_headers(admin_token)
    )
    assert resp.status == 200
    types = resp.json()
    assert len(types) >= count, "Not enough seeded session types for this test"
    return [t["id"] for t in types[:count]]


def _create_session(page: Page, admin_token: str, payload: dict) -> dict:
    resp = page.request.post(
        f"{API_URL}/sessions",
        headers={**_api_headers(admin_token), "Content-Type": "application/json"},
        data=json.dumps(payload),
    )
    assert resp.status == 201, f"Expected 201, got {resp.status}: {resp.text()}"
    return resp.json()


# ---------------------------------------------------------------------------
# AC1 — Admin can add/remove multiple segments in the CREATE dialog
# ---------------------------------------------------------------------------


def test_create_dialog_supports_adding_and_removing_multiple_segments(
    page: Page,
) -> None:
    """AC1: Admin can add/remove multiple segments in the create dialog."""
    admin_token = _make_token("admin")
    type_id = _get_type_ids(page, admin_token, count=1)[0]

    _seed_profile(page, admin_token)
    _set_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/sessions")
    page.get_by_role("button", name="Create Session").click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_be_visible(timeout=10_000)

    # 3. "Add segment" button is present
    add_btn = dialog.get_by_role("button", name="Add segment")
    expect(add_btn).to_be_visible()

    # 4. Click "Add segment" — two segment rows visible
    add_btn.click()
    expect(dialog.locator('[aria-label="Segment 1"]')).to_be_visible()
    expect(dialog.locator('[aria-label="Segment 2"]')).to_be_visible()

    # 5. Remove segment 2 — only one remains
    dialog.locator('[aria-label="Segment 2"]').get_by_role(
        "button", name="Remove segment"
    ).click()
    expect(dialog.locator('[aria-label="Segment 2"]')).not_to_be_visible()
    expect(dialog.locator('[aria-label="Segment 1"]')).to_be_visible()

    # 6. Fill required fields and submit with the remaining single segment
    dialog.get_by_label("Title").fill("AC1 Multi-Segment Test")
    dialog.get_by_label("Date").fill("2099-11-01")
    seg1 = dialog.locator('[aria-label="Segment 1"]')
    seg1.get_by_label("Start time").fill("19:00")
    # Click the type checkbox for segment 0 (0-indexed ids, 1-indexed aria-label)
    dialog.locator(f'[id="seg-0-type-{type_id}"]').click()
    dialog.get_by_role("button", name="Create Session").click()

    # Dialog closes; session appears in the list
    expect(page.get_by_text("AC1 Multi-Segment Test", exact=False)).to_be_visible(
        timeout=10_000
    )


# ---------------------------------------------------------------------------
# AC2 — A segment can hold multiple types; overlapping segments and duplicate
# types across segments are accepted.
# ---------------------------------------------------------------------------


def test_segment_supports_multiple_types_and_overlapping_segments_are_accepted(
    page: Page,
) -> None:
    """AC2: Multiple types per segment; overlapping/duplicate types accepted."""
    admin_token = _make_token("admin")
    type_ids = _get_type_ids(page, admin_token, count=2)
    type_a, type_b = type_ids[0], type_ids[1]

    _seed_profile(page, admin_token)
    _set_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/sessions")
    page.get_by_role("button", name="Create Session").click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_be_visible(timeout=10_000)

    # 2. In segment 1, select both type_a and type_b — both chips/checkboxes active
    dialog.get_by_label("Title").fill("AC2 Multi-Type Test")
    dialog.get_by_label("Date").fill("2099-11-02")
    seg1 = dialog.locator('[aria-label="Segment 1"]')
    seg1.get_by_label("Start time").fill("19:00")
    dialog.locator(f'[id="seg-0-type-{type_a}"]').click()
    dialog.locator(f'[id="seg-0-type-{type_b}"]').click()
    # Both checkboxes should now be checked
    expect(dialog.locator(f'[id="seg-0-type-{type_a}"]')).to_have_attribute(
        "aria-checked", "true"
    )
    expect(dialog.locator(f'[id="seg-0-type-{type_b}"]')).to_have_attribute(
        "aria-checked", "true"
    )

    # 3. Add a second segment with the same type_a (duplicate type across segments)
    dialog.get_by_role("button", name="Add segment").click()
    seg2 = dialog.locator('[aria-label="Segment 2"]')
    # New segment starts with no type; select type_a (same as segment 1)
    dialog.locator(f'[id="seg-1-type-{type_a}"]').click()

    # 4. Set both segments to the same start_time (overlapping) — no validation error
    seg2.get_by_label("Start time").fill("19:00")

    # 5. Submit — should succeed (no error shown, dialog closes)
    dialog.get_by_role("button", name="Create Session").click()
    # If validation fails, the dialog stays open and shows an error.
    # Successful submission closes the dialog and shows the session in the list.
    expect(dialog).not_to_be_visible(timeout=10_000)
    expect(page.get_by_text("AC2 Multi-Type Test", exact=False)).to_be_visible(
        timeout=10_000
    )

    # Verify via API that segment 1 has 2 type_ids
    sessions_resp = page.request.get(
        f"{API_URL}/sessions", headers=_api_headers(admin_token)
    )
    our_session = next(
        (s for s in sessions_resp.json() if s["title"] == "AC2 Multi-Type Test"), None
    )
    assert our_session is not None, "Created session not found in list"
    detail_resp = page.request.get(
        f"{API_URL}/sessions/{our_session['id']}", headers=_api_headers(admin_token)
    )
    detail = detail_resp.json()
    assert len(detail["segments"][0]["type_ids"]) == 2, (
        f"Expected 2 types in segment 1, got {detail['segments'][0]['type_ids']}"
    )


# ---------------------------------------------------------------------------
# AC3 — Each segment can carry optional coach notes
# ---------------------------------------------------------------------------


def test_each_segment_row_has_optional_coach_notes_field(
    page: Page,
) -> None:
    """AC3: Each segment in the editor exposes an optional coach notes field."""
    admin_token = _make_token("admin")
    type_id = _get_type_ids(page, admin_token, count=1)[0]

    _seed_profile(page, admin_token)
    _set_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/sessions")
    page.get_by_role("button", name="Create Session").click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_be_visible(timeout=10_000)

    # 2. First segment has a "Coach notes" input
    seg1 = dialog.locator('[aria-label="Segment 1"]')
    expect(seg1.get_by_label("Coach notes")).to_be_visible()

    # 3. Fill the coach note for segment 1
    seg1.get_by_label("Coach notes").fill("Per-segment admin note")

    # 4. Add a second segment — it also has its own "Coach notes" field
    dialog.get_by_role("button", name="Add segment").click()
    seg2 = dialog.locator('[aria-label="Segment 2"]')
    expect(seg2.get_by_label("Coach notes")).to_be_visible()
    # The two fields are independent: segment 2 starts empty
    expect(seg2.get_by_label("Coach notes")).to_have_value("")
    # Fill segment 2 note with a different value
    seg2.get_by_label("Coach notes").fill("Segment 2 note")

    # Fill required fields for both segments
    dialog.get_by_label("Title").fill("AC3 Coach Notes Test")
    dialog.get_by_label("Date").fill("2099-11-03")
    seg1.get_by_label("Start time").fill("18:00")
    seg2.get_by_label("Start time").fill("19:00")
    dialog.locator(f'[id="seg-0-type-{type_id}"]').click()
    dialog.locator(f'[id="seg-1-type-{type_id}"]').click()
    dialog.get_by_role("button", name="Create Session").click()

    # Wait for dialog to close
    expect(dialog).not_to_be_visible(timeout=10_000)

    # 5–6. Verify via API that segment 1's coach_notes was persisted
    sessions_resp = page.request.get(
        f"{API_URL}/sessions", headers=_api_headers(admin_token)
    )
    our_session = next(
        (s for s in sessions_resp.json() if s["title"] == "AC3 Coach Notes Test"), None
    )
    assert our_session is not None, "Created session not found in list"
    detail_resp = page.request.get(
        f"{API_URL}/sessions/{our_session['id']}", headers=_api_headers(admin_token)
    )
    detail = detail_resp.json()
    assert detail["segments"][0]["coach_notes"] == "Per-segment admin note", (
        f"Segment 1 coach_notes mismatch: {detail['segments'][0]['coach_notes']!r}"
    )


# ---------------------------------------------------------------------------
# AC4 — The editor is usable on a narrow (mobile) screen: stacked cards,
# mirrors existing table/card responsive pattern.
# ---------------------------------------------------------------------------


def test_segment_editor_is_usable_on_mobile_viewport(
    page: Page,
) -> None:
    """AC4: The segment editor renders in a stacked-card layout on mobile."""
    admin_token = _make_token("admin")
    _get_type_ids(page, admin_token, count=1)  # ensure session types are seeded

    # 1. Set viewport to 375×667 (iPhone SE)
    page.set_viewport_size({"width": 375, "height": 667})

    _seed_profile(page, admin_token)
    _set_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/sessions")
    page.get_by_role("button", name="Create Session").click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_be_visible(timeout=10_000)

    # 3. No horizontal scroll — dialog scrollWidth <= clientWidth
    scroll_ok: bool = dialog.evaluate(
        "el => el.scrollWidth <= el.clientWidth + 2"
    )
    assert scroll_ok, "Dialog has horizontal overflow on mobile (375px)"

    # 4. "Add segment" button is visible without horizontal scrolling
    add_btn = dialog.get_by_role("button", name="Add segment")
    expect(add_btn).to_be_visible()

    # 5. Segment field labels are visible (not clipped off-screen)
    seg1 = dialog.locator('[aria-label="Segment 1"]')
    expect(seg1.get_by_text("Start time", exact=True)).to_be_visible()
    expect(seg1.get_by_text("Duration (minutes)", exact=True)).to_be_visible()
    expect(seg1.get_by_text("Coach notes", exact=True)).to_be_visible()

    # 6. Add a second segment — both rows still reachable without horizontal scroll
    add_btn.click()
    expect(dialog.locator('[aria-label="Segment 2"]')).to_be_visible()
    scroll_ok_after: bool = dialog.evaluate(
        "el => el.scrollWidth <= el.clientWidth + 2"
    )
    assert scroll_ok_after, "Dialog has horizontal overflow after adding second segment"


# ---------------------------------------------------------------------------
# AC5 — Single-segment creation remains a simple one-screen flow
# ---------------------------------------------------------------------------


def test_single_segment_create_is_a_simple_one_screen_flow(
    page: Page,
) -> None:
    """AC5: The create dialog with one segment is a simple, familiar flow."""
    admin_token = _make_token("admin")
    type_id = _get_type_ids(page, admin_token, count=1)[0]

    _seed_profile(page, admin_token)
    _set_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/sessions")
    page.get_by_role("button", name="Create Session").click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_be_visible(timeout=10_000)

    # 2. Dialog opens with exactly one segment row — no wizard / multi-step prompt
    expect(dialog.locator('[aria-label^="Segment"]')).to_have_count(1)
    # No "Next" or "Step N of M" wizard UI
    expect(dialog.get_by_role("button", name="Next")).not_to_be_visible()

    # 3. Fill title, date, type, start_time, duration
    dialog.get_by_label("Title").fill("AC5 Single Segment Flow")
    dialog.get_by_label("Date").fill("2099-11-05")
    seg1 = dialog.locator('[aria-label="Segment 1"]')
    seg1.get_by_label("Start time").fill("19:00")
    seg1.get_by_label("Duration (minutes)").fill("90")
    dialog.locator(f'[id="seg-0-type-{type_id}"]').click()

    # 4. Submit button is enabled (not disabled before submission)
    submit_btn = dialog.get_by_role("button", name="Create Session")
    expect(submit_btn).to_be_enabled()

    # 5. Submit — session appears in the session list
    submit_btn.click()
    expect(dialog).not_to_be_visible(timeout=10_000)
    expect(page.get_by_text("AC5 Single Segment Flow", exact=False)).to_be_visible(
        timeout=10_000
    )


# ---------------------------------------------------------------------------
# AC6 — Editing replaces the full segment set transactionally (edit form)
# ---------------------------------------------------------------------------


def test_edit_form_replaces_full_segment_set_on_save(
    page: Page,
) -> None:
    """AC6: Editing a session via the edit form replaces all segments."""
    admin_token = _make_token("admin")
    type_ids = _get_type_ids(page, admin_token, count=2)
    type_a, type_b = type_ids[0], type_ids[1]

    # 1. Seed a session with two segments via the API
    created = _create_session(
        page,
        admin_token,
        {
            "title": "AC6 Edit Segments Test",
            "date": "2099-11-06",
            "segments": [
                {
                    "start_time": "18:00",
                    "duration_minutes": 60,
                    "type_ids": [type_a],
                },
                {
                    "start_time": "19:00",
                    "duration_minutes": 60,
                    "type_ids": [type_b],
                },
            ],
        },
    )
    session_id = created["id"]

    # 2. Navigate to the session detail page as admin
    _seed_profile(page, admin_token)
    _set_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/sessions/{session_id}")
    expect(
        page.get_by_role("heading", name="AC6 Edit Segments Test")
    ).to_be_visible(timeout=15_000)

    # 3. Open the edit form — both segments pre-populated
    page.get_by_role("button", name="Edit").click()
    expect(page.locator('[aria-label="Segment 1"]')).to_be_visible(timeout=10_000)
    expect(page.locator('[aria-label="Segment 2"]')).to_be_visible()

    # 4. Remove segment 2 — only segment 1 remains
    page.locator('[aria-label="Segment 2"]').get_by_role(
        "button", name="Remove segment"
    ).click()
    expect(page.locator('[aria-label="Segment 2"]')).not_to_be_visible()

    # 5. Add a new segment with a different type and time
    page.get_by_role("button", name="Add segment").click()
    new_seg = page.locator('[aria-label="Segment 2"]')
    expect(new_seg).to_be_visible()
    new_seg.get_by_label("Start time").fill("20:00")
    # Select type_b for the new segment (different from the seeded segment 2's type)
    page.locator(f'[id="seg-1-type-{type_b}"]').click()

    # 6. Save
    page.get_by_role("button", name="Save").click()
    # After save the edit form is dismissed and we're back on the detail page
    expect(page.get_by_role("heading", name="AC6 Edit Segments Test")).to_be_visible(
        timeout=10_000
    )

    # 6 (cont). Verify via API: exactly 2 segments (not 3)
    detail_resp = page.request.get(
        f"{API_URL}/sessions/{session_id}", headers=_api_headers(admin_token)
    )
    detail = detail_resp.json()
    assert len(detail["segments"]) == 2, (
        f"Expected 2 segments after edit, got {len(detail['segments'])}"
    )

    # 7. Reload and verify the segment set matches (removed segment is gone)
    page.reload()
    expect(
        page.get_by_role("heading", name="AC6 Edit Segments Test")
    ).to_be_visible(timeout=15_000)
    # Open edit form to count the current segments
    page.get_by_role("button", name="Edit").click()
    expect(page.locator('[aria-label="Segment 1"]')).to_be_visible(timeout=10_000)
    expect(page.locator('[aria-label="Segment 2"]')).to_be_visible()
    expect(page.locator('[aria-label="Segment 3"]')).not_to_be_visible()
