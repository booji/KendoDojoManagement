from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.attendance.dependencies import (
    get_attendance_repo,
    get_session_instance_repo,
)
from app.attendance.models import (
    AddVisitorRequest,
    AttendanceRead,
    MarkAttendedRequest,
    MemberAttendanceRead,
)
from app.attendance.repository import (
    AbstractAttendanceRepository,
    AbstractSessionInstanceRepository,
)
from app.auth.guards import REQUIRE_ADMIN, REQUIRE_MEMBER
from app.auth.models import AccountClaims
from app.db.unit_of_work import AbstractUnitOfWork
from app.dependencies import get_uow
from app.members.dependencies import get_current_member_id
from app.sessions.checkin_window import CheckinWindowStatus, classify_checkin_window
from app.sessions.envelope import envelope_bounds
from app.settings.dependencies import get_dojo_settings_repo
from app.settings.repository import AbstractDojoSettingsRepository

router = APIRouter(tags=["attendance"])

_AttRepo = Annotated[AbstractAttendanceRepository, Depends(get_attendance_repo)]
_SessRepo = Annotated[
    AbstractSessionInstanceRepository, Depends(get_session_instance_repo)
]
_UoW = Annotated[AbstractUnitOfWork, Depends(get_uow)]
_Admin = Annotated[AccountClaims, Depends(REQUIRE_ADMIN)]
_Member = Annotated[AccountClaims, Depends(REQUIRE_MEMBER)]
_CurrentMemberId = Annotated[str | None, Depends(get_current_member_id)]
_SettingsRepo = Annotated[
    AbstractDojoSettingsRepository, Depends(get_dojo_settings_repo)
]


def _require_member_id(member_id: str | None) -> str:
    """Attendance rows are keyed by Member id (#340); a user without a member
    record has no key to write under."""
    if member_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No member record for this user",
        )
    return member_id


def _session_envelope_datetimes(session: dict) -> tuple[datetime, datetime]:
    # end_time may be "24:00" or beyond when a segment runs to/past midnight;
    # envelope_bounds rolls those hours into the next day rather than crashing.
    return envelope_bounds(session["date"], session["start_time"], session["end_time"])


@router.post("/sessions/{session_id}/checkin")
async def checkin_to_session(
    session_id: uuid.UUID,
    current_user: _Member,
    current_member_id: _CurrentMemberId,
    session_repo: _SessRepo,
    attendance_repo: _AttRepo,
    settings_repo: _SettingsRepo,
    uow: _UoW,
) -> AttendanceRead:
    member_id = _require_member_id(current_member_id)
    session = await session_repo.get(str(session_id))
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    if session.get("cancelled"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Session is cancelled"
        )
    existing = await attendance_repo.get_by_session_member(str(session_id), member_id)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Already checked in"
        )
    session_start, session_end = _session_envelope_datetimes(session)
    settings = await settings_repo.get()
    override_before = session.get("checkin_window_before_minutes")
    override_after = session.get("checkin_window_after_minutes")
    effective_before = (
        override_before
        if override_before is not None
        else settings["checkin_window_before_minutes"]
    )
    effective_after = (
        override_after
        if override_after is not None
        else settings["checkin_window_after_minutes"]
    )
    window = classify_checkin_window(
        session_start=session_start,
        session_end=session_end,
        before_minutes=effective_before,
        after_minutes=effective_after,
        now=datetime.now(),
    )
    if window.status == CheckinWindowStatus.TOO_EARLY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "reason": "too_early",
                "opens_at": window.opens_at.isoformat(),
            },
        )
    if window.status == CheckinWindowStatus.CLOSED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "reason": "closed",
                "closes_at": window.closes_at.isoformat(),
            },
        )
    # A concurrent check-in can pass the guard above too; the unique constraint
    # then refuses this insert, and main's IntegrityError handler answers 409.
    record = await attendance_repo.check_in(
        str(session_id), member_id, current_user.sub
    )
    await uow.commit()
    return AttendanceRead(**record)


@router.get("/sessions/{session_id}/attendance")
async def list_session_attendance(
    session_id: uuid.UUID,
    _claims: _Admin,
    session_repo: _SessRepo,
    attendance_repo: _AttRepo,
) -> list[AttendanceRead]:
    session = await session_repo.get(str(session_id))
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    records = await attendance_repo.list_for_session(str(session_id))
    return [AttendanceRead(**r) for r in records]


@router.post("/sessions/{session_id}/attendance", status_code=status.HTTP_201_CREATED)
async def admin_mark_attended(
    session_id: uuid.UUID,
    body: MarkAttendedRequest,
    current_user: _Admin,
    session_repo: _SessRepo,
    attendance_repo: _AttRepo,
    uow: _UoW,
) -> AttendanceRead:
    session = await session_repo.get(str(session_id))
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    record = await attendance_repo.admin_mark_attended(
        str(session_id), str(body.member_id), current_user.sub
    )
    await uow.commit()
    return AttendanceRead(**record)


@router.delete(
    "/sessions/{session_id}/attendance/{member_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def remove_attendance(
    session_id: uuid.UUID,
    member_id: uuid.UUID,
    _claims: _Admin,
    attendance_repo: _AttRepo,
    uow: _UoW,
) -> Response:
    removed = await attendance_repo.remove_attendance(str(session_id), str(member_id))
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Attendance record not found"
        )
    await uow.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/sessions/{session_id}/visitors", status_code=status.HTTP_201_CREATED)
async def add_visitor(
    session_id: uuid.UUID,
    body: AddVisitorRequest,
    current_user: _Admin,
    session_repo: _SessRepo,
    attendance_repo: _AttRepo,
    uow: _UoW,
) -> AttendanceRead:
    session = await session_repo.get(str(session_id))
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    record = await attendance_repo.add_visitor(
        str(session_id), body.visitor_name, current_user.sub
    )
    await uow.commit()
    return AttendanceRead(**record)


@router.get("/members/{member_id}/attendance")
async def get_member_attendance_history(
    member_id: uuid.UUID,
    current_user: _Member,
    current_member_id: _CurrentMemberId,
    attendance_repo: _AttRepo,
) -> list[MemberAttendanceRead]:
    if current_user.role != "admin":
        try:
            own_member_id = (
                str(uuid.UUID(current_member_id))
                if current_member_id is not None
                else None
            )
        except ValueError:
            own_member_id = None
        if own_member_id != str(member_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot access another member's attendance history",
            )
    records = await attendance_repo.list_for_member(str(member_id))
    return [MemberAttendanceRead(**r) for r in records]
