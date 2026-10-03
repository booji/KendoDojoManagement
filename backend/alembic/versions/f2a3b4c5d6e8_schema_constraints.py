"""schema constraints: attendance, federations, dojo_settings

Issue #431 (decided in the #418 schema review, section 2). Until now the
schema had no multi-column UNIQUE and no CHECK constraints at all, so every
invariant below lived only in application code — and the check-in guard was
check-then-insert, which two concurrent requests can both pass.

- attendance UNIQUE (session_id, member_id). Postgres treats NULLs as
  distinct, so any number of Visitor rows (member_id NULL) per session stay
  legal.
- attendance CHECK: exactly one of member_id / visitor_name is set.
- member_federations UNIQUE (member_id, federation_id).
- dojo_settings holds one row: a unique index on the constant (true).
- federations.name UNIQUE.

No other indexes (section 3): at dojo scale a sequential scan is microseconds.

Existing rows are inspected before anything is constrained:

- Duplicate check-ins are repaired: the earliest checked_in_at per
  (session_id, member_id) is kept, the rest deleted — a second row for the
  same member and session adds nothing. checked_in_at is an ISO-8601 string
  written by one code path, so string order is time order; id breaks ties.
- Everything else aborts with a RuntimeError naming the rows and what to do,
  before any change: attendance with neither or both of member/visitor,
  duplicate (member_id, federation_id), more than one dojo_settings row, and
  duplicate federation names. Each is a human call (merging federations
  re-points member_federations). `setup.sh upgrade` backs up before
  migrating, so an abort costs a retry, not data.

Revision ID: f2a3b4c5d6e8
Revises: e1f2a3b4c5d7
Create Date: 2026-10-03

"""

import sqlalchemy as sa

from alembic import op

revision = "f2a3b4c5d6e8"
down_revision = "e1f2a3b4c5d7"
branch_labels = None
depends_on = None


def _ids(rows) -> str:
    return ", ".join(str(r) for r in rows)


def _refuse_rows_needing_a_human(conn) -> None:
    problems = []

    bad = conn.execute(
        sa.text(
            "SELECT id FROM attendance "
            "WHERE (member_id IS NULL) = (visitor_name IS NULL) ORDER BY id"
        )
    ).scalars()
    bad = list(bad)
    if bad:
        problems.append(
            "attendance rows with neither or both of member_id and visitor_name: "
            f"{_ids(bad)}. Set exactly one of the two, or delete the row."
        )

    for member_id, federation_id, ids in conn.execute(
        sa.text(
            "SELECT member_id, federation_id, array_agg(id ORDER BY id) "
            "FROM member_federations GROUP BY member_id, federation_id "
            "HAVING count(*) > 1"
        )
    ):
        problems.append(
            f"member_federations: member {member_id} holds federation "
            f"{federation_id} more than once (rows {_ids(ids)}). "
            "Delete all but one."
        )

    settings = list(
        conn.execute(sa.text("SELECT id FROM dojo_settings ORDER BY id")).scalars()
    )
    if len(settings) > 1:
        problems.append(
            f"dojo_settings has {len(settings)} rows ({_ids(settings)}); the app "
            "only ever reads one. Keep the one with your settings, delete the rest."
        )

    for name, ids in conn.execute(
        sa.text(
            "SELECT name, array_agg(id ORDER BY id) FROM federations "
            "GROUP BY name HAVING count(*) > 1"
        )
    ):
        problems.append(
            f"federations: the name {name!r} is used by more than one row "
            f"({_ids(ids)}). Merge them: point member_federations at one id, "
            "then delete the others."
        )

    if problems:
        raise RuntimeError(
            "Cannot add the #431 schema constraints: fix these rows by hand, "
            "then re-run the upgrade. Nothing has been changed.\n- "
            + "\n- ".join(problems)
        )


def upgrade() -> None:
    conn = op.get_bind()
    _refuse_rows_needing_a_human(conn)
    # Keep the earliest check-in per member and session; see the docstring.
    conn.execute(
        sa.text(
            "DELETE FROM attendance a USING attendance b "
            "WHERE a.session_id = b.session_id AND a.member_id = b.member_id "
            "AND (a.checked_in_at, a.id) > (b.checked_in_at, b.id)"
        )
    )

    op.create_unique_constraint(
        "uq_attendance_session_member", "attendance", ["session_id", "member_id"]
    )
    op.create_check_constraint(
        "ck_attendance_member_xor_visitor",
        "attendance",
        "(member_id IS NULL) <> (visitor_name IS NULL)",
    )
    op.create_unique_constraint(
        "uq_member_federations_member_federation",
        "member_federations",
        ["member_id", "federation_id"],
    )
    # A unique index on a constant: every row has the same key, so a second
    # row is a duplicate. No column to add, no data to rewrite.
    op.create_index(
        "uq_dojo_settings_single_row",
        "dojo_settings",
        [sa.text("(true)")],
        unique=True,
    )
    op.create_unique_constraint("uq_federations_name", "federations", ["name"])


def downgrade() -> None:
    op.drop_constraint("uq_federations_name", "federations", type_="unique")
    op.drop_index("uq_dojo_settings_single_row", table_name="dojo_settings")
    op.drop_constraint(
        "uq_member_federations_member_federation",
        "member_federations",
        type_="unique",
    )
    op.drop_constraint("ck_attendance_member_xor_visitor", "attendance", type_="check")
    op.drop_constraint("uq_attendance_session_member", "attendance", type_="unique")
