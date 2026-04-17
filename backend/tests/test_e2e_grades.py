"""
Playwright E2E tests for issue #8 — Grade promotion UI.

One test per acceptance criterion that has a frontend component.
Admin setup mirrors the pattern from test_e2e_members.py.
"""

import sqlite3
from pathlib import Path

import httpx
from playwright.sync_api import Page, expect

BASE_URL = "http://localhost:5173"
API_BASE = "http://localhost:8000"

_ADMIN_EMAIL = "e2e_admin_grades@dojo.test"
_ADMIN_PASS = "Str0ng!Pass"


def _get_db_path() -> Path:
    """Find kendo.db — may be in backend/ or cwd."""
    candidates = [
        Path(__file__).parents[2] / "backend" / "kendo.db",
        Path(__file__).parents[1] / "kendo.db",
        Path("kendo.db"),
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError("kendo.db not found")


def _setup_admin(page: Page) -> None:
    """Register a user and promote to admin via DB, then log in via the browser."""
    r = httpx.post(
        f"{API_BASE}/auth/register/password",
        json={"email": _ADMIN_EMAIL, "password": _ADMIN_PASS},
    )
    if r.status_code == 201:
        user_id = r.json()["sub"]
        db = _get_db_path()
        conn = sqlite3.connect(db)
        conn.execute("UPDATE users SET role='admin' WHERE id=?", (user_id,))
        conn.commit()
        conn.close()

    # Login page defaults to passkey mode — switch to password mode first.
    page.goto(f"{BASE_URL}/login")
    page.get_by_role("button", name="Use email and password instead").click()
    page.get_by_label("Email").fill(_ADMIN_EMAIL)
    page.get_by_label("Password").fill(_ADMIN_PASS)
    page.get_by_role("button", name="Sign in").click()
    expect(page).to_have_url(f"{BASE_URL}/", timeout=8000)


def _create_member_via_api(full_name: str, email: str) -> str:
    """Create a member via API using admin credentials; return member id."""
    client = httpx.Client()
    r = client.post(
        f"{API_BASE}/auth/login/password",
        json={"email": _ADMIN_EMAIL, "password": _ADMIN_PASS},
    )
    r.raise_for_status()
    r2 = client.post(
        f"{API_BASE}/members",
        json={
            "email": email,
            "full_name": full_name,
            "dob": "1990-01-01",
            "join_date": "2024-01-01",
        },
    )
    if r2.status_code not in (201, 409):
        r2.raise_for_status()
    if r2.status_code == 201:
        return r2.json()["id"]
    # Already exists — look it up by email
    r3 = client.get(f"{API_BASE}/members?search={email}")
    r3.raise_for_status()
    return r3.json()[0]["id"]


# CardTitle in shadcn renders as a div[data-slot="card-title"], not a semantic
# heading element, so we locate it by text content within that slot.
_GRADE_CARD_TITLE = '[data-slot="card-title"]:has-text("Grade")'


# ---------------------------------------------------------------------------
# AC1/AC5 — Grade card shows member's current grade
# ---------------------------------------------------------------------------


def test_grade_shown_on_member_detail(page: Page) -> None:
    """AC1/AC5: Member detail page shows the member's current grade."""
    _setup_admin(page)
    member_id = _create_member_via_api(
        "Grade Display Member", "grade_display@dojo.test"
    )
    page.goto(f"{BASE_URL}/members/{member_id}")
    # Grade card title must be visible
    expect(page.locator(_GRADE_CARD_TITLE)).to_be_visible(timeout=8000)
    # Member with no promotions shows "Mukyū" as their current grade
    expect(page.get_by_text("Mukyū")).to_be_visible(timeout=8000)


# ---------------------------------------------------------------------------
# AC2 — Promote button visible for admin
# ---------------------------------------------------------------------------


def test_promote_button_visible_for_admin(page: Page) -> None:
    """AC2: Promote button is visible on the member detail page for admins."""
    _setup_admin(page)
    member_id = _create_member_via_api(
        "Promote Button Member", "promote_button@dojo.test"
    )
    page.goto(f"{BASE_URL}/members/{member_id}")
    # Wait for grade card to load (skeleton resolves to grade text)
    expect(page.locator(_GRADE_CARD_TITLE)).to_be_visible(timeout=8000)
    expect(page.get_by_role("button", name="Promote member")).to_be_visible(
        timeout=8000
    )


# ---------------------------------------------------------------------------
# AC4/AC6 — Grade history toggle works
# ---------------------------------------------------------------------------


def test_grade_history_visible_to_member(page: Page) -> None:
    """AC4/AC6: Grade history toggle appears after a promotion and expands correctly."""
    _setup_admin(page)
    member_id = _create_member_via_api(
        "History Toggle Member", "history_toggle@dojo.test"
    )
    page.goto(f"{BASE_URL}/members/{member_id}")

    # Wait for grade card and Promote button to appear
    expect(page.locator(_GRADE_CARD_TITLE)).to_be_visible(timeout=8000)
    expect(page.get_by_role("button", name="Promote member")).to_be_visible(
        timeout=8000
    )

    # Promote the member so there is at least one history entry
    page.get_by_role("button", name="Promote member").click()

    # "Show grade history (1)" toggle must appear after promotion
    toggle = page.locator("button", has_text="grade history")
    expect(toggle).to_be_visible(timeout=8000)

    # Expand
    toggle.click()
    expect(page.locator("#grade-history-list")).to_be_visible(timeout=5000)

    # Collapse
    toggle.click()
    expect(page.locator("#grade-history-list")).not_to_be_visible(timeout=5000)
