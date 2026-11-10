"""lowercase emails

Issue #592. `LenientEmail` kept `email_validator`'s normalized form, which
lowercases the domain but leaves the part before the @ as typed. Every lookup
compares exactly, so a Member entered as `Kenji@…` could not sign in, or
redeem a recovery code, as `kenji@…`. `LenientEmail` now lowercases the whole
address; this folds the rows written before it to match. Invites are folded
too: redeeming one creates or finds the Member by its email.

Two Members whose emails differ only by case would collide on the unique
constraint. The upgrade refuses, naming their ids, and changes nothing: which
one is the real Member is for an Admin to decide, not a migration.

`ck_members_email_lowercase` then holds the rule: with every stored email
lowercase, the existing unique constraint is case-insensitive in effect and an
exact-match lookup is correct, so no query needs `lower()`. A writer that
skips `LenientEmail` fails loudly instead of storing an address no one can
sign in with.

Downgrade drops the constraint and leaves the addresses lowercase: the case
each was typed in is gone and cannot be recovered, and lowercase addresses are
valid under the old rules.

Revision ID: d2e3f4a5b6c8
Revises: c1d2e3f4a5b7
Create Date: 2026-11-09

"""

import sqlalchemy as sa

from alembic import op

revision = "d2e3f4a5b6c8"
down_revision = "c1d2e3f4a5b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    collisions = conn.execute(
        sa.text(
            "SELECT lower(email), string_agg(id::text, ', ' ORDER BY id) "
            "FROM members WHERE email IS NOT NULL "
            "GROUP BY lower(email) HAVING count(*) > 1 ORDER BY 1"
        )
    ).all()
    if collisions:
        raise RuntimeError(
            "Cannot lowercase members.email (#592): these Members' emails "
            "differ only by case. Change or clear all but one email in each "
            "group, then re-run the upgrade. Nothing has been changed.\n- "
            + "\n- ".join(f"{email}: members {ids}" for email, ids in collisions)
        )
    conn.execute(sa.text("UPDATE members SET email = lower(email)"))
    conn.execute(sa.text("UPDATE invites SET email = lower(email)"))
    op.create_check_constraint(
        "ck_members_email_lowercase", "members", "email = lower(email)"
    )


def downgrade() -> None:
    op.drop_constraint("ck_members_email_lowercase", "members", type_="check")
