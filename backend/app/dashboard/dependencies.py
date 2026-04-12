from typing import Annotated

from fastapi import Depends

from app.dashboard.repository import AbstractDashboardRepository, SqlDashboardRepository
from app.db.unit_of_work import AbstractUnitOfWork
from app.dependencies import get_uow


def get_dashboard_repo(
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> AbstractDashboardRepository:
    return SqlDashboardRepository(uow.session)
