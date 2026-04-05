from typing import Annotated

from fastapi import Depends

from app.db.unit_of_work import AbstractUnitOfWork
from app.dependencies import get_uow
from app.users.preferences_repository import AbstractUserPrefsRepo, SqlUserPrefsRepo


def get_user_prefs_repo(
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> AbstractUserPrefsRepo:
    return SqlUserPrefsRepo(uow.session)
