from typing import Annotated

from fastapi import Depends

from app.auth.passkey_repository import AbstractPasskeyRepository, SqlPasskeyRepository
from app.auth.recovery_repository import (
    AbstractRecoveryRepository,
    SqlRecoveryRepository,
)
from app.db.unit_of_work import AbstractUnitOfWork
from app.dependencies import get_uow


def get_passkey_repo(
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> AbstractPasskeyRepository:
    return SqlPasskeyRepository(uow.session)


def get_recovery_repo(
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> AbstractRecoveryRepository:
    return SqlRecoveryRepository(uow.session)
