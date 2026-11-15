"""session instances: original_date and edited, for reconciling a series

Issue #578. Reconciling a Session Template with its recurrence (Extend
Series, a recurrence change) matched Sessions to the recurrence by their
current `date`. A Session's date is editable, so a moved Session no longer
matched its slot: it was deleted and its original date generated again, or,
once it had Attendance, the delete hit the foreign key and the extend failed
for good.

`original_date` is the date the template generated the Session for. It never
changes when the Session is moved, so reconciliation matches on it instead.
Ad-hoc Sessions have none.

`edited` records that an Admin has changed the Session (PUT /sessions/{id}).
Reconciliation never deletes an edited Session, even from a slot the
recurrence has dropped: the edit is Admin work the template does not know
about. Existing rows start unedited, since no record says otherwise.

Existing generated Sessions are backfilled with their current date: a Session
moved before this revision has lost its original date, and its current one is
the best record left. Should two Sessions of one template share a date, only
one is backfilled (lowest id) and the other is left without a slot, which
reconciliation never deletes. That keeps the backfill clear of the new
UNIQUE (template_id, original_date), audit C12: generation was
check-then-insert, which two concurrent extends could both pass.

Revision ID: a7b8c9d0e1f3
Revises: e3f4a5b6c7d9
Create Date: 2026-11-15

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a7b8c9d0e1f3"
down_revision: str | None = "e3f4a5b6c7d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "session_instances", sa.Column("original_date", sa.Date(), nullable=True)
    )
    op.execute(
        "UPDATE session_instances si SET original_date = si.date "
        "FROM ("
        "  SELECT id, row_number() OVER ("
        "    PARTITION BY template_id, date ORDER BY id"
        "  ) AS rn"
        "  FROM session_instances WHERE template_id IS NOT NULL"
        ") ranked "
        "WHERE si.id = ranked.id AND ranked.rn = 1"
    )
    op.create_unique_constraint(
        "uq_session_instances_template_slot",
        "session_instances",
        ["template_id", "original_date"],
    )
    op.add_column(
        "session_instances",
        sa.Column("edited", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_session_instances_template_slot", "session_instances", type_="unique"
    )
    op.drop_column("session_instances", "edited")
    op.drop_column("session_instances", "original_date")
