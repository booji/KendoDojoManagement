"""add checkin window override minutes to session instances

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-07-08

"""

import sqlalchemy as sa

from alembic import op

revision = "d0e1f2a3b4c5"
down_revision = "c9d0e1f2a3b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "session_instances",
        sa.Column(
            "checkin_window_before_minutes",
            sa.Integer(),
            nullable=True,
        ),
    )
    op.add_column(
        "session_instances",
        sa.Column(
            "checkin_window_after_minutes",
            sa.Integer(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("session_instances", "checkin_window_after_minutes")
    op.drop_column("session_instances", "checkin_window_before_minutes")
