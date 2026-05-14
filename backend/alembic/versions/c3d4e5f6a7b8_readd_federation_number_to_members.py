"""readd federation_number to members

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-05-05

"""
import sqlalchemy as sa

from alembic import op

revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "members",
        sa.Column("federation_number", sa.String(50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("members", "federation_number")
