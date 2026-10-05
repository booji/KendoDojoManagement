"""auth_sessions.kind

Issue #486 (design: #455, ADR-0008). Recovery tokens were JWTs, so a leaked
JWT_SECRET could forge one and enrol an attacker's passkey on any Account.
They are now Auth Session rows of kind `recovery`: 15 minutes, never slid,
deleted when the passkey they enrol is saved. Existing rows are sign-ins, so
the column defaults to `sign_in` (not `session`: a Session is a training
event, UBIQUITOUS_LANGUAGE.md).

Revision ID: b0c1d2e3f4a6
Revises: a9b0c1d2e3f5
Create Date: 2026-10-05

"""

import sqlalchemy as sa

from alembic import op

revision = "b0c1d2e3f4a6"
down_revision = "a9b0c1d2e3f5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "auth_sessions",
        sa.Column("kind", sa.String(10), nullable=False, server_default="sign_in"),
    )
    op.create_check_constraint(
        "ck_auth_sessions_kind", "auth_sessions", "kind IN ('sign_in', 'recovery')"
    )


def downgrade() -> None:
    # Without `kind`, a live recovery row would read as a sign-in.
    op.execute("DELETE FROM auth_sessions WHERE kind = 'recovery'")
    op.drop_constraint("ck_auth_sessions_kind", "auth_sessions", type_="check")
    op.drop_column("auth_sessions", "kind")
