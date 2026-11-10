"""admin recovery token issuer: on delete set null

Issue #570. `admin_recovery_tokens.created_by_id` came from the baseline with
no ON DELETE rule, so erasing a Member whose Account had issued an admin
recovery token to someone else failed: `delete_account` removes only the
tokens issued *to* the Account, and the issuer reference blocked the delete.
Both callers of `delete_account` hit it (Member erasure and setup's removal of
abandoned claims).

The constraint is dropped and recreated under the same name, now SET NULL,
the rule invites' `issued_by` already has. The token keeps its row, so the
Account it was issued to can still use it; only the record of who issued it
goes with the issuer. The column was already nullable (a CLI-issued token has
no issuer).

Downgrade restores the default (NO ACTION). Tokens whose issuer was erased
keep a NULL `created_by_id`, which the old constraint also allows.

Revision ID: e3f4a5b6c7d9
Revises: d2e3f4a5b6c8
Create Date: 2026-11-10

"""

from collections.abc import Sequence

from alembic import op

revision: str = "e3f4a5b6c7d9"
down_revision: str | None = "d2e3f4a5b6c8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "admin_recovery_tokens_created_by_id_fkey",
        "admin_recovery_tokens",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "admin_recovery_tokens_created_by_id_fkey",
        "admin_recovery_tokens",
        "accounts",
        ["created_by_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "admin_recovery_tokens_created_by_id_fkey",
        "admin_recovery_tokens",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "admin_recovery_tokens_created_by_id_fkey",
        "admin_recovery_tokens",
        "accounts",
        ["created_by_id"],
        ["id"],
    )
