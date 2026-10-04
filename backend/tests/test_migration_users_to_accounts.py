"""`users` becomes `accounts` (#436), and the migration that renames it.

Tier 2: each test gets its own scratch database (see test_migrations.py for
why), migrates it with alembic, and talks to it in raw SQL.
"""

import uuid

from tests.migration_support import downgrade, sql, upgrade

# The revision before the rename, and the rename itself: pinned rather than
# head so a later migration touching `accounts` does not break these tests.
_BEFORE = "d6e7f8a9b0c2"
_AFTER = "e7f8a9b0c1d3"

MEMBER = str(uuid.uuid4())
ACCOUNT = str(uuid.uuid4())
CODE = str(uuid.uuid4())


async def seed(url: str, table: str) -> None:
    await sql(
        url,
        f"""INSERT INTO members (id, first_name, surname, join_date,
            membership_status, is_coach, is_first_aider)
            VALUES ('{MEMBER}', 'Ai', 'Sato', '2026-01-01', 'active', false, false)""",
        f"""INSERT INTO {table} (id, member_id, role, is_active, theme)
            VALUES ('{ACCOUNT}', '{MEMBER}', 'admin', true, 'dark')""",
        f"""INSERT INTO recovery_codes (id, user_id, code_hash, set_id, created_at)
            VALUES ('{CODE}', '{ACCOUNT}', 'h', 's', now())""",
    )


async def tables(url: str) -> set[str]:
    rows = await sql(
        url,
        """SELECT table_name FROM information_schema.tables
           WHERE table_schema = 'public' AND table_name IN ('users', 'accounts')""",
    )
    return {r[0] for r in rows}


async def constraints(url: str, table: str) -> set[str]:
    rows = await sql(
        url,
        f"""SELECT conname FROM pg_constraint
            WHERE conrelid = '{table}'::regclass""",
    )
    return {r[0] for r in rows}


async def referenced_by_recovery_codes(url: str) -> str:
    rows = await sql(
        url,
        """SELECT confrelid::regclass::text FROM pg_constraint
           WHERE conrelid = 'recovery_codes'::regclass AND contype = 'f'""",
    )
    return rows[0][0]


async def test_upgrade_renames_users_to_accounts_keeping_rows_and_fks(scratch_db):
    await upgrade(scratch_db, _BEFORE)
    await seed(scratch_db, "users")

    await upgrade(scratch_db, _AFTER)

    assert await tables(scratch_db) == {"accounts"}
    rows = await sql(scratch_db, "SELECT id::text, role, theme FROM accounts")
    assert rows == [(ACCOUNT, "admin", "dark")]
    assert await referenced_by_recovery_codes(scratch_db) == "accounts"
    assert await constraints(scratch_db, "accounts") == {
        "accounts_pkey",
        "uq_accounts_member_id",
        "fk_accounts_member_id",
    }


async def test_downgrade_restores_users(scratch_db):
    await upgrade(scratch_db, _BEFORE)
    await seed(scratch_db, "users")
    await upgrade(scratch_db, _AFTER)

    await downgrade(scratch_db, _BEFORE)

    assert await tables(scratch_db) == {"users"}
    rows = await sql(scratch_db, "SELECT id::text FROM users")
    assert rows == [(ACCOUNT,)]
    assert await referenced_by_recovery_codes(scratch_db) == "users"
    assert await constraints(scratch_db, "users") == {
        "users_pkey",
        "uq_users_member_id",
        "fk_users_member_id",
    }
