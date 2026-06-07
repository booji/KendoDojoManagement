"""add_member_federations_table

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-04 00:01:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "member_federations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "member_id",
            sa.String(36),
            sa.ForeignKey("members.id"),
            nullable=False,
        ),
        sa.Column(
            "federation_id",
            sa.String(36),
            sa.ForeignKey("federations.id"),
            nullable=False,
        ),
        sa.Column("member_number", sa.String(100), nullable=False),
        sa.Column("renewal_date", sa.Date, nullable=True),
    )
    op.execute("ALTER TABLE members DROP COLUMN IF EXISTS federation_number")


def downgrade() -> None:
    op.drop_table("member_federations")
    op.add_column(
        "members",
        sa.Column("federation_number", sa.String(50), nullable=True),
    )
