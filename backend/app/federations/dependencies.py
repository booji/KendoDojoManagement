from typing import Annotated

from fastapi import Depends

from app.db.unit_of_work import AbstractUnitOfWork
from app.dependencies import get_uow
from app.federations.repository import (
    AbstractFederationRepository,
    SqlFederationRepository,
)


def get_federation_repo(
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> AbstractFederationRepository:
    return SqlFederationRepository(uow.session)
