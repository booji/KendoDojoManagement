"""every account belongs to a member, with one email address

Issue #432, decided in the #418 schema review (sections 6 and 7); the
reasoning is ADR-0006 (`docs/adr/0006-accounts-and-members-stay-separate-tables.md`).

A Member is the kendoka; an Account (`users`) is how a Member signs in. Every
Account belongs to exactly one Member, the first Admin included, and most
Members have no Account.

This reverses two columns the baseline created:

- `members.user_id` is dropped. The nullable link pointed the wrong way: it let
  an Account exist with no Member at all, and nothing stopped two Members
  naming the same Account. What supersedes it is `users.member_id` — NOT NULL,
  UNIQUE, and a foreign key with ON DELETE RESTRICT (Members are deactivated
  or anonymised, never hard-deleted).
- `users.email` is dropped. The address was stored twice, and the two copies
  drifted: an admin could change a Member's email and the Account kept signing
  in with the old one. What supersedes it is `members.email`, now both the
  contact address and the sign-in identifier.

Existing rows are repaired only where the answer is unambiguous:

- A `members.user_id` naming an Account that no longer exists is set NULL
  first — what ON DELETE SET NULL would have done, had there been a key.
- An Account with no Member that nobody can sign in to — no passkey, and no
  recovery code or admin recovery token either — is deleted. The old setup
  claim created one per abandoned attempt (a mistyped email, a cancelled
  passkey prompt), and they hold nothing worth keeping.

Everything else aborts with a RuntimeError naming the rows, before any change
(`setup.sh upgrade` backs up first, so an abort costs a retry, not data):

- an Account with no Member that someone can still sign in to (a first
  Admin who never completed onboarding);
- two Members linked to one Account;
- a linked Account and Member whose emails differ (the drift above).

`downgrade()` restores both columns from the link and the Member's email; it
cannot restore an Account email that differed, because none survives.

Revision ID: b4c5d6e7f8a0
Revises: f2a3b4c5d6e8
Create Date: 2026-10-03

"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision = "b4c5d6e7f8a0"
down_revision = "f2a3b4c5d6e8"
branch_labels = None
depends_on = None


def _ids(rows) -> str:
    return ", ".join(str(r) for r in rows)


def _refuse_what_needs_a_human(conn) -> None:
    problems = []

    for user_id, email in conn.execute(
        sa.text(
            "SELECT u.id, u.email FROM users u "
            "WHERE NOT EXISTS (SELECT 1 FROM members m WHERE m.user_id = u.id) "
            "ORDER BY u.id"
        )
    ):
        problems.append(
            f"account {user_id} ({email}) belongs to no member. Sign in as "
            f"{email}, complete Personal Details, then run ./setup.sh upgrade "
            "again."
        )

    for user_id, member_ids in conn.execute(
        sa.text(
            "SELECT user_id, array_agg(id ORDER BY id) FROM members "
            "WHERE user_id IS NOT NULL GROUP BY user_id HAVING count(*) > 1"
        )
    ):
        problems.append(
            f"account {user_id} is linked to more than one member "
            f"({_ids(member_ids)}). Clear members.user_id on all but the "
            "member who signs in with it."
        )

    for user_id, account_email, member_id, member_email in conn.execute(
        sa.text(
            "SELECT u.id, u.email, m.id, m.email FROM users u "
            "JOIN members m ON m.user_id = u.id "
            "WHERE m.email IS DISTINCT FROM u.email ORDER BY u.id"
        )
    ):
        problems.append(
            f"account {user_id} signs in as {account_email} but its member "
            f"{member_id} has the email {member_email}. Set the member's email "
            "to the address that should sign in."
        )

    if problems:
        raise RuntimeError(
            "Cannot move the account link onto users (#432): fix these by hand, "
            "then re-run the upgrade. Nothing has been changed.\n- "
            + "\n- ".join(problems)
        )


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE members SET user_id = NULL WHERE user_id IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM users u WHERE u.id = members.user_id)"
        )
    )
    # Phantoms from abandoned setup claims; see the docstring. Invites point
    # here too, but ON DELETE SET NULL, so they do not hold an Account back.
    conn.execute(
        sa.text(
            "DELETE FROM users u "
            "WHERE NOT EXISTS (SELECT 1 FROM members m WHERE m.user_id = u.id) "
            "AND NOT EXISTS (SELECT 1 FROM passkey_credentials p WHERE p.user_id = u.id) "
            "AND NOT EXISTS (SELECT 1 FROM recovery_codes r WHERE r.user_id = u.id) "
            "AND NOT EXISTS (SELECT 1 FROM recovery_attempts a WHERE a.user_id = u.id) "
            "AND NOT EXISTS (SELECT 1 FROM admin_recovery_tokens t "
            "WHERE t.user_id = u.id OR t.created_by_id = u.id)"
        )
    )
    _refuse_what_needs_a_human(conn)

    op.add_column(
        "users", sa.Column("member_id", PG_UUID(as_uuid=False), nullable=True)
    )
    conn.execute(
        sa.text(
            "UPDATE users SET member_id = m.id FROM members m WHERE m.user_id = users.id"
        )
    )
    op.alter_column("users", "member_id", nullable=False)
    op.create_unique_constraint("uq_users_member_id", "users", ["member_id"])
    op.create_foreign_key(
        "fk_users_member_id",
        "users",
        "members",
        ["member_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_column("members", "user_id")
    op.drop_column("users", "email")


def downgrade() -> None:
    op.add_column("users", sa.Column("email", sa.String(255), nullable=True))
    op.add_column(
        "members", sa.Column("user_id", PG_UUID(as_uuid=False), nullable=True)
    )
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE users SET email = m.email FROM members m WHERE m.id = users.member_id"
        )
    )
    conn.execute(
        sa.text(
            "UPDATE members SET user_id = u.id FROM users u WHERE u.member_id = members.id"
        )
    )
    op.alter_column("users", "email", nullable=False)
    op.create_unique_constraint("users_email_key", "users", ["email"])
    op.drop_constraint("fk_users_member_id", "users", type_="foreignkey")
    op.drop_constraint("uq_users_member_id", "users", type_="unique")
    op.drop_column("users", "member_id")
