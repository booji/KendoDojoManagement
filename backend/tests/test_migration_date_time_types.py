"""Real date/time column types (#433), and the migration that converts them.

Tier 2: each test gets its own scratch database (see test_migrations.py for
why), migrates it with alembic, and talks to it in raw SQL.
"""

import uuid

import pytest

from tests.migration_support import downgrade, sql, upgrade

# The revision before the conversion, when every column below is VARCHAR.
_BEFORE = "b4c5d6e7f8a0"

MEMBER = str(uuid.uuid4())
TEMPLATE = str(uuid.uuid4())
TEMPLATE_SEGMENT = str(uuid.uuid4())
SESSION = str(uuid.uuid4())
SESSION_SEGMENT = str(uuid.uuid4())
ATTENDANCE = str(uuid.uuid4())
GRADE = str(uuid.uuid4())
RECORDER = str(uuid.uuid4())

# (table, column, row id, value as the app writes it, type it becomes)
COLUMNS = [
    ("members", "dob", MEMBER, "2010-02-28", "date"),
    ("members", "join_date", MEMBER, "2026-01-01", "date"),
    ("session_templates", "start_date", TEMPLATE, "2026-09-01", "date"),
    ("session_templates", "end_date", TEMPLATE, "2027-03-01", "date"),
    ("session_instances", "date", SESSION, "2026-10-01", "date"),
    (
        "session_template_segments",
        "start_time",
        TEMPLATE_SEGMENT,
        "19:00",
        "time without time zone",
    ),
    (
        "session_instance_segments",
        "start_time",
        SESSION_SEGMENT,
        "07:30",
        "time without time zone",
    ),
    (
        "attendance",
        "checked_in_at",
        ATTENDANCE,
        "2026-10-01T19:02:03.456789+00:00",
        "timestamp with time zone",
    ),
    (
        "grade_history",
        "promoted_at",
        GRADE,
        "2026-01-15T00:00:00+00:00",
        "timestamp with time zone",
    ),
]

_VALUE = {(table, column): value for table, column, _, value, _ in COLUMNS}


def seed(overrides: dict[tuple[str, str], str] | None = None) -> list[str]:
    """Rows in every converted table; `overrides` replaces values by
    (table, column)."""
    v = {**_VALUE, **(overrides or {})}
    return [
        f"""INSERT INTO members (id, first_name, surname, dob, join_date,
            membership_status, is_coach, is_first_aider)
            VALUES ('{MEMBER}', 'Ai', 'Sato', '{v["members", "dob"]}',
                    '{v["members", "join_date"]}', 'active', false, false)""",
        f"""INSERT INTO session_templates (id, title, start_date, end_date,
            recurrence, interval_weeks, is_active)
            VALUES ('{TEMPLATE}', 'Keiko', '{v["session_templates", "start_date"]}',
                    '{v["session_templates", "end_date"]}', 'weekly', 1, true)""",
        f"""INSERT INTO session_template_segments (id, template_id, start_time,
            duration_minutes, position)
            VALUES ('{TEMPLATE_SEGMENT}', '{TEMPLATE}',
                    '{v["session_template_segments", "start_time"]}', 90, 0)""",
        f"""INSERT INTO session_instances (id, title, date, cancelled)
            VALUES ('{SESSION}', 'Keiko', '{v["session_instances", "date"]}', false)""",
        f"""INSERT INTO session_instance_segments (id, instance_id, start_time,
            duration_minutes, position)
            VALUES ('{SESSION_SEGMENT}', '{SESSION}',
                    '{v["session_instance_segments", "start_time"]}', 90, 0)""",
        f"""INSERT INTO attendance (id, session_id, member_id, checked_in_at,
            recorded_by)
            VALUES ('{ATTENDANCE}', '{SESSION}', '{MEMBER}',
                    '{v["attendance", "checked_in_at"]}', '{RECORDER}')""",
        f"""INSERT INTO grade_history (id, member_id, grade, display_name,
            promoted_at, status)
            VALUES ('{GRADE}', '{MEMBER}', 'SHODAN', 'Shodan',
                    '{v["grade_history", "promoted_at"]}', 'confirmed')""",
    ]


async def column_type(url: str, table: str, column: str) -> str:
    rows = await sql(
        url,
        f"""SELECT data_type FROM information_schema.columns
            WHERE table_name = '{table}' AND column_name = '{column}'""",
    )
    return rows[0][0]


async def stored(url: str, table: str, column: str, row: str) -> object:
    rows = await sql(url, f"""SELECT "{column}" FROM {table} WHERE id = '{row}'""")
    return rows[0][0]


async def test_upgrade_converts_each_column_to_its_real_type(scratch_db):
    await upgrade(scratch_db, _BEFORE)
    await sql(scratch_db, *seed())

    await upgrade(scratch_db)

    for table, column, row, value, real_type in COLUMNS:
        assert await column_type(scratch_db, table, column) == real_type
        # Raw SQL returns native values; isoformat is the app's own format.
        native = await stored(scratch_db, table, column, row)
        text = (
            native.strftime("%H:%M")
            if real_type.startswith("time ")
            else native.isoformat()
        )
        assert text == value, (table, column)


async def test_downgrade_restores_the_strings_the_app_wrote(scratch_db):
    await upgrade(scratch_db, _BEFORE)
    await sql(scratch_db, *seed())
    await upgrade(scratch_db)

    await downgrade(scratch_db, _BEFORE)

    for table, column, row, value, _ in COLUMNS:
        assert await column_type(scratch_db, table, column) == "character varying"
        assert await stored(scratch_db, table, column, row) == value, (table, column)


@pytest.mark.parametrize(
    "table, column, row, bad",
    [
        ("members", "dob", MEMBER, "2026-02-31"),
        ("members", "dob", MEMBER, ""),
        ("members", "join_date", MEMBER, "01/02/2026"),
        ("session_instances", "date", SESSION, "today"),
        ("session_template_segments", "start_time", TEMPLATE_SEGMENT, "24:00"),
        ("session_instance_segments", "start_time", SESSION_SEGMENT, "7pm"),
        ("attendance", "checked_in_at", ATTENDANCE, "yesterday"),
        # No offset: which instant it means depends on the server's TimeZone.
        ("grade_history", "promoted_at", GRADE, "2026-01-15T00:00:00"),
    ],
)
async def test_upgrade_aborts_naming_values_that_will_not_cast(
    scratch_db, table, column, row, bad
):
    await upgrade(scratch_db, _BEFORE)
    await sql(scratch_db, *seed({(table, column): bad}))

    with pytest.raises(RuntimeError) as aborted:
        await upgrade(scratch_db)
    message = str(aborted.value)
    assert "fix these rows by hand" in message
    assert f"{table}.{column}, row {row}: {bad!r}" in message

    version = await sql(scratch_db, "SELECT version_num FROM alembic_version")
    assert version[0][0] == _BEFORE
    assert await column_type(scratch_db, table, column) == "character varying"
