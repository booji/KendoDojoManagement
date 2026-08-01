"""add anonymised_at and anonymised_by to members

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-07-26

"""

import sqlalchemy as sa

from alembic import op

revision = "f2a3b4c5d6e7"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "members",
        sa.Column("anonymised_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "members",
        sa.Column("anonymised_by", sa.String(length=36), nullable=True),
    )
    # GDPR erasure scrubs email to NULL; Postgres treats multiple NULLs as
    # distinct so the existing unique constraint still holds.
    op.alter_column(
        "members", "email", existing_type=sa.String(length=255), nullable=True
    )


def downgrade() -> None:
    op.alter_column(
        "members", "email", existing_type=sa.String(length=255), nullable=False
    )
    op.drop_column("members", "anonymised_by")
    op.drop_column("members", "anonymised_at")
