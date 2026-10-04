"""recovery_attempts.ip_address nullable

Issue #434 (decided in the #418 schema review, section 5). recovery_attempts
kept every attempt's IP address forever. Rows themselves must stay -- lockout
counts an Account's failures since its last success with no time window, so
deleting by age would silently expire lockouts -- but after 30 days the
address is cleared to NULL (app.auth.attempt_repository.IP_RETENTION), which
needs the column nullable.

Upgrade also clears addresses already older than 30 days, rather than leaving
them until the next recovery attempt happens to run the clear. The 30 days is
written out here, not imported: a migration must not change when app code does.

Downgrade writes '' into cleared addresses so NOT NULL can be restored; the
addresses themselves are gone.

Revision ID: d6e7f8a9b0c2
Revises: c5d6e7f8a9b1
Create Date: 2026-10-04

"""

import sqlalchemy as sa

from alembic import op

revision = "d6e7f8a9b0c2"
down_revision = "c5d6e7f8a9b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "recovery_attempts",
        "ip_address",
        existing_type=sa.String(length=45),
        nullable=True,
    )
    op.execute(
        "UPDATE recovery_attempts SET ip_address = NULL "
        "WHERE attempted_at < now() - interval '30 days'"
    )


def downgrade() -> None:
    op.execute("UPDATE recovery_attempts SET ip_address = '' WHERE ip_address IS NULL")
    op.alter_column(
        "recovery_attempts",
        "ip_address",
        existing_type=sa.String(length=45),
        nullable=False,
    )
