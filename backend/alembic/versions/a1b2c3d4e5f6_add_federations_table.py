"""add_federations_table

Revision ID: a1b2c3d4e5f6
Revises: 000000000000
Create Date: 2026-05-04 00:00:00.000000

Column types/lengths were corrected as part of issue #264 (see the baseline
migration's docstring): `id` is now `postgresql.UUID` to match the ORM's
`UUIDType`, and `website`/`continental_grouping` now use the lengths the ORM
(`app.federations.db_models.Federation`) actually declares (512 and 50) —
both were flagged as drift by `test_migrated_schema_matches_orm_metadata_exactly`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "000000000000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "federations",
        sa.Column("id", PG_UUID(as_uuid=False), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("abbreviation", sa.String(50), nullable=True),
        sa.Column("iso_code", sa.String(10), nullable=True),
        sa.Column("website", sa.String(512), nullable=True),
        sa.Column("continental_grouping", sa.String(50), nullable=True),
        sa.Column("type", sa.String(50), nullable=True),
        sa.Column("is_pinned", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
    )


def downgrade() -> None:
    op.drop_table("federations")
