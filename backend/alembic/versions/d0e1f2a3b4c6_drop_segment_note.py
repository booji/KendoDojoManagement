"""drop the per-segment note columns

Issue #406 — the optional per-segment `note` is removed entirely, from both
`session_template_segments` and `session_instance_segments`. Segment `title`
stays.

This reverses the baseline, which created both columns (originally added for
#182 alongside `title`). What supersedes it: the session-level `info` field,
which is where free prose about a session belongs. A note attached to one
block of the timetable only reads correctly *next to* that block — in the
calendar feed it became a fragment appended to a segment line, and in practice
the same text was written into `info` anyway, where it is legible without the
reader mapping prose onto a timetable. Per-segment `title` covers the job the
field was reached for (naming a block); per-segment prose does not earn a
column. Same reasoning, and the same shape, as `b7c8d9e0f1a2` dropping the
per-segment `coach_notes` for #190.

Existing note text is dropped, deliberately and not recoverably: the premise
of the removal is that those fragments are not worth reading outside the
segment they hung off, so folding them into `info` would import exactly the
unreadability this removes. `downgrade()` therefore restores the schema but
not the data — it re-creates both columns empty and nullable.

Revision ID: d0e1f2a3b4c6
Revises: c9d0e1f2a3b5
Create Date: 2026-09-13

"""

import sqlalchemy as sa

from alembic import op

revision = "d0e1f2a3b4c6"
down_revision = "c9d0e1f2a3b5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("session_template_segments") as batch_op:
        batch_op.drop_column("note")
    with op.batch_alter_table("session_instance_segments") as batch_op:
        batch_op.drop_column("note")


def downgrade() -> None:
    # Schema only — the text is gone. See the module docstring.
    with op.batch_alter_table("session_template_segments") as batch_op:
        batch_op.add_column(sa.Column("note", sa.String(length=280), nullable=True))
    with op.batch_alter_table("session_instance_segments") as batch_op:
        batch_op.add_column(sa.Column("note", sa.String(length=280), nullable=True))
