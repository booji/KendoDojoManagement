"""Narrow port auth uses to ask questions about Members.

Auth needs to know exactly two things about the members domain:
1. Is there an admin-created Member row for this email? (registration gate)
2. Link a newly-created User to its matching Member row.

Everything else about Member stays inside app.members — this module hides
that repository behind the two questions auth actually asks, per the
deep-modules convention in CLAUDE.md.
"""

from datetime import date
from typing import Protocol, runtime_checkable

from app.db.unit_of_work import AbstractUnitOfWork
from app.members.repository import AbstractMemberRepository, SqlMemberRepository


@runtime_checkable
class MemberDirectory(Protocol):
    async def has_member(self, email: str) -> bool: ...

    async def link_user(self, email: str, user_id: str) -> None: ...

    async def ensure_member_for_email(
        self, email: str, user_id: str, first_name: str, surname: str
    ) -> None: ...


class RepositoryMemberDirectory:
    def __init__(self, repo: AbstractMemberRepository) -> None:
        self._repo = repo

    async def has_member(self, email: str) -> bool:
        return await self._repo.get_by_email(email) is not None

    async def link_user(self, email: str, user_id: str) -> None:
        member = await self._repo.get_by_email(email)
        if member is not None:
            await self._repo.update(member["id"], {"user_id": user_id})

    async def ensure_member_for_email(
        self, email: str, user_id: str, first_name: str, surname: str
    ) -> None:
        """Create-or-link the Member row for an invited email (#257).

        The invite-redemption counterpart to `link_user`: the #239 Member
        gate assumes the Member row already exists (an admin created it
        first, making it the implicit invite), but an explicit invite may be
        issued for an email with no Member row yet. Both paths converge on
        the same Member.user_id linkage either way.

        The name comes from the invite the admin issued. An existing Member
        keeps whatever name it already has -- the register is the authority
        on someone already in it, not an invite raised later.
        """
        member = await self._repo.get_by_email(email)
        if member is None:
            await self._repo.add(
                {
                    "email": email,
                    "first_name": first_name,
                    "surname": surname,
                    "join_date": date.today().isoformat(),
                    "user_id": user_id,
                }
            )
        else:
            await self._repo.update(member["id"], {"user_id": user_id})


def member_directory_for(uow: AbstractUnitOfWork) -> MemberDirectory:
    return RepositoryMemberDirectory(SqlMemberRepository(uow.session))
