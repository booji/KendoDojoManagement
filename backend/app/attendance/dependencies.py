from typing import Annotated

from fastapi import Depends

from app.attendance.repository import (
    AbstractAttendanceRepository,
    AbstractCheckinTokenRepository,
    AbstractSessionInstanceRepository,
    SqlAttendanceRepository,
    SqlCheckinTokenRepository,
    SqlSessionInstanceRepository,
)
from app.db.unit_of_work import AbstractUnitOfWork
from app.dependencies import get_uow


def get_attendance_repo(
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> AbstractAttendanceRepository:
    return SqlAttendanceRepository(uow.session)


def get_checkin_token_repo(
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> AbstractCheckinTokenRepository:
    return SqlCheckinTokenRepository(uow.session)


def get_session_instance_repo(
    uow: Annotated[AbstractUnitOfWork, Depends(get_uow)],
) -> AbstractSessionInstanceRepository:
    return SqlSessionInstanceRepository(uow.session)
