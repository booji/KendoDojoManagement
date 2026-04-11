from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.attendance.dependencies import (
    get_attendance_repo,
    get_checkin_token_repo,
    get_session_instance_repo,
)
from app.attendance.models import (
    AddVisitorRequest,
    AttendanceRead,
    CheckinTokenRead,
    MarkAttendedRequest,
)
from app.attendance.repository import (
    AbstractAttendanceRepository,
    AbstractCheckinTokenRepository,
    AbstractSessionInstanceRepository,
)
from app.auth.guards import REQUIRE_ADMIN, REQUIRE_MEMBER
from app.auth.models import UserClaims
from app.db.unit_of_work import AbstractUnitOfWork
from app.dependencies import get_uow
from app.members.dependencies import get_member_repo
from app.members.repository import AbstractMemberRepository

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
_MemberRepo = Annotated[AbstractMemberRepository, Depends(get_member_repo)]


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


@router.post("/sessions/{session_id}/attendance", status_code=status.HTTP_201_CREATED)
async def admin_mark_attended(
    session_id: str,
    body: MarkAttendedRequest,
    current_user: _Admin,
    session_repo: _SessRepo,
    attendance_repo: _AttRepo,
    uow: _UoW,
) -> AttendanceRead:
    session = await session_repo.get(session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    record = await attendance_repo.admin_mark_attended(
        session_id, body.member_id, current_user.sub
    )
    await uow.commit()
    return AttendanceRead(**record)


@router.delete(
    "/sessions/{session_id}/attendance/{member_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def remove_attendance(
    session_id: str,
    member_id: str,
    _claims: _Admin,
    attendance_repo: _AttRepo,
    uow: _UoW,
) -> Response:
    removed = await attendance_repo.remove_attendance(session_id, member_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Attendance record not found"
        )
    await uow.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/sessions/{session_id}/visitors", status_code=status.HTTP_201_CREATED)
async def add_visitor(
    session_id: str,
    body: AddVisitorRequest,
    current_user: _Admin,
    session_repo: _SessRepo,
    attendance_repo: _AttRepo,
    uow: _UoW,
) -> AttendanceRead:
    session = await session_repo.get(session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    record = await attendance_repo.add_visitor(
        session_id, body.visitor_name, current_user.sub
    )
    await uow.commit()
    return AttendanceRead(**record)


@router.get("/members/{member_id}/attendance")
async def get_member_attendance_history(
    member_id: str,
    current_user: _Member,
    attendance_repo: _AttRepo,
    member_repo: _MemberRepo,
) -> list[AttendanceRead]:
    if current_user.role != "admin":
        # Resolve the calling user's own member record to compare by member UUID
        # (current_user.sub is a user UUID; member_id is a member record UUID)
        own_member = await member_repo.get_by_user_id(current_user.sub)
        own_member_id = own_member["id"] if own_member is not None else None
        if own_member_id != member_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot access another member's attendance history",
            )
    records = await attendance_repo.list_for_member(member_id)
    return [AttendanceRead(**r) for r in records]
