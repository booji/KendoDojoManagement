from typing import Annotated

from fastapi import Depends

from app.db.unit_of_work import AbstractUnitOfWork
from app.dependencies import get_uow
from app.members.repository import AbstractMemberRepository, SqlMemberRepository


def get_member_repo(
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> AbstractMemberRepository:
    return SqlMemberRepository(uow.session)
