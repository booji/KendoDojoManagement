"""real date/time column types

Issue #433 (decided in the #418 schema review, section 1). Dates, times and
timestamps were VARCHAR, so Postgres accepted '2026-02-31' and ordering held
only because ISO-8601 happens to sort lexically. Each column becomes its real
type with ALTER COLUMN ... TYPE ... USING.

- members.dob, members.join_date, session_templates.start_date/.end_date,
  session_instances.date: VARCHAR(10) -> date
- session_template_segments.start_time, session_instance_segments.start_time:
  VARCHAR(5) -> time
- attendance.checked_in_at, grade_history.promoted_at: VARCHAR(50) ->
  timestamptz. Both were written as ISO-8601 with an offset, so the cast is
  lossless.

The API contract is unchanged: app.db.base's Iso* column types hand the app
the same ISO strings it read before.

Existing rows are inspected first. A value that is not in the format the app
writes ('YYYY-MM-DD', 'HH:MM', ISO-8601 with an offset), or that is but names
no real date or time ('2026-02-31', '24:00'), aborts the upgrade naming the
table, row and value, before any change. No coercion: Postgres would happily
read '01/02/2026' or 'yesterday', and either guess could be wrong.

Downgrade writes the same strings back with to_char. A timestamp that was
written with a non-UTC offset comes back in UTC: the same instant.

Revision ID: c5d6e7f8a9b1
Revises: b4c5d6e7f8a0
Create Date: 2026-10-03

"""

import sqlalchemy as sa

from alembic import op

revision = "c5d6e7f8a9b1"
down_revision = "b4c5d6e7f8a0"
branch_labels = None
depends_on = None

# Each kind: the real type, the shape the app writes, the VARCHAR it was, and
# how to_char writes it back. US is microseconds; Python's isoformat leaves
# them out when they are zero, so the downgrade strips '.000000'.
_KINDS = {
    "date": (sa.Date(), r"^\d{4}-\d{2}-\d{2}$", 10, "to_char({c}, 'YYYY-MM-DD')"),
    "time": (sa.Time(), r"^([01]\d|2[0-3]):[0-5]\d$", 5, "to_char({c}, 'HH24:MI')"),
    "timestamptz": (
        sa.DateTime(timezone=True),
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|[+-]\d{2}:\d{2})$",
        50,
        "replace(to_char({c} AT TIME ZONE 'UTC', "
        "'YYYY-MM-DD\"T\"HH24:MI:SS.US\"+00:00\"'), '.000000', '')",
    ),
}

_COLUMNS = [
    ("members", "dob", "date"),
    ("members", "join_date", "date"),
    ("session_templates", "start_date", "date"),
    ("session_templates", "end_date", "date"),
    ("session_instances", "date", "date"),
    ("session_template_segments", "start_time", "time"),
    ("session_instance_segments", "start_time", "time"),
    ("attendance", "checked_in_at", "timestamptz"),
    ("grade_history", "promoted_at", "timestamptz"),
]


def _refuse_values_that_will_not_cast(conn) -> None:
    problems = []
    for table, column, kind in _COLUMNS:
        _, shape, _, _ = _KINDS[kind]
        # pg_input_is_valid (Postgres 16) tests the cast without raising.
        rows = conn.execute(
            sa.text(
                f'SELECT id, "{column}" FROM {table} '
                f'WHERE "{column}" IS NOT NULL AND NOT ("{column}" ~ :shape '
                f'AND pg_input_is_valid("{column}", :kind)) ORDER BY id'
            ),
            {"shape": shape, "kind": kind},
        )
        problems += [f"{table}.{column}, row {id_}: {value!r}" for id_, value in rows]

    if problems:
        raise RuntimeError(
            "Cannot convert the #433 date/time columns: fix these rows by hand "
            "(dates 'YYYY-MM-DD', times 'HH:MM', timestamps ISO-8601 with an "
            "offset), then re-run the upgrade. Nothing has been changed.\n- "
            + "\n- ".join(problems)
        )


def upgrade() -> None:
    _refuse_values_that_will_not_cast(op.get_bind())
    for table, column, kind in _COLUMNS:
        real_type = _KINDS[kind][0]
        op.alter_column(
            table, column, type_=real_type, postgresql_using=f'"{column}"::{kind}'
        )


def downgrade() -> None:
    for table, column, kind in _COLUMNS:
        _, _, length, to_text = _KINDS[kind]
        op.alter_column(
            table,
            column,
            type_=sa.String(length),
            postgresql_using=to_text.format(c=f'"{column}"'),
        )
