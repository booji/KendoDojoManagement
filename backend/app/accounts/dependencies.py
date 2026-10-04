from typing import Annotated

from fastapi import Depends

from app.accounts.preferences_repository import (
    AbstractAccountPrefsRepo,
    SqlAccountPrefsRepo,
)
from app.db.unit_of_work import AbstractUnitOfWork
from app.dependencies import get_uow


def get_account_prefs_repo(
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> AbstractAccountPrefsRepo:
    return SqlAccountPrefsRepo(uow.session)
