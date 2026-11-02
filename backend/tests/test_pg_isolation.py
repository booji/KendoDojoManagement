"""
PostgreSQL integration tests: engine fixture and per-test savepoint rollback.

Skipped automatically when DATABASE_URL is not postgresql+asyncpg:// (i.e. local
dev without Docker). Run via docker-compose.test.yml which sets DATABASE_URL.
"""

import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason="PostgreSQL not configured — set DATABASE_URL=postgresql+asyncpg://",
)

# ---------------------------------------------------------------------------
# 1. Verify the engine fixture uses PostgreSQL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pg_fixture_uses_postgresql(pg_engine: AsyncEngine) -> None:
    """The `pg_engine` fixture must connect to PostgreSQL.

    Fails right now because conftest.py does not define a `pg_engine` fixture.
    """
    url_str = str(pg_engine.url)
    assert url_str.startswith("postgresql+asyncpg://"), (
        f"Expected postgresql+asyncpg:// URL, got: {url_str}"
    )


# ---------------------------------------------------------------------------
# 2. Data isolation — pair of tests that share a table name but must NOT
#    see each other's data. Uses a raw `db_session` fixture (savepoint-backed).
# ---------------------------------------------------------------------------

# We use a scratch table that the real schema doesn't need; the session fixture
# must create the schema once per session so the table exists.  The isolation
# pair inserts a sentinel row and then asserts the OTHER sentinel is absent.

_TABLE = "members"  # real table that will exist once schema is created
_SENTINEL_A = "isolation-sentinel-test-a"
_SENTINEL_B = "isolation-sentinel-test-b"


@pytest.mark.asyncio
async def test_data_isolation_between_tests_a(db_session: AsyncSession) -> None:
    """Insert a row in test A; verify test B's sentinel is NOT present.

    Fails right now because conftest.py does not define a `db_session` fixture
    with savepoint rollback semantics.
    """
    # Insert our sentinel so test B (if run after A) would see it without rollback
    await db_session.execute(
        text(
            "INSERT INTO members (id, first_name, surname, email, join_date, membership_status, is_coach, is_first_aider) "
            "VALUES (:id, :name, 'Sentinel', :email, '2020-01-01', 'active', false, false)"
        ),
        {
            "id": "00000000-0000-0000-0000-000000000001",
            "name": _SENTINEL_A,
            "email": "sentinel-a@example.com",
        },
    )

    # Test B's sentinel must not be here
    result = await db_session.execute(
        text("SELECT COUNT(*) FROM members WHERE first_name = :name"),
        {"name": _SENTINEL_B},
    )
    count = result.scalar_one()
    assert count == 0, (
        f"Test B's sentinel row was visible in test A — isolation is broken. "
        f"count={count}"
    )


@pytest.mark.asyncio
async def test_data_isolation_between_tests_b(db_session: AsyncSession) -> None:
    """Insert a row in test B; verify test A's sentinel is NOT present.

    If savepoint rollback works correctly, test A's insert was rolled back before
    this test started, so the sentinel from test A must not be visible here.

    Fails right now because conftest.py does not define a `db_session` fixture
    with savepoint rollback semantics.
    """
    # Insert our sentinel so test A (if run after B) would see it without rollback
    await db_session.execute(
        text(
            "INSERT INTO members (id, first_name, surname, email, join_date, membership_status, is_coach, is_first_aider) "
            "VALUES (:id, :name, 'Sentinel', :email, '2020-01-01', 'active', false, false)"
        ),
        {
            "id": "00000000-0000-0000-0000-000000000002",
            "name": _SENTINEL_B,
            "email": "sentinel-b@example.com",
        },
    )

    # Test A's sentinel must not be here (it should have been rolled back)
    result = await db_session.execute(
        text("SELECT COUNT(*) FROM members WHERE first_name = :name"),
        {"name": _SENTINEL_A},
    )
    count = result.scalar_one()
    assert count == 0, (
        f"Test A's sentinel row was visible in test B — isolation is broken "
        f"(savepoint rollback did not run). count={count}"
    )
