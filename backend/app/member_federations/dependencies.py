from typing import Annotated

from fastapi import Depends

from app.db.unit_of_work import AbstractUnitOfWork
from app.dependencies import get_uow
from app.member_federations.repository import (
    AbstractMemberFederationRepository,
    SqlMemberFederationRepository,
)


def get_member_federation_repo(
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> AbstractMemberFederationRepository:
    return SqlMemberFederationRepository(uow.session)
