"""Stored emails are folded to lowercase (#592).

Lookups compare exactly against the `LenientEmail` form, which is now all
lowercase, so the rows written before the fix are folded to match. Two
Members whose emails differ only by case would collide; the migration
refuses, naming them, rather than pick one.
"""

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from tests.migration_support import sql, upgrade

_BEFORE = "c1d2e3f4a5b7"
_AFTER = "d2e3f4a5b6c8"


def member(member_id: str, email: str) -> str:
    return f"""INSERT INTO members (id, email, first_name, surname, join_date,
        membership_status, is_coach, is_first_aider)
        VALUES ('{member_id}', '{email}', 'Ai', 'Sato', '2026-01-01', 'active',
                false, false)"""


def invite(email: str) -> str:
    return f"""INSERT INTO invites (id, email, first_name, surname, token_hash,
        expires_at, created_at)
        VALUES ('{uuid.uuid4()}', '{email}', 'Ai', 'Sato', '{uuid.uuid4().hex}',
                now(), now())"""


async def test_upgrade_folds_member_and_invite_emails(scratch_db):
    await upgrade(scratch_db, _BEFORE)
    await sql(
        scratch_db,
        member(str(uuid.uuid4()), "Kenji@dojo.test"),
        invite("Hana@dojo.test"),
    )

    await upgrade(scratch_db, _AFTER)

    assert await sql(scratch_db, "SELECT email FROM members") == [("kenji@dojo.test",)]
    assert await sql(scratch_db, "SELECT email FROM invites") == [("hana@dojo.test",)]


async def test_upgrade_refuses_emails_that_differ_only_by_case(scratch_db):
    await upgrade(scratch_db, _BEFORE)
    first, second = str(uuid.uuid4()), str(uuid.uuid4())
    await sql(
        scratch_db,
        member(first, "Kenji@dojo.test"),
        member(second, "kenji@dojo.test"),
    )

    with pytest.raises(RuntimeError) as aborted:
        await upgrade(scratch_db, _AFTER)

    assert first in str(aborted.value)
    assert second in str(aborted.value)
    emails = await sql(scratch_db, "SELECT email FROM members ORDER BY email")
    assert emails == [("Kenji@dojo.test",), ("kenji@dojo.test",)]


async def test_the_database_refuses_an_email_that_is_not_lowercase(scratch_db):
    # Lookups match exactly, so a writer that skips LenientEmail must fail
    # loudly rather than store an address no one can sign in with.
    await upgrade(scratch_db, _AFTER)

    with pytest.raises(IntegrityError, match="ck_members_email_lowercase"):
        await sql(scratch_db, member(str(uuid.uuid4()), "Kenji@dojo.test"))
