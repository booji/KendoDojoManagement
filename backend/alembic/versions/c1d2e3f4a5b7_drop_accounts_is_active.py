"""drop accounts.is_active

Issue #484. `accounts.is_active` (created as `users.is_active` in the
baseline) was meant to say whether an Account may sign in, but nothing ever
set it false: every write was `True` at creation. Meanwhile a Member's
Membership Status, which an Admin does change, was never consulted, so an
archived or suspended Member kept full access.

Sign-in eligibility now comes from the Member's `membership_status` alone:
`archived` and `suspended` are refused at sign-in and on every authenticated
request, read through the Auth Session join (ADR-0008); `inactive` keeps
access. The rule lives in `app.auth.accounts.MAY_SIGN_IN`. Two flags that
had to agree were one flag too many, so the column goes.

Downgrade restores the column as all-true, which is what every row held.

Revision ID: c1d2e3f4a5b7
Revises: b0c1d2e3f4a6
Create Date: 2026-10-31

"""

import sqlalchemy as sa

from alembic import op

revision = "c1d2e3f4a5b7"
down_revision = "b0c1d2e3f4a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("accounts", "is_active")


def downgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.alter_column("accounts", "is_active", server_default=None)
