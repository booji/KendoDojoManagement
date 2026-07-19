"""add_federations_table

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2026-05-04 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "federations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("abbreviation", sa.String(50), nullable=True),
        sa.Column("iso_code", sa.String(10), nullable=True),
        sa.Column("website", sa.String(500), nullable=True),
        sa.Column("continental_grouping", sa.String(100), nullable=True),
        sa.Column("type", sa.String(50), nullable=True),
        sa.Column("is_pinned", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
    )


def downgrade() -> None:
    op.drop_table("federations")
