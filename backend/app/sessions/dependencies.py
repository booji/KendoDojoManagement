from typing import Annotated

from fastapi import Depends

from app.db.unit_of_work import AbstractUnitOfWork
from app.dependencies import get_uow
from app.sessions.repository import (
    AbstractSessionInstanceRepository,
    AbstractSessionTemplateRepository,
    AbstractSessionTypeRepository,
    SqlSessionInstanceRepository,
    SqlSessionTemplateRepository,
    SqlSessionTypeRepository,
)


def get_session_type_repo(
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> AbstractSessionTypeRepository:
    return SqlSessionTypeRepository(uow.session)


def get_session_template_repo(
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> AbstractSessionTemplateRepository:
    return SqlSessionTemplateRepository(uow.session)


def get_session_instance_repo(
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> AbstractSessionInstanceRepository:
    return SqlSessionInstanceRepository(uow.session)
