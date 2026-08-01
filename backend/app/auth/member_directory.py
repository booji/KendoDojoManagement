"""Narrow port auth uses to ask questions about Members.

Auth needs to know exactly two things about the members domain:
1. Is there an admin-created Member row for this email? (registration gate)
2. Link a newly-created User to its matching Member row.

Everything else about Member stays inside app.members — this module hides
that repository behind the two questions auth actually asks, per the
deep-modules convention in CLAUDE.md.
"""

from typing import Protocol, runtime_checkable

from app.db.unit_of_work import AbstractUnitOfWork
from app.members.repository import AbstractMemberRepository, SqlMemberRepository


@runtime_checkable
class MemberDirectory(Protocol):
    async def has_member(self, email: str) -> bool: ...

    async def link_user(self, email: str, user_id: str) -> None: ...


class RepositoryMemberDirectory:
    def __init__(self, repo: AbstractMemberRepository) -> None:
        self._repo = repo

    async def has_member(self, email: str) -> bool:
        return await self._repo.get_by_email(email) is not None

    async def link_user(self, email: str, user_id: str) -> None:
        member = await self._repo.get_by_email(email)
        if member is not None:
            await self._repo.update(member["id"], {"user_id": user_id})


def member_directory_for(uow: AbstractUnitOfWork) -> MemberDirectory:
    return RepositoryMemberDirectory(SqlMemberRepository(uow.session))
