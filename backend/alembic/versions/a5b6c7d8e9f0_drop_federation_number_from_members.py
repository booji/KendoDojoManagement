"""drop federation_number from members

Revision ID: a5b6c7d8e9f0
Revises: a4b5c6d7e8f9
Create Date: 2026-08-09

Pre-existing drift closed as part of issue #264. `c3d4e5f6a7b8` ("readd
federation_number to members") added this column back after
`b2c3d4e5f6a7` introduced the `member_federations` table (per-federation
membership numbers superseding a single flat column on `members`), but no
migration ever removed it again — even though the ORM `Member` model
(`app.members.db_models`) has never had it back, and AC20 in
`test_federation.py` (`test_member_db_model_has_no_federation_number_column`)
already asserts the model doesn't have it. `test_migrated_schema_matches_orm_metadata_exactly`
caught the resulting drift: the migrated schema still had the column, the
ORM metadata didn't. This migration is the missing drop.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a5b6c7d8e9f0"
down_revision: str | None = "a4b5c6d7e8f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("members", "federation_number")


def downgrade() -> None:
    op.add_column(
        "members",
        sa.Column("federation_number", sa.String(50), nullable=True),
    )
