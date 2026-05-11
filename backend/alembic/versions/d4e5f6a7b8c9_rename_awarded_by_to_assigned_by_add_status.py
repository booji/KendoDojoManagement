"""rename awarded_by to assigned_by add status

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-05-11

"""

import sqlalchemy as sa

from alembic import op

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "grade_history",
        "awarded_by",
        new_column_name="assigned_by",
    )
    op.add_column(
        "grade_history",
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="confirmed",
        ),
    )


def downgrade() -> None:
    op.drop_column("grade_history", "status")
    op.alter_column(
        "grade_history",
        "assigned_by",
        new_column_name="awarded_by",
    )
