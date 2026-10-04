from typing import Annotated

from fastapi import Depends

from app.auth.guards import REQUIRE_MEMBER
from app.auth.models import AccountClaims
from app.db.unit_of_work import AbstractUnitOfWork
from app.dependencies import get_uow
from app.members.admin_directory import AbstractAdminDirectory, SqlAdminDirectory
from app.members.repository import AbstractMemberRepository, SqlMemberRepository


def get_member_repo(
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> AbstractMemberRepository:
    return SqlMemberRepository(uow.session)


def get_admin_directory(
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> AbstractAdminDirectory:
    return SqlAdminDirectory(uow.session)


async def get_current_member_id(
    claims: Annotated[AccountClaims, Depends(REQUIRE_MEMBER)],
    member_repo: Annotated[AbstractMemberRepository, Depends(get_member_repo)],
) -> str | None:
    """The Member id of the caller, or None if their Account has no member record.

    Attendance is keyed by Member id (#340) while an access token carries an
    Account id, so every attendance path -- writing a self check-in, reading
    "am I checked in", reading a member's own history -- needs this mapping.
    Resolving it once here is what keeps the repositories speaking a single
    kind of identifier.

    None rather than a 403: an admin with no member record may legitimately
    read a session list (they are simply never checked in). Routes that must
    write attendance reject the None themselves.
    """
    member = await member_repo.get_by_user_id(claims.sub)
    return member["id"] if member else None
