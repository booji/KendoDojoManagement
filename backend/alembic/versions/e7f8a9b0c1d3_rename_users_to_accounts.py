"""rename users to accounts

Issue #436 (decided in the #418 schema review). "User" sounds like a person,
but the person is always the Member; the glossary calls the sign-in an
Account, and the code now does too.

A rename, not a copy: rows, and the foreign keys that point at the table,
follow it. The named constraints and the primary key are renamed to match.
Foreign-key columns elsewhere stay `user_id`.

Revision ID: e7f8a9b0c1d3
Revises: d6e7f8a9b0c2
Create Date: 2026-10-04

"""

from alembic import op

revision = "e7f8a9b0c1d3"
down_revision = "d6e7f8a9b0c2"
branch_labels = None
depends_on = None


def _rename(old: str, new: str) -> None:
    op.rename_table(old, new)
    for name in ("{}_pkey", "uq_{}_member_id", "fk_{}_member_id"):
        op.execute(
            f"ALTER TABLE {new} RENAME CONSTRAINT "
            f"{name.format(old)} TO {name.format(new)}"
        )


def upgrade() -> None:
    _rename("users", "accounts")


def downgrade() -> None:
    _rename("accounts", "users")
