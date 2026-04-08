from typing import Annotated

from fastapi import Depends

from app.db.unit_of_work import AbstractUnitOfWork
from app.dependencies import get_uow
from app.grades.repository import AbstractGradeRepository, SqlGradeRepository


def get_grade_repo(
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> AbstractGradeRepository:
    return SqlGradeRepository(uow.session)
