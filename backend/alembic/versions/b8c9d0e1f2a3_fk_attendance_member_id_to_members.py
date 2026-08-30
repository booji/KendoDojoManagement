"""add foreign key from attendance.member_id to members.id

Revision ID: b8c9d0e1f2a3
Revises: a6b7c8d9e0f1
Create Date: 2026-08-30

Issue #340. The column held a User id for a self check-in and a Member id
when an admin marked someone present, so it could not have referenced either
table. Both check-in routes now resolve the caller's Member record before
writing (`app.members.dependencies.get_current_member_id`), which makes the
column single-valued and the reference expressible.

The constraint is what stops the ambiguity coming back: a User id written
into this column is now rejected by the database rather than discovered
later by a join that returns no name.

NULL stays legal -- a visitor row carries `visitor_name` and no member.

No ON DELETE clause, because nothing deletes a member: GDPR erasure
(`app.members.router`) scrubs the row in place and stamps `anonymised_at`,
keeping the id and with it the attendance history. The default (RESTRICT)
is therefore the honest declaration -- a member with attendance cannot be
hard-deleted without deciding what happens to that history first.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b8c9d0e1f2a3"
down_revision: str | None = "a6b7c8d9e0f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_foreign_key(
        "attendance_member_id_fkey", "attendance", "members", ["member_id"], ["id"]
    )


def downgrade() -> None:
    op.drop_constraint("attendance_member_id_fkey", "attendance", type_="foreignkey")
