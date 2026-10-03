"""Schema constraints added for #431, and the migration that adds them.

Tier 2: each test gets its own scratch database (see test_migrations.py for
why), migrates it with alembic, and talks to it in raw SQL — the point is what
the database itself refuses, not what the app happens to check first.
"""

import asyncio
import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command
from app.db.bootstrap import _alembic_config
from app.db.scratch import create_database, drop_database, url_parts

_BASE_URL, _ = url_parts(os.environ["DATABASE_URL"])

# The revision before the constraints, for seeding rows they would refuse.
_BEFORE = "e1f2a3b4c5d7"

SESSION = str(uuid.uuid4())
MEMBER = str(uuid.uuid4())
FEDERATION = str(uuid.uuid4())
RECORDER = str(uuid.uuid4())


@pytest_asyncio.fixture
async def db_url():
    name = f"kendo_test_con_{uuid.uuid4().hex[:12]}"
    url = await create_database(_BASE_URL, name)
    try:
        yield url
    finally:
        await drop_database(_BASE_URL, name)


def _upgrade_blocking(url: str, revision: str) -> None:
    cfg = _alembic_config(url)
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        command.upgrade(cfg, revision)
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


async def upgrade(url: str, revision: str = "head") -> None:
    # env.py runs its own asyncio.run(), which cannot nest in the test's loop.
    await asyncio.to_thread(_upgrade_blocking, url, revision)


async def sql(url: str, *statements: str) -> list:
    """Run statements in one transaction; return the last one's rows."""
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            rows: list = []
            for statement in statements:
                result = await conn.execute(text(statement))
                rows = list(result) if result.returns_rows else []
            return rows
    finally:
        await engine.dispose()


SEED = [
    f"""INSERT INTO members (id, first_name, surname, join_date, membership_status,
        is_coach, is_first_aider)
        VALUES ('{MEMBER}', 'Ai', 'Sato', '2026-01-01', 'active', false, false)""",
    f"""INSERT INTO session_instances (id, title, date, cancelled)
        VALUES ('{SESSION}', 'Keiko', '2026-10-01', false)""",
    f"""INSERT INTO federations (id, name, is_pinned, is_active)
        VALUES ('{FEDERATION}', 'BKA', false, true)""",
]


def attendance(
    *, member: str | None = MEMBER, visitor: str | None = None, at: str = "t1"
) -> str:
    member_sql = f"'{member}'" if member else "NULL"
    visitor_sql = f"'{visitor}'" if visitor else "NULL"
    return f"""INSERT INTO attendance
        (id, session_id, member_id, visitor_name, checked_in_at, recorded_by)
        VALUES ('{uuid.uuid4()}', '{SESSION}', {member_sql}, {visitor_sql},
                '{at}', '{RECORDER}')"""


# ---------------------------------------------------------------------------
# Each constraint refuses the row it exists to refuse
# ---------------------------------------------------------------------------


async def test_a_member_cannot_be_checked_in_twice(db_url):
    await upgrade(db_url)
    await sql(db_url, *SEED, attendance())

    with pytest.raises(IntegrityError, match="uq_attendance_session_member"):
        await sql(db_url, attendance())


async def test_any_number_of_visitors_may_attend_one_session(db_url):
    # NULL member_id is never equal to another NULL, so the unique constraint
    # leaves visitor rows alone.
    await upgrade(db_url)
    await sql(db_url, *SEED, attendance(member=None, visitor="Guest"))
    await sql(db_url, attendance(member=None, visitor="Guest"))

    rows = await sql(db_url, "SELECT count(*) FROM attendance")
    assert rows[0][0] == 2


@pytest.mark.parametrize(
    "member, visitor",
    [(None, None), (MEMBER, "Guest")],
    ids=["neither", "both"],
)
async def test_attendance_is_exactly_one_of_member_or_visitor(db_url, member, visitor):
    await upgrade(db_url)
    await sql(db_url, *SEED)

    with pytest.raises(IntegrityError, match="ck_attendance_member_xor_visitor"):
        await sql(db_url, attendance(member=member, visitor=visitor))


def membership() -> str:
    return f"""INSERT INTO member_federations (id, member_id, federation_id, member_number)
        VALUES ('{uuid.uuid4()}', '{MEMBER}', '{FEDERATION}', 'N-1')"""


async def test_a_member_holds_one_membership_per_federation(db_url):
    await upgrade(db_url)
    await sql(db_url, *SEED, membership())

    with pytest.raises(IntegrityError, match="uq_member_federations_member_federation"):
        await sql(db_url, membership())


def settings_row() -> str:
    return f"""INSERT INTO dojo_settings (id, dojo_name, primary_colour,
        checkin_window_before_minutes, checkin_window_after_minutes,
        login_show_background, login_show_logo, login_show_name, updated_at)
        VALUES ('{uuid.uuid4()}', 'Dojo', '#000000', 60, 120,
                false, false, false, now())"""


async def test_dojo_settings_holds_one_row(db_url):
    await upgrade(db_url)
    await sql(db_url, settings_row())

    with pytest.raises(IntegrityError, match="uq_dojo_settings_single_row"):
        await sql(db_url, settings_row())


async def test_federation_names_are_unique(db_url):
    await upgrade(db_url)
    await sql(db_url, *SEED)

    with pytest.raises(IntegrityError, match="uq_federations_name"):
        await sql(
            db_url,
            f"""INSERT INTO federations (id, name, is_pinned, is_active)
                VALUES ('{uuid.uuid4()}', 'BKA', false, true)""",
        )


# ---------------------------------------------------------------------------
# Rows that predate the constraints
# ---------------------------------------------------------------------------


async def test_upgrade_keeps_only_the_earliest_of_duplicate_check_ins(db_url):
    await upgrade(db_url, _BEFORE)
    await sql(
        db_url,
        *SEED,
        attendance(at="2026-10-01T19:05:00+00:00"),
        attendance(at="2026-10-01T19:00:00+00:00"),
        attendance(at="2026-10-01T19:10:00+00:00"),
        attendance(member=None, visitor="Guest"),
        attendance(member=None, visitor="Guest"),
    )

    await upgrade(db_url)

    rows = await sql(
        db_url, "SELECT checked_in_at FROM attendance WHERE member_id IS NOT NULL"
    )
    assert [r[0] for r in rows] == ["2026-10-01T19:00:00+00:00"]
    visitors = await sql(
        db_url, "SELECT count(*) FROM attendance WHERE member_id IS NULL"
    )
    assert visitors[0][0] == 2


def _bad_attendance() -> tuple[list[str], str]:
    row = str(uuid.uuid4())
    return [
        f"""INSERT INTO attendance
            (id, session_id, member_id, visitor_name, checked_in_at, recorded_by)
            VALUES ('{row}', '{SESSION}', NULL, NULL, 't', '{RECORDER}')"""
    ], row


def _duplicate_membership() -> tuple[list[str], str]:
    return [membership(), membership()], MEMBER


def _two_settings_rows() -> tuple[list[str], str]:
    return [settings_row(), settings_row()], "dojo_settings"


def _duplicate_federation_name() -> tuple[list[str], str]:
    other = str(uuid.uuid4())
    return [
        f"""INSERT INTO federations (id, name, is_pinned, is_active)
            VALUES ('{other}', 'BKA', false, true)"""
    ], other


@pytest.mark.parametrize(
    "violation",
    [
        _bad_attendance,
        _duplicate_membership,
        _two_settings_rows,
        _duplicate_federation_name,
    ],
    ids=["attendance-neither", "membership", "settings", "federation-name"],
)
async def test_upgrade_aborts_naming_rows_it_will_not_guess_about(db_url, violation):
    await upgrade(db_url, _BEFORE)
    statements, named = violation()
    await sql(db_url, *SEED, *statements)

    with pytest.raises(RuntimeError) as aborted:
        await upgrade(db_url)
    # The migration's own message, not a constraint error that happens to
    # quote the key: it names the rows and says what to do with them.
    assert "fix these rows by hand" in str(aborted.value)
    assert named in str(aborted.value)

    version = await sql(db_url, "SELECT version_num FROM alembic_version")
    assert version[0][0] == _BEFORE
