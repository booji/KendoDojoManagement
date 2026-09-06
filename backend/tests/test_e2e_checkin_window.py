"""
Playwright browser tests for issue #192 — check-in window enforcement
with dojo-wide defaults.

Scope: DOJO-WIDE DEFAULTS ONLY. Per-session override columns are a separate,
later slice and are out of scope here.

One test per relevant acceptance criterion:
  7. Check-in page renders a too-early state ("opens at …").
  7. Check-in page renders a closed state ("closed at …").
  3. Admin settings page has a "Check-in window" card with the two default
     minute inputs.
  3. Admin settings "Check-in window" card validates non-negative integers
     <= 1440.

Auth pattern follows test_e2e_attendance.py / test_e2e_admin_settings.py:
JWT tokens are generated directly and injected as cookies. Tests that
navigate to a profile-gated page (anything under RequireProfile in App.tsx —
which includes /checkin/session/:id and /admin/settings) also insert a
complete member row via asyncpg, following test_e2e_onboarding.py's
_insert_complete_member pattern, so the RequireProfile gate doesn't redirect
to /onboarding first.

Window math relies on the dojo-wide defaults seeded in
app/settings/repository.py: checkin_window_before_minutes=60,
checkin_window_after_minutes=120. Sessions are scheduled with enough margin
(hours, not minutes) around those defaults so the assertions aren't flaky
near the boundary.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
import uuid
from datetime import datetime, timedelta

import asyncpg
from dotenv import load_dotenv
from playwright.sync_api import Page, expect

# Load the real JWT_SECRET from .env so tokens pass server-side validation.
_dotenv_path = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path=_dotenv_path, override=False)
os.environ.setdefault("JWT_SECRET", "test-secret-not-for-production")

from app import config as _config  # noqa: E402
from app.auth.models import UserClaims  # noqa: E402
from app.auth.token import encode_token  # noqa: E402

_config.JWT_SECRET = os.environ["JWT_SECRET"]

BASE_URL = "http://localhost:5173"
API_URL = "http://localhost:8000/api"


# ── helpers (mirrors test_e2e_attendance.py) ────────────────────────────────


def _make_token(role: str) -> str:
    claims = UserClaims(
        sub=str(uuid.uuid4()),
        email=f"{role}_{uuid.uuid4().hex[:6]}@dojo.test",
        role=role,  # type: ignore[arg-type]
        is_active=True,
    )
    return encode_token(claims)


def _set_cookie(page: Page, token: str) -> None:
    page.context.add_cookies(
        [{"name": "access_token", "value": token, "url": BASE_URL}]
    )


def _make_user_with_complete_profile(role: str) -> str:
    """Create a JWT for `role` and a matching complete member row (via
    asyncpg, mirroring test_e2e_onboarding.py's _insert_complete_member
    helper) so the RequireProfile gate does not redirect to /onboarding
    before the target page can render."""
    claims = UserClaims(
        sub=str(uuid.uuid4()),
        email=f"{role}_{uuid.uuid4().hex[:6]}@dojo.test",
        role=role,  # type: ignore[arg-type]
        is_active=True,
    )
    token = encode_token(claims)

    db_url = os.environ["DATABASE_URL"].replace(
        "postgresql+asyncpg://", "postgresql://"
    )

    async def _insert() -> None:
        conn = await asyncpg.connect(db_url)
        try:
            await conn.execute(
                """
                INSERT INTO members
                    (id, email, first_name, surname, dob,
                     join_date, membership_status,
                     is_coach, is_first_aider, user_id)
                VALUES
                    ($1, $2, $3, $4, $5,
                     '2024-01-01', 'active',
                     FALSE, FALSE, $6)
                """,
                str(uuid.uuid4()),
                claims.email,
                "Checkin",
                "Window",
                "1990-06-15",
                claims.sub,
            )
        finally:
            await conn.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(lambda: asyncio.run(_insert())).result()

    return token


def _api_headers(token: str) -> dict:
    return {"Cookie": f"access_token={token}"}


def _get_or_create_session_type(page: Page, token: str) -> tuple[str, str]:
    resp = page.request.get(
        f"{API_URL}/session-types",
        headers=_api_headers(token),
    )
    assert resp.status == 200
    data = resp.json()
    return data[0]["id"], data[0]["name"]


def _create_session_at(
    page: Page, token: str, start: datetime, duration_minutes: int = 60
) -> str:
    """Create an ad-hoc session with a segment starting at `start` local time."""
    type_id, _ = _get_or_create_session_type(page, token)
    resp = page.request.post(
        f"{API_URL}/sessions",
        headers={**_api_headers(token), "Content-Type": "application/json"},
        data=json.dumps(
            {
                "title": "Checkin Window Test Session",
                "date": start.strftime("%Y-%m-%d"),
                "segments": [
                    {
                        "start_time": start.strftime("%H:%M"),
                        "duration_minutes": duration_minutes,
                        "type_ids": [type_id],
                    }
                ],
            }
        ),
    )
    assert resp.status == 201, f"create session failed: {resp.status} {resp.text()}"
    return resp.json()["id"]


# ── AC7 — Too-early state on the check-in page ──────────────────────────────


def test_checkin_page_shows_too_early_state(page: Page) -> None:
    admin_token = _make_token("admin")
    # Default checkin_window_before_minutes is 60 — start the session 3 hours
    # from now so "now" is well before opens_at (start - 60min).
    start = datetime.now() + timedelta(hours=3)
    session_id = _create_session_at(page, admin_token, start)

    member_token = _make_user_with_complete_profile("member")
    _set_cookie(page, member_token)
    page.goto(f"{BASE_URL}/checkin/session/{session_id}")

    expect(page.get_by_role("heading", name="Check-in not open yet")).to_be_visible(
        timeout=8000
    )
    expect(page.get_by_text("Check-in opens at")).to_be_visible()


# ── AC7 — Closed state on the check-in page ─────────────────────────────────


def test_checkin_page_shows_closed_state(page: Page) -> None:
    admin_token = _make_token("admin")
    # Default checkin_window_after_minutes is 120 — a session that started 5
    # hours ago and ran 1 hour closes 2 hours ago, well before "now".
    start = datetime.now() - timedelta(hours=5)
    session_id = _create_session_at(page, admin_token, start, duration_minutes=60)

    member_token = _make_user_with_complete_profile("member")
    _set_cookie(page, member_token)
    page.goto(f"{BASE_URL}/checkin/session/{session_id}")

    expect(page.get_by_role("heading", name="Check-in closed")).to_be_visible(
        timeout=8000
    )
    expect(page.get_by_text("Check-in closed at")).to_be_visible()


# ── AC3 — Admin settings "Check-in window" card with two default inputs ────


def test_admin_settings_shows_checkin_window_card_with_two_inputs(page: Page) -> None:
    admin_token = _make_user_with_complete_profile("admin")
    _set_cookie(page, admin_token)

    page.goto(f"{BASE_URL}/admin/settings")

    expect(page.get_by_role("heading", name="Check-in Window")).to_be_visible(
        timeout=8000
    )

    before_input = page.get_by_label("Check-in window opens before session, in minutes")
    after_input = page.get_by_label(
        "Check-in window closes after session starts, in minutes"
    )
    expect(before_input).to_be_visible()
    expect(after_input).to_be_visible()

    expect(page.get_by_role("button", name="Save check-in window")).to_be_visible()


# ── AC3 — Admin settings "Check-in window" validation (0-1440 integer) ─────


def test_admin_settings_checkin_window_rejects_invalid_minutes(page: Page) -> None:
    admin_token = _make_user_with_complete_profile("admin")
    _set_cookie(page, admin_token)

    page.goto(f"{BASE_URL}/admin/settings")

    before_input = page.get_by_label("Check-in window opens before session, in minutes")
    expect(before_input).to_be_visible(timeout=8000)
    save_button = page.get_by_role("button", name="Save check-in window")

    # Negative value is rejected
    before_input.fill("-5")
    expect(page.get_by_text("Must be a non-negative whole number")).to_be_visible()
    expect(save_button).to_be_disabled()

    # Value over 1440 is rejected
    before_input.fill("2000")
    expect(page.get_by_text("Must be 1440 or less")).to_be_visible()
    expect(save_button).to_be_disabled()

    # A valid value clears the error and re-enables Save
    before_input.fill("30")
    expect(page.get_by_text("Must be 1440 or less")).not_to_be_visible()
    expect(save_button).to_be_enabled()
