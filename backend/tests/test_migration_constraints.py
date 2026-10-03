"""Schema constraints added for #431, and the migration that adds them.

Tier 2: each test gets its own scratch database (see test_migrations.py for
why), migrates it with alembic, and talks to it in raw SQL — the point is what
the database itself refuses, not what the app happens to check first.
"""

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from tests.migration_support import sql, upgrade

# The revision before the constraints, for seeding rows they would refuse.
_BEFORE = "e1f2a3b4c5d7"

SESSION = str(uuid.uuid4())
MEMBER = str(uuid.uuid4())
FEDERATION = str(uuid.uuid4())
RECORDER = str(uuid.uuid4())


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


async def test_a_member_cannot_be_checked_in_twice(scratch_db):
    await upgrade(scratch_db)
    await sql(scratch_db, *SEED, attendance())

    with pytest.raises(IntegrityError, match="uq_attendance_session_member"):
        await sql(scratch_db, attendance())


async def test_any_number_of_visitors_may_attend_one_session(scratch_db):
    # NULL member_id is never equal to another NULL, so the unique constraint
    # leaves visitor rows alone.
    await upgrade(scratch_db)
    await sql(scratch_db, *SEED, attendance(member=None, visitor="Guest"))
    await sql(scratch_db, attendance(member=None, visitor="Guest"))

    rows = await sql(scratch_db, "SELECT count(*) FROM attendance")
    assert rows[0][0] == 2


@pytest.mark.parametrize(
    "member, visitor",
    [(None, None), (MEMBER, "Guest")],
    ids=["neither", "both"],
)
async def test_attendance_is_exactly_one_of_member_or_visitor(
    scratch_db, member, visitor
):
    await upgrade(scratch_db)
    await sql(scratch_db, *SEED)

    with pytest.raises(IntegrityError, match="ck_attendance_member_xor_visitor"):
        await sql(scratch_db, attendance(member=member, visitor=visitor))


def membership() -> str:
    return f"""INSERT INTO member_federations (id, member_id, federation_id, member_number)
        VALUES ('{uuid.uuid4()}', '{MEMBER}', '{FEDERATION}', 'N-1')"""


async def test_a_member_holds_one_membership_per_federation(scratch_db):
    await upgrade(scratch_db)
    await sql(scratch_db, *SEED, membership())

    with pytest.raises(IntegrityError, match="uq_member_federations_member_federation"):
        await sql(scratch_db, membership())


def settings_row() -> str:
    return f"""INSERT INTO dojo_settings (id, dojo_name, primary_colour,
        checkin_window_before_minutes, checkin_window_after_minutes,
        login_show_background, login_show_logo, login_show_name, updated_at)
        VALUES ('{uuid.uuid4()}', 'Dojo', '#000000', 60, 120,
                false, false, false, now())"""


async def test_dojo_settings_holds_one_row(scratch_db):
    await upgrade(scratch_db)
    await sql(scratch_db, settings_row())

    with pytest.raises(IntegrityError, match="uq_dojo_settings_single_row"):
        await sql(scratch_db, settings_row())


async def test_federation_names_are_unique(scratch_db):
    await upgrade(scratch_db)
    await sql(scratch_db, *SEED)

    with pytest.raises(IntegrityError, match="uq_federations_name"):
        await sql(
            scratch_db,
            f"""INSERT INTO federations (id, name, is_pinned, is_active)
                VALUES ('{uuid.uuid4()}', 'BKA', false, true)""",
        )


# ---------------------------------------------------------------------------
# Rows that predate the constraints
# ---------------------------------------------------------------------------


async def test_upgrade_keeps_only_the_earliest_of_duplicate_check_ins(scratch_db):
    await upgrade(scratch_db, _BEFORE)
    await sql(
        scratch_db,
        *SEED,
        attendance(at="2026-10-01T19:05:00+00:00"),
        attendance(at="2026-10-01T19:00:00+00:00"),
        attendance(at="2026-10-01T19:10:00+00:00"),
        attendance(member=None, visitor="Guest"),
        attendance(member=None, visitor="Guest"),
    )

    await upgrade(scratch_db)

    rows = await sql(
        scratch_db, "SELECT checked_in_at FROM attendance WHERE member_id IS NOT NULL"
    )
    assert [r[0] for r in rows] == ["2026-10-01T19:00:00+00:00"]
    visitors = await sql(
        scratch_db, "SELECT count(*) FROM attendance WHERE member_id IS NULL"
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
async def test_upgrade_aborts_naming_rows_it_will_not_guess_about(
    scratch_db, violation
):
    await upgrade(scratch_db, _BEFORE)
    statements, named = violation()
    await sql(scratch_db, *SEED, *statements)

    with pytest.raises(RuntimeError) as aborted:
        await upgrade(scratch_db)
    # The migration's own message, not a constraint error that happens to
    # quote the key: it names the rows and says what to do with them.
    assert "fix these rows by hand" in str(aborted.value)
    assert named in str(aborted.value)

    version = await sql(scratch_db, "SELECT version_num FROM alembic_version")
    assert version[0][0] == _BEFORE
