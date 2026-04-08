from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.attendance.dependencies import (
    get_attendance_repo,
    get_checkin_token_repo,
    get_session_instance_repo,
)
from app.attendance.models import AttendanceRead, CheckinTokenRead
from app.attendance.repository import (
    AbstractAttendanceRepository,
    AbstractCheckinTokenRepository,
    AbstractSessionInstanceRepository,
)
from app.auth.guards import REQUIRE_ADMIN, REQUIRE_MEMBER
from app.auth.models import UserClaims
from app.db.unit_of_work import AbstractUnitOfWork
from app.dependencies import get_uow

router = APIRouter(tags=["attendance"])

_AttRepo = Annotated[AbstractAttendanceRepository, Depends(get_attendance_repo)]
_TokRepo = Annotated[
    AbstractCheckinTokenRepository, Depends(get_checkin_token_repo)
]
_SessRepo = Annotated[
    AbstractSessionInstanceRepository, Depends(get_session_instance_repo)
]
_UoW = Annotated[AbstractUnitOfWork, Depends(get_uow)]
_Admin = Annotated[UserClaims, Depends(REQUIRE_ADMIN)]
_Member = Annotated[UserClaims, Depends(REQUIRE_MEMBER)]


@router.post("/sessions/{session_id}/checkin")
async def checkin_to_session(
    session_id: str,
    current_user: _Member,
    session_repo: _SessRepo,
    attendance_repo: _AttRepo,
    uow: _UoW,
) -> AttendanceRead:
    session = await session_repo.get(session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    if session.get("cancelled"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Session is cancelled"
        )
    existing = await attendance_repo.get_by_session_member(session_id, current_user.sub)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Already checked in"
        )
    record = await attendance_repo.check_in(session_id, current_user.sub, "self")
    await uow.commit()
    return AttendanceRead(**record)


@router.get("/sessions/{session_id}/checkin-token")
async def generate_checkin_token(
    session_id: str,
    _claims: _Admin,
    session_repo: _SessRepo,
    token_repo: _TokRepo,
    uow: _UoW,
) -> CheckinTokenRead:
    session = await session_repo.get(session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    expires_at = datetime.now(UTC) + timedelta(hours=24)
    record = await token_repo.create(session_id, expires_at)
    await uow.commit()
    return CheckinTokenRead(**record)


@router.post("/checkin/{token}")
async def checkin_via_token(
    token: str,
    current_user: _Member,
    token_repo: _TokRepo,
    session_repo: _SessRepo,
    attendance_repo: _AttRepo,
    uow: _UoW,
) -> AttendanceRead:
    token_record = await token_repo.get(token)
    if token_record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Token not found"
        )
    expires_at = datetime.fromisoformat(token_record["expires_at"])
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at < datetime.now(UTC):
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Token expired")
    session = await session_repo.get(token_record["session_id"])
    if session is not None and session.get("cancelled"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Session is cancelled"
        )
    existing = await attendance_repo.get_by_session_member(
        token_record["session_id"], current_user.sub
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Already checked in"
        )
    record = await attendance_repo.check_in(
        token_record["session_id"], current_user.sub, "self"
    )
    await uow.commit()
    return AttendanceRead(**record)


@router.get("/sessions/{session_id}/attendance")
async def list_session_attendance(
    session_id: str,
    _claims: _Admin,
    session_repo: _SessRepo,
    attendance_repo: _AttRepo,
) -> list[AttendanceRead]:
    session = await session_repo.get(session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    records = await attendance_repo.list_for_session(session_id)
    return [AttendanceRead(**r) for r in records]
