"""add end_date to session_templates

Revision ID: a4b5c6d7e8f9
Revises: a3b4c5d6e7f8
Create Date: 2026-08-08

"""

import sqlalchemy as sa

from alembic import op

revision = "a4b5c6d7e8f9"
down_revision = "a3b4c5d6e7f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable at first so existing rows can be backfilled before the
    # NOT NULL constraint is applied.
    op.add_column(
        "session_templates",
        sa.Column("end_date", sa.String(length=10), nullable=True),
    )
    # Bounded recurrence (issue #258): every existing template gets an
    # end_date of "today + 6 months" at migration time. This is per-row
    # relative to the migration's run date, so it cannot be expressed as a
    # static server_default literal — a data migration via op.execute is
    # required instead. Instances already generated beyond that date are
    # left untouched; nothing here touches session_instances.
    op.execute(
        "UPDATE session_templates "
        "SET end_date = to_char(CURRENT_DATE + INTERVAL '6 months', 'YYYY-MM-DD') "
        "WHERE end_date IS NULL"
    )
    op.alter_column("session_templates", "end_date", nullable=False)


def downgrade() -> None:
    op.drop_column("session_templates", "end_date")
