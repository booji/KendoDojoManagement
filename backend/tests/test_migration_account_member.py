"""Every Account belongs to exactly one Member, with one email (#432).

The link moves from the nullable `members.user_id` to `users.member_id`
(NOT NULL, UNIQUE, ON DELETE RESTRICT), and `users.email` goes: the address
lives once, on the Member. The migration repairs only what is unambiguous and
aborts, naming the rows, on the rest.
"""

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from tests.migration_support import sql, upgrade

# The revision before the move, for seeding the old shape.
_BEFORE = "f2a3b4c5d6e8"
# This migration. Pinned rather than head: #436 later renames `users`.
_AFTER = "b4c5d6e7f8a0"


def member(member_id: str, email: str | None, user_id: str | None = None) -> str:
    """A Member row; `user_id` is the pre-#432 link, so pass it only before."""
    email_sql = f"'{email}'" if email else "NULL"
    link_column, link_value = (", user_id", f", '{user_id}'") if user_id else ("", "")
    return f"""INSERT INTO members (id, email, first_name, surname, join_date,
        membership_status, is_coach, is_first_aider{link_column})
        VALUES ('{member_id}', {email_sql}, 'Ai', 'Sato', '2026-01-01', 'active',
                false, false{link_value})"""


def old_account(user_id: str, email: str) -> str:
    return f"""INSERT INTO users (id, email, role, is_active, theme)
        VALUES ('{user_id}', '{email}', 'member', true, 'system')"""


def account(user_id: str, member_id: str | None) -> str:
    member_sql = f"'{member_id}'" if member_id else "NULL"
    return f"""INSERT INTO users (id, member_id, role, is_active, theme)
        VALUES ('{user_id}', {member_sql}, 'member', true, 'system')"""


# ---------------------------------------------------------------------------
# The database holds the rule
# ---------------------------------------------------------------------------


async def test_an_account_cannot_exist_without_a_member(scratch_db):
    await upgrade(scratch_db, _AFTER)

    with pytest.raises(IntegrityError, match="member_id"):
        await sql(scratch_db, account(str(uuid.uuid4()), None))


async def test_two_accounts_cannot_belong_to_one_member(scratch_db):
    await upgrade(scratch_db, _AFTER)
    member_id = str(uuid.uuid4())
    await sql(
        scratch_db,
        member(member_id, "ai@dojo.test"),
        account(str(uuid.uuid4()), member_id),
    )

    with pytest.raises(IntegrityError, match="uq_users_member_id"):
        await sql(scratch_db, account(str(uuid.uuid4()), member_id))


async def test_a_member_with_an_account_cannot_be_deleted(scratch_db):
    # Members are deactivated or anonymised, never hard-deleted (RESTRICT).
    await upgrade(scratch_db, _AFTER)
    member_id = str(uuid.uuid4())
    await sql(
        scratch_db,
        member(member_id, "ai@dojo.test"),
        account(str(uuid.uuid4()), member_id),
    )

    with pytest.raises(IntegrityError, match="fk_users_member_id"):
        await sql(scratch_db, f"DELETE FROM members WHERE id = '{member_id}'")


# ---------------------------------------------------------------------------
# Existing rows
# ---------------------------------------------------------------------------


async def test_upgrade_moves_the_link_onto_the_account(scratch_db):
    await upgrade(scratch_db, _BEFORE)
    user_id, member_id = str(uuid.uuid4()), str(uuid.uuid4())
    unlinked = str(uuid.uuid4())
    await sql(
        scratch_db,
        old_account(user_id, "ai@dojo.test"),
        member(member_id, "ai@dojo.test", user_id),
        member(unlinked, "ken@dojo.test"),
    )

    await upgrade(scratch_db, _AFTER)

    rows = await sql(scratch_db, "SELECT id, member_id FROM users")
    assert [(str(r[0]), str(r[1])) for r in rows] == [(user_id, member_id)]
    columns = await sql(
        scratch_db,
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE (table_name, column_name) IN (('users', 'email'), ('members', 'user_id'))",
    )
    assert columns == []


async def test_upgrade_drops_a_link_to_an_account_that_no_longer_exists(scratch_db):
    # What ON DELETE SET NULL would have done, had there been a foreign key.
    await upgrade(scratch_db, _BEFORE)
    member_id = str(uuid.uuid4())
    await sql(scratch_db, member(member_id, "ai@dojo.test", str(uuid.uuid4())))

    await upgrade(scratch_db, _AFTER)

    rows = await sql(scratch_db, "SELECT id FROM members")
    assert [str(r[0]) for r in rows] == [member_id]
    assert await sql(scratch_db, "SELECT count(*) FROM users") == [(0,)]


async def test_upgrade_deletes_an_account_nobody_can_sign_in_to(scratch_db):
    # A phantom from an abandoned first-run claim: no Member, no passkey, and
    # nothing pointing at it. It cannot be signed in to, so "sign in and
    # complete Personal Details" would be an instruction nobody can follow.
    await upgrade(scratch_db, _BEFORE)
    await sql(scratch_db, old_account(str(uuid.uuid4()), "typo@dojo.tst"))

    await upgrade(scratch_db, _AFTER)

    assert await sql(scratch_db, "SELECT count(*) FROM users") == [(0,)]


def _account_with_no_member() -> tuple[list[str], list[str]]:
    # One somebody can sign in to: it has a passkey.
    user_id = str(uuid.uuid4())
    return [
        old_account(user_id, "admin@dojo.test"),
        f"""INSERT INTO passkey_credentials
            (id, user_id, credential_id, public_key, sign_count, label, created_at)
            VALUES ('{uuid.uuid4()}', '{user_id}', '\\xbeef', '\\xbeef', 0, 'k', now())""",
    ], [user_id, "Personal Details"]


def _two_members_one_account() -> tuple[list[str], list[str]]:
    user_id, a, b = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    return [
        old_account(user_id, "ai@dojo.test"),
        member(a, "ai@dojo.test", user_id),
        member(b, "ai2@dojo.test", user_id),
    ], [user_id, a, b]


def _emails_disagree() -> tuple[list[str], list[str]]:
    user_id, member_id = str(uuid.uuid4()), str(uuid.uuid4())
    return [
        old_account(user_id, "old@dojo.test"),
        member(member_id, "new@dojo.test", user_id),
    ], [user_id, member_id, "old@dojo.test", "new@dojo.test"]


@pytest.mark.parametrize(
    "violation",
    [_account_with_no_member, _two_members_one_account, _emails_disagree],
    ids=["account-without-member", "two-members", "emails-disagree"],
)
async def test_upgrade_aborts_naming_what_needs_a_human(scratch_db, violation):
    await upgrade(scratch_db, _BEFORE)
    statements, named = violation()
    await sql(scratch_db, *statements)

    with pytest.raises(RuntimeError) as aborted:
        await upgrade(scratch_db, _AFTER)

    message = str(aborted.value)
    assert "fix these by hand" in message
    for fragment in named:
        assert fragment in message
    version = await sql(scratch_db, "SELECT version_num FROM alembic_version")
    assert version[0][0] == _BEFORE
