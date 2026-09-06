"""E2E tests for issue #174 — session segment model (parent PRD #172).

One Playwright browser test per acceptance criterion, following the same
fixture/driver pattern as the other test_e2e_*.py files: synthetic JWT
tokens injected as cookies, `page.request` used to seed state via the API,
then real UI assertions via Playwright (AC1/AC2/AC4). AC3 and AC5 are
verified at the API layer with httpx, matching the style already used for
backend-only behaviour with no dedicated UI surface (see test_ical.py).
"""

from __future__ import annotations

import datetime
import json
import os
import uuid

import httpx
from dotenv import load_dotenv
from playwright.sync_api import Page, expect

_dotenv_path = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path=_dotenv_path, override=False)
os.environ.setdefault("JWT_SECRET", "test-secret-not-for-production")

from app import config as _config  # noqa: E402
from app.auth.models import UserClaims  # noqa: E402
from app.auth.token import encode_token  # noqa: E402
from tests.e2e_support import complete_onboarding  # noqa: E402

_config.JWT_SECRET = os.environ["JWT_SECRET"]

BASE_URL = "http://localhost:5173"
API_URL = "http://localhost:8000/api"


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


def _make_token(role: str) -> str:
    claims = UserClaims(
        sub=str(uuid.uuid4()),
        email=f"{role}-{uuid.uuid4().hex[:6]}@dojo.test",
        role=role,  # type: ignore[arg-type]
        is_active=True,
    )
    token = encode_token(claims)
    # Seed the acting user's Member profile so the RequireProfile gate does
    # not bounce every navigation to /onboarding before assertions run (#221).
    complete_onboarding(token)
    return token


def _set_cookie(page: Page, token: str) -> None:
    page.goto(BASE_URL)
    page.context.add_cookies(
        [{"name": "access_token", "value": token, "url": BASE_URL}]
    )


def _api_headers(token: str) -> dict:
    return {"Cookie": f"access_token={token}"}


def _get_type_ids(page: Page, admin_token: str, count: int = 2) -> list[str]:
    resp = page.request.get(
        f"{API_URL}/session-types", headers=_api_headers(admin_token)
    )
    assert resp.status == 200
    types = resp.json()
    assert len(types) >= count, "Not enough seeded session types for this test"
    return [t["id"] for t in types[:count]]


# ---------------------------------------------------------------------------
# AC1 — A session can be created/read via the nested `segments` payload with
# one segment, and the created session is visible in the UI.
# ---------------------------------------------------------------------------


def test_session_created_via_nested_segments_payload_with_one_segment(
    page: Page,
) -> None:
    admin_token = _make_token("admin")
    type_id = _get_type_ids(page, admin_token, count=1)[0]

    create_resp = page.request.post(
        f"{API_URL}/sessions",
        headers={**_api_headers(admin_token), "Content-Type": "application/json"},
        data=json.dumps(
            {
                "title": "Single Segment Keiko",
                "date": "2099-09-11",
                "segments": [
                    {
                        "start_time": "19:00",
                        "duration_minutes": 90,
                        "type_ids": [type_id],
                    }
                ],
            }
        ),
    )
    assert (
        create_resp.status == 201
    ), f"Expected 201, got {create_resp.status}: {create_resp.text()}"
    created = create_resp.json()
    session_id = created["id"]
    assert created["title"] == "Single Segment Keiko"
    assert len(created["segments"]) == 1
    assert created["segments"][0]["type_ids"] == [type_id]
    # Derived envelope from the single segment
    assert created["start_time"] == "19:00"
    assert created["duration_minutes"] == 90

    # The created session is visible in the UI (session detail page). Rely on
    # expect()'s auto-retry rather than networkidle, which races the SPA fetch.
    _set_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/sessions/{session_id}")
    expect(page.get_by_role("heading", name="Single Segment Keiko")).to_be_visible(
        timeout=15000
    )


# ---------------------------------------------------------------------------
# AC2 — Session has a required title; session-level type/time/duration
# columns are gone — the create form requires a title and no longer exposes
# a single top-level type/time/duration field.
# ---------------------------------------------------------------------------


def test_session_has_required_title_and_no_legacy_type_time_duration_fields(
    page: Page,
) -> None:
    admin_token = _make_token("admin")
    type_id = _get_type_ids(page, admin_token, count=1)[0]

    # Server-side: a session without a title is rejected.
    no_title_resp = page.request.post(
        f"{API_URL}/sessions",
        headers={**_api_headers(admin_token), "Content-Type": "application/json"},
        data=json.dumps(
            {
                "date": "2099-09-12",
                "segments": [
                    {
                        "start_time": "19:00",
                        "duration_minutes": 60,
                        "type_ids": [type_id],
                    }
                ],
            }
        ),
    )
    assert no_title_resp.status == 422

    # Server-side: a session created via segments has no legacy
    # session_type_id column on the response.
    created_resp = page.request.post(
        f"{API_URL}/sessions",
        headers={**_api_headers(admin_token), "Content-Type": "application/json"},
        data=json.dumps(
            {
                "title": "No Legacy Columns",
                "date": "2099-09-13",
                "segments": [
                    {
                        "start_time": "19:00",
                        "duration_minutes": 60,
                        "type_ids": [type_id],
                    }
                ],
            }
        ),
    )
    assert created_resp.status == 201
    assert "session_type_id" not in created_resp.json()

    # Client-side: the create dialog exposes a required Title field. Submitting
    # without a title triggers form-level validation ("Title is required.")
    # before any request — the form checks the title first, so we don't need to
    # touch the (Radix) type select to prove the title is required.
    _set_cookie(page, admin_token)
    page.goto(f"{BASE_URL}/sessions")
    # Only the toolbar trigger exists until the dialog opens.
    page.get_by_role("button", name="Create Session").click()

    dialog = page.get_by_role("dialog")
    # The session Title field (#session-title); a plain "Title" label also matches
    # the per-segment title input, so scope to the session field to stay unambiguous.
    # It is marked `required`, so the browser blocks submission of an empty title
    # via native validation — assert the requirement through the attribute rather
    # than a custom in-form message (which native validation pre-empts).
    title_field = dialog.locator("#session-title")
    expect(title_field).to_be_visible()
    expect(title_field).to_have_attribute("required", "")


# ---------------------------------------------------------------------------
# AC3 — Server rejects a session with no segments, a segment with no type,
# and a segment with duration <= 0. Verified at the API layer: the create
# form always builds a single, valid segment from its own required fields
# (title, type, time, positive duration), so these invalid combinations are
# never reachable from the UI — they can only be sent directly to the API.
# ---------------------------------------------------------------------------


def test_server_rejects_invalid_segment_combinations() -> None:
    admin_token = _make_token("admin")
    types_resp = httpx.get(
        f"{API_URL}/session-types",
        headers={"Cookie": f"access_token={admin_token}"},
    )
    assert types_resp.status_code == 200
    type_id = types_resp.json()[0]["id"]
    headers = {"Cookie": f"access_token={admin_token}"}

    # No segments at all.
    no_segments_resp = httpx.post(
        f"{API_URL}/sessions",
        headers=headers,
        json={"title": "No Segments", "date": "2099-09-15", "segments": []},
    )
    assert no_segments_resp.status_code == 422

    # A segment with no type.
    no_type_resp = httpx.post(
        f"{API_URL}/sessions",
        headers=headers,
        json={
            "title": "Segment Without Type",
            "date": "2099-09-16",
            "segments": [
                {"start_time": "19:00", "duration_minutes": 60, "type_ids": []}
            ],
        },
    )
    assert no_type_resp.status_code == 422

    # A segment with duration <= 0.
    zero_duration_resp = httpx.post(
        f"{API_URL}/sessions",
        headers=headers,
        json={
            "title": "Zero Duration Segment",
            "date": "2099-09-17",
            "segments": [
                {
                    "start_time": "19:00",
                    "duration_minutes": 0,
                    "type_ids": [type_id],
                }
            ],
        },
    )
    assert zero_duration_resp.status_code == 422

    negative_duration_resp = httpx.post(
        f"{API_URL}/sessions",
        headers=headers,
        json={
            "title": "Negative Duration Segment",
            "date": "2099-09-18",
            "segments": [
                {
                    "start_time": "19:00",
                    "duration_minutes": -15,
                    "type_ids": [type_id],
                }
            ],
        },
    )
    assert negative_duration_resp.status_code == 422


# ---------------------------------------------------------------------------
# AC4 — Calendar chip shows the title plus a colour pip per distinct type;
# the detail view shows the segment breakdown.
# ---------------------------------------------------------------------------


def test_calendar_chip_shows_title_and_colour_pip_per_distinct_type(
    page: Page,
) -> None:
    admin_token = _make_token("admin")

    # Capture the two types (id + original colour) up front so colours can be
    # restored afterwards — otherwise this test pollutes others that assert on
    # seeded type colours.
    types_resp = page.request.get(
        f"{API_URL}/session-types", headers=_api_headers(admin_token)
    )
    assert types_resp.status == 200
    all_types = types_resp.json()
    assert len(all_types) >= 2, "Need at least two seeded session types"
    type_a, type_b = all_types[0], all_types[1]
    type_a_id, type_b_id = type_a["id"], type_b["id"]

    def _set_colour(type_id: str, colour: str | None) -> None:
        page.request.put(
            f"{API_URL}/session-types/{type_id}",
            headers={**_api_headers(admin_token), "Content-Type": "application/json"},
            data=json.dumps({"colour": colour}),
        )

    # Give both types a colour so the pips are visible.
    _set_colour(type_a_id, "#ff0000")
    _set_colour(type_b_id, "#00ff00")
    try:
        # A near-future month keeps month navigation to a couple of clicks while
        # staying stable regardless of when the test runs (mid-month avoids any
        # month-boundary ambiguity).
        target = datetime.date.today() + datetime.timedelta(days=70)
        target = target.replace(day=15)
        session_date = target.isoformat()
        month_label = target.strftime("%B %Y")

        create_resp = page.request.post(
            f"{API_URL}/sessions",
            headers={**_api_headers(admin_token), "Content-Type": "application/json"},
            data=json.dumps(
                {
                    "title": "Multi-Type Block",
                    "date": session_date,
                    "segments": [
                        {
                            "start_time": "09:00",
                            "duration_minutes": 60,
                            "type_ids": [type_a_id],
                        },
                        {
                            "start_time": "10:00",
                            "duration_minutes": 45,
                            "type_ids": [type_b_id],
                        },
                    ],
                }
            ),
        )
        assert create_resp.status == 201, create_resp.text()
        session_id = create_resp.json()["id"]

        # Calendar month grid (home dashboard, desktop). Navigate to the
        # session's month, then assert the chip shows the title + one pip per
        # distinct type.
        _set_cookie(page, admin_token)
        page.goto(BASE_URL)
        period_span = page.locator("span.flex-1.text-center")
        for _ in range(24):
            if period_span.inner_text(timeout=5000) == month_label:
                break
            page.get_by_role("button", name="Next period").click()
        else:
            raise AssertionError(f"Could not navigate to {month_label}")

        chip = page.get_by_role("button", name="Multi-Type Block", exact=False).first
        expect(chip).to_be_visible(timeout=10000)

        pips = chip.locator("span.rounded-full")
        expect(pips).to_have_count(2)

        # Detail view shows the segment breakdown — both type names visible.
        page.goto(f"{BASE_URL}/sessions/{session_id}")
        expect(page.get_by_text("Segments")).to_be_visible(timeout=15000)
        name_by_id = {t["id"]: t["name"] for t in all_types}
        expect(page.get_by_text(name_by_id[type_a_id]).first).to_be_visible()
        expect(page.get_by_text(name_by_id[type_b_id]).first).to_be_visible()
    finally:
        # Restore original colours regardless of assertion outcome.
        _set_colour(type_a_id, type_a.get("colour"))
        _set_colour(type_b_id, type_b.get("colour"))


# ---------------------------------------------------------------------------
# AC5 — iCal still produces one VEVENT per session (envelope time +
# per-segment DESCRIPTION; private fields excluded) — verified against the
# live /sessions/ical feed.
# ---------------------------------------------------------------------------


def test_ical_feed_produces_one_vevent_with_envelope_and_segment_description() -> None:
    admin_token = _make_token("admin")
    headers = {"Cookie": f"access_token={admin_token}"}
    types_resp = httpx.get(f"{API_URL}/session-types", headers=headers)
    assert types_resp.status_code == 200
    type_id = types_resp.json()[0]["id"]
    type_name = types_resp.json()[0]["name"]

    create_resp = httpx.post(
        f"{API_URL}/sessions",
        headers=headers,
        json={
            "title": "iCal Envelope Session",
            "date": "2099-09-20",
            "coach_notes": "SECRET coach-only note",
            "segments": [
                {
                    "start_time": "09:00",
                    "duration_minutes": 60,
                    "coach_notes": "SECRET segment note",
                    "type_ids": [type_id],
                },
                {
                    "start_time": "10:00",
                    "duration_minutes": 30,
                    "type_ids": [type_id],
                },
            ],
        },
    )
    assert create_resp.status_code == 201
    session_id = create_resp.json()["id"]

    ical_resp = httpx.get(f"{API_URL}/sessions/ical")
    assert ical_resp.status_code == 200
    body = ical_resp.text

    # Exactly one VEVENT for this session.
    vevent_blocks = [
        block
        for block in body.split("BEGIN:VEVENT")[1:]
        if f"UID:{session_id}" in block.split("END:VEVENT")[0]
    ]
    assert len(vevent_blocks) == 1, (
        f"Expected exactly one VEVENT for session {session_id}, "
        f"found {len(vevent_blocks)}"
    )
    vevent = vevent_blocks[0]

    # Envelope time spans both segments: 09:00 -> 10:30 (dojo-local wall time,
    # tagged with a TZID now that the feed is timezone-anchored, not floating).
    assert "DTSTART;TZID=" in vevent
    assert "20990920T090000" in vevent
    assert "20990920T103000" in vevent

    # DESCRIPTION carries the per-segment breakdown with the type name.
    description_line = next(
        line
        for line in vevent.replace("\r\n", "\n").split("\n")
        if line.startswith("DESCRIPTION:")
    )
    assert "09:00-10:00" in description_line
    assert "10:00-10:30" in description_line
    assert type_name in description_line

    # Coach notes (session-level and per-segment) never appear.
    assert "SECRET coach-only note" not in body
    assert "SECRET segment note" not in body
