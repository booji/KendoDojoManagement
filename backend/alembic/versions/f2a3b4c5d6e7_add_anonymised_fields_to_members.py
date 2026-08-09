"""add anonymised_at and anonymised_by to members

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-07-26

Deliberately left as originally written (`anonymised_by` as
`String(length=36)`), unlike the CREATE TABLE migrations touched by issue
#264 (`a1b2c3d4e5f6`, `b2c3d4e5f6a7`, `a3b4c5d6e7f8`). Those three create
tables (`federations`, `member_federations`, `invites`) that, under the
pre-#264 bootstrap, every real deployment actually got from
`Base.metadata.create_all` — not from this chain's own `CREATE TABLE`
statements ever executing — so correcting their declared column types to
match the ORM changes nothing about any live deployment's real schema, only
the migration's *description* of a CREATE TABLE that (for any real
deployment) never really ran. `members`, in contrast, predates Alembic
entirely and has existed via `create_all` on every deployment since day
one, so this `ADD COLUMN` genuinely executed against every real
deployment's live table once its `alembic_version` passed this revision —
editing this file cannot retroactively fix an already-applied column's real
type, since Alembic never re-runs a revision already recorded as applied.
Doing so anyway would have made this file lie about what already happened
while leaving every such deployment's `anonymised_by` silently `VARCHAR(36)`
forever — exactly the class of drift issue #264 exists to close. The actual
fix is the forward `ALTER COLUMN` in
`a6b7c8d9e0f1_fix_anonymised_by_type_on_members.py`, which runs for real on
every deployment (including ones that already have this column) the next
time it upgrades.
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
