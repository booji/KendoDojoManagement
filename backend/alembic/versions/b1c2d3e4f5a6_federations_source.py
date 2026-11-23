"""federations: source and source_key, for the bundled FIK affiliate list

Issue #613. kendo-migrate syncs the FIK affiliate list shipped in
app/federations/fik_affiliates.json into the Federation catalogue. `source`
marks the rows the sync owns (`fik`; null for rows an Admin added) and
`source_key` is each affiliate's stable key (its ISO code, or a slug for the
continental and international bodies), so a renamed affiliate updates its row
instead of adding one. Existing rows are all Admin-added and keep null.

Revision ID: b1c2d3e4f5a6
Revises: a7b8c9d0e1f3
Create Date: 2026-11-23

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: str | None = "a7b8c9d0e1f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("federations", sa.Column("source", sa.String(20), nullable=True))
    op.add_column("federations", sa.Column("source_key", sa.String(20), nullable=True))
    op.create_unique_constraint(
        "uq_federations_source_key", "federations", ["source", "source_key"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_federations_source_key", "federations", type_="unique")
    op.drop_column("federations", "source_key")
    op.drop_column("federations", "source")
