"""fix anonymised_by type on members

Revision ID: a6b7c8d9e0f1
Revises: a5b6c7d8e9f0
Create Date: 2026-08-09

Pre-existing drift closed as part of issue #264. `f2a3b4c5d6e7` added
`members.anonymised_by` as `String(length=36)`, but the ORM
(`app.members.db_models.Member.anonymised_by`) has always declared it as
`UUIDType` (native `uuid` on Postgres) — `test_migrated_schema_matches_orm_metadata_exactly`
caught the resulting `modify_type` drift. Unlike the baseline's CREATE TABLE
fixes, `f2a3b4c5d6e7` itself was deliberately left unchanged (see its
docstring): `members` predates Alembic and this `ADD COLUMN` genuinely ran
against every real deployment's live table, so only a real forward `ALTER
COLUMN` — this migration — fixes it there; editing the historical file text
could not.

`USING anonymised_by::uuid` is required: Postgres does not implicitly cast
`varchar` to `uuid`. Values already in the column are always well-formed
UUIDs (the only writer is GDPR erasure, which stores `str(user_id)` — see
`app.members.service`), so the cast cannot fail on real data.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision: str = "a6b7c8d9e0f1"
down_revision: str | None = "a5b6c7d8e9f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "members",
        "anonymised_by",
        type_=PG_UUID(as_uuid=False),
        postgresql_using="anonymised_by::uuid",
    )


def downgrade() -> None:
    op.alter_column(
        "members",
        "anonymised_by",
        type_=sa.String(length=36),
        postgresql_using="anonymised_by::text",
    )
