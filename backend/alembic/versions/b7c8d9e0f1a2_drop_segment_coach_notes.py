"""drop per-segment coach_notes columns

Issue #190 — the per-segment coach_notes field is removed entirely from both
the template-segment and instance-segment tables. Session-level coach_notes on
templates and instances is untouched.

Revision ID: b7c8d9e0f1a2
Revises: a7b8c9d0e1f2
Create Date: 2026-07-06

"""

import sqlalchemy as sa

from alembic import op

revision = "b7c8d9e0f1a2"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("session_template_segments") as batch_op:
        batch_op.drop_column("coach_notes")
    with op.batch_alter_table("session_instance_segments") as batch_op:
        batch_op.drop_column("coach_notes")


def downgrade() -> None:
    with op.batch_alter_table("session_template_segments") as batch_op:
        batch_op.add_column(sa.Column("coach_notes", sa.Text(), nullable=True))
    with op.batch_alter_table("session_instance_segments") as batch_op:
        batch_op.add_column(sa.Column("coach_notes", sa.Text(), nullable=True))
