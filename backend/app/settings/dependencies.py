from typing import Annotated

from fastapi import Depends

from app.db.unit_of_work import AbstractUnitOfWork
from app.dependencies import get_uow
from app.settings.repository import (
    AbstractDojoSettingsRepository,
    SqlDojoSettingsRepository,
)


def get_dojo_settings_repo(
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> AbstractDojoSettingsRepository:
    return SqlDojoSettingsRepository(uow.session)
