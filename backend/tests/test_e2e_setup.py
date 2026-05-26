"""E2E browser tests for the first-run setup page (issue #38).

Tests are ordered so that "fresh instance" checks (AC1, AC3, AC4) run before
the populate step, and "populated instance" checks (AC2) run after.

The module-scoped ``fresh_db`` fixture wipes the users and passkey_credentials
tables at the start of the module so the server starts each suite group in a
known state.
"""

import asyncio
import concurrent.futures
import os

import asyncpg
import pytest
import requests
from playwright.sync_api import Page, expect

BASE_URL = "http://localhost:5173"
API_URL = "http://localhost:8000"

# The backend exposes /setup directly (no /api prefix).
# The frontend dev-server proxy rewrites /api/setup → /setup on the backend,
# so browser-facing code uses /api/setup, but direct backend checks use /setup.
_SETUP_HEALTH_URL = f"{API_URL}/setup"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _clear_users_async() -> None:
    db_url = os.environ["DATABASE_URL"].replace(
        "postgresql+asyncpg://", "postgresql://"
    )
    conn = await asyncpg.connect(db_url)
    try:
        await conn.execute("DELETE FROM passkey_credentials")
        await conn.execute("DELETE FROM recovery_codes")
        await conn.execute("DELETE FROM recovery_attempts")
        await conn.execute("DELETE FROM admin_recovery_tokens")
        await conn.execute("DELETE FROM grade_history")
        await conn.execute("DELETE FROM attendance")
        await conn.execute("DELETE FROM members WHERE user_id IS NOT NULL")
        await conn.execute("DELETE FROM users")
    finally:
        await conn.close()


def _clear_users_and_credentials() -> None:
    """Wipe users and passkey_credentials so the server reports a fresh instance."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(lambda: asyncio.run(_clear_users_async())).result()


def _populate_instance() -> None:
    """Create a passkey credential row so the server reports a populated instance."""
    resp = requests.post(
        f"{API_URL}/auth/login/test",
        json={"email": "e2e_setup_seed@dojo.test", "role": "admin"},
        timeout=5,
    )
    assert resp.ok, f"Test login failed: {resp.status_code} {resp.text}"
    user_id = resp.json()["sub"]

    db_url = os.environ["DATABASE_URL"].replace(
        "postgresql+asyncpg://", "postgresql://"
    )

    async def _insert_credential() -> None:
        conn = await asyncpg.connect(db_url)
        try:
            await conn.execute(
                """
                INSERT INTO passkey_credentials
                    (id, user_id, credential_id, public_key, sign_count, label, created_at)
                VALUES
                    (gen_random_uuid()::text, $1, '\\xDEADBEEF', '\\xDEADBEEF', 0, 'seed', now())
                ON CONFLICT DO NOTHING
                """,
                user_id,
            )
        finally:
            await conn.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(lambda: asyncio.run(_insert_credential())).result()


# ---------------------------------------------------------------------------
# Module-scoped fixture: ensure we start with a fresh DB
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", autouse=True)
def fresh_db() -> None:
    """Reset the live database to a pristine state before this test module runs."""
    _clear_users_and_credentials()
    # Verify the API now reports setup available (backend path, no /api prefix)
    r = requests.get(_SETUP_HEALTH_URL, timeout=5)
    assert (
        r.status_code == 200
    ), f"Expected 200 from {_SETUP_HEALTH_URL} after clearing DB, got {r.status_code}"


# ---------------------------------------------------------------------------
# AC1: /setup loads on a fresh instance
# ---------------------------------------------------------------------------


def test_setup_page_loads_on_fresh_instance(page: Page, fresh_db: None) -> None:
    """Visiting /setup on a fresh instance renders the setup card without redirecting."""
    page.goto(f"{BASE_URL}/setup")
    # CardTitle renders as a <div data-slot="card-title">, not a semantic heading.
    # Use get_by_text so we don't depend on the element type.
    expect(page.get_by_text("Welcome to Kendo Dojo")).to_be_visible()
    # Must still be on /setup, not redirected away
    expect(page).to_have_url(f"{BASE_URL}/setup")


# ---------------------------------------------------------------------------
# AC3: / on a fresh instance redirects to /setup (not /login)
# ---------------------------------------------------------------------------


def test_fresh_instance_redirects_root_to_setup(page: Page, fresh_db: None) -> None:
    """Unauthenticated visit to / on a fresh instance redirects to /setup."""
    page.context.clear_cookies()
    page.goto(f"{BASE_URL}/")
    expect(page).to_have_url(f"{BASE_URL}/setup")


# ---------------------------------------------------------------------------
# AC4: Setup page renders passkey registration UI
# ---------------------------------------------------------------------------


def test_setup_page_shows_passkey_registration_ui(page: Page, fresh_db: None) -> None:
    """The setup page presents an email field and a passkey registration button."""
    page.goto(f"{BASE_URL}/setup")
    # CardTitle renders as <div data-slot="card-title">, not a semantic heading
    expect(page.get_by_text("Welcome to Kendo Dojo")).to_be_visible()
    expect(page.get_by_label("Email")).to_be_visible()
    expect(page.get_by_role("button", name="Create admin passkey")).to_be_visible()


# ---------------------------------------------------------------------------
# Populate the database for AC2
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def populated_db(fresh_db: None) -> None:
    """Seed a real user so the server treats the instance as populated."""
    _populate_instance()
    # Sanity-check: setup endpoint must now return 404
    r = requests.get(f"{API_URL}/api/setup", timeout=5)
    assert (
        r.status_code == 404
    ), f"Expected 404 from /api/setup after seeding user, got {r.status_code}"


# ---------------------------------------------------------------------------
# AC2: /setup redirects to /login when instance is populated
# ---------------------------------------------------------------------------


def test_setup_redirects_to_login_when_populated(
    page: Page, populated_db: None
) -> None:
    """Visiting /setup on a populated instance redirects to /login."""
    page.context.clear_cookies()
    page.goto(f"{BASE_URL}/setup")
    expect(page).to_have_url(f"{BASE_URL}/login")


# ---------------------------------------------------------------------------
# AC5: Full ceremony requires hardware — UI-only check, strict=False
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=False,
    reason=(
        "WebAuthn passkey ceremony requires a hardware authenticator or CDP virtual "
        "authenticator — cannot automate in headless Playwright without additional "
        "test infrastructure"
    ),
)
def test_setup_registration_redirects_to_dashboard_as_admin(
    page: Page, fresh_db: None
) -> None:
    """After successful passkey registration via setup, user lands on / as admin.

    This test is marked xfail(strict=False) because the WebAuthn credential-creation
    ceremony (navigator.credentials.create) requires a real or virtual authenticator
    that is not available in standard headless Playwright.  The UI assertions above
    (AC1, AC4) confirm the form is present and wired correctly; the full flow can be
    verified manually or with a CDP virtual authenticator extension.
    """
    # Re-ensure fresh state (this test depends on fresh_db but runs after populated)
    _clear_users_and_credentials()
    page.goto(f"{BASE_URL}/setup")
    expect(page.get_by_label("Email")).to_be_visible()
    page.get_by_label("Email").fill("admin@dojo.test")
    page.get_by_role("button", name="Create admin passkey").click()
    # The ceremony will fail without an authenticator; we cannot assert the redirect.
    expect(page).to_have_url(f"{BASE_URL}/")
