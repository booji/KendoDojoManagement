from typing import Annotated

from fastapi import Depends

from app.db.unit_of_work import AbstractUnitOfWork
from app.dependencies import get_uow
from app.reports.repository import AbstractReportRepository, SqlReportRepository


def get_report_repo(
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> AbstractReportRepository:
    return SqlReportRepository(uow.session)
