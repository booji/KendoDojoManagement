"""members.claim_attempted_at

Issue #446. Since #432 the first-admin claim creates the claimant's Member
and Account at begin. A claim begun under one address and finished under
another left the first attempt's Member on the roster, and its Account open
to the ordinary registration route. Completing a claim now removes those, and
this column is how it tells them from the roster: set when a claim's begin
creates the Member, cleared when that claim completes. Existing rows stay
NULL, so no Member already on the roster can be taken for a claim attempt.

Revision ID: f8a9b0c1d2e4
Revises: e7f8a9b0c1d3
Create Date: 2026-10-04

"""

import sqlalchemy as sa

from alembic import op

revision = "f8a9b0c1d2e4"
down_revision = "e7f8a9b0c1d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "members",
        sa.Column("claim_attempted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("members", "claim_attempted_at")
