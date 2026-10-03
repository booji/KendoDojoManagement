"""drop session_instances.notes

Issue #430 (decided in the #418 schema review) — the free-text `notes` column
on `session_instances` is removed.

This reverses the baseline, which created the column before either audience
field existed. What supersedes it: `info`, shown to Members, and
`coach_notes`, shown to coaches. Between them they cover both audiences; a
third free-text field with no stated audience is where content goes to be
ignored. It had also stopped being editable — the edit form sent it, but
`SessionInstanceUpdate` never declared it, so every change was dropped.

Existing text is dropped, deliberately and not recoverably, as with
`d0e1f2a3b4c6` for the per-segment note: the field had no audience, so there
is no right place to fold it into. `downgrade()` therefore restores the schema
but not the data — it re-creates the column empty and nullable.

Revision ID: e1f2a3b4c5d7
Revises: d0e1f2a3b4c6
Create Date: 2026-10-03

"""

import sqlalchemy as sa

from alembic import op

revision = "e1f2a3b4c5d7"
down_revision = "d0e1f2a3b4c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("session_instances") as batch_op:
        batch_op.drop_column("notes")


def downgrade() -> None:
    # Schema only — the text is gone. See the module docstring.
    with op.batch_alter_table("session_instances") as batch_op:
        batch_op.add_column(sa.Column("notes", sa.String(length=1000), nullable=True))
