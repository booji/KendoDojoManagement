"""add checkin window default minutes to dojo settings

Revision ID: c9d0e1f2a3b4
Revises: b7c8d9e0f1a2
Create Date: 2026-07-06

"""

import sqlalchemy as sa

from alembic import op

revision = "c9d0e1f2a3b4"
down_revision = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "dojo_settings",
        sa.Column(
            "checkin_window_before_minutes",
            sa.Integer(),
            nullable=False,
            server_default="60",
        ),
    )
    op.add_column(
        "dojo_settings",
        sa.Column(
            "checkin_window_after_minutes",
            sa.Integer(),
            nullable=False,
            server_default="120",
        ),
    )


def downgrade() -> None:
    op.drop_column("dojo_settings", "checkin_window_after_minutes")
    op.drop_column("dojo_settings", "checkin_window_before_minutes")
