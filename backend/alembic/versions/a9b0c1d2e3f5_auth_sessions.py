"""auth_sessions

Issue #485 (design: #455, ADR-0008). Auth Sessions were stateless JWTs that
nothing could revoke. Each one is now a row: the cookie carries a random id
and `token_hash` holds its SHA-256. Both foreign keys cascade, and that is the
revocation for erasure (the Account goes) and for removing a lost device's
passkey (the Auth Sessions it signed in go with it). `expires_at` is indexed
for the sweep of expired rows at sign-in.

Not `sessions`: a Session is a training event (GLOSSARY.md).

Revision ID: a9b0c1d2e3f5
Revises: f8a9b0c1d2e4
Create Date: 2026-10-05

"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision = "a9b0c1d2e3f5"
down_revision = "f8a9b0c1d2e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auth_sessions",
        sa.Column("id", PG_UUID(as_uuid=False), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "account_id",
            PG_UUID(as_uuid=False),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "passkey_id",
            PG_UUID(as_uuid=False),
            sa.ForeignKey("passkey_credentials.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_auth_sessions_account_id", "auth_sessions", ["account_id"])
    op.create_index("ix_auth_sessions_passkey_id", "auth_sessions", ["passkey_id"])
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])


def downgrade() -> None:
    op.drop_table("auth_sessions")
