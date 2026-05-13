from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends

from app.db.unit_of_work import AbstractUnitOfWork
from app.dependencies import get_uow
from app.grades.repository import AbstractGradeRepository, SqlGradeRepository


async def get_grade_repo(
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> AsyncGenerator[AbstractGradeRepository]:
    yield SqlGradeRepository(uow.session)
    await uow.commit()
