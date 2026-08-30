from __future__ import annotations

import os
import uuid
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
from app.core.security_logger import log_security_event
from app.db.unit_of_work import AbstractUnitOfWork
from app.dependencies import get_uow
from app.members.dependencies import get_current_member_id
from app.sessions.checkin_window import CheckinWindowStatus, classify_checkin_window
from app.sessions.envelope import envelope_bounds
from app.settings.dependencies import get_dojo_settings_repo
from app.settings.repository import AbstractDojoSettingsRepository

router = APIRouter(tags=["attendance"])

_AttRepo = Annotated[AbstractAttendanceRepository, Depends(get_attendance_repo)]
_TokRepo = Annotated[AbstractCheckinTokenRepository, Depends(get_checkin_token_repo)]
_SessRepo = Annotated[
    AbstractSessionInstanceRepository, Depends(get_session_instance_repo)
]
_UoW = Annotated[AbstractUnitOfWork, Depends(get_uow)]
_Admin = Annotated[UserClaims, Depends(REQUIRE_ADMIN)]
_Member = Annotated[UserClaims, Depends(REQUIRE_MEMBER)]
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
    record = await attendance_repo.check_in(
        str(session_id), member_id, current_user.sub
    )
    await uow.commit()
    return AttendanceRead(**record)


@router.get("/sessions/{session_id}/checkin-token")
async def generate_checkin_token(
    session_id: uuid.UUID,
    _claims: _Admin,
    session_repo: _SessRepo,
    token_repo: _TokRepo,
    uow: _UoW,
) -> CheckinTokenRead:
    session = await session_repo.get(str(session_id))
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    expires_at = datetime.now(UTC) + timedelta(hours=24)
    record = await token_repo.create(str(session_id), expires_at)
    origin = os.getenv("PUBLIC_ORIGIN") or os.getenv(
        "WEBAUTHN_ORIGIN", "http://localhost:5173"
    )
    checkin_url = f"{origin.rstrip('/')}/checkin/{record['token']}"
    await session_repo.update(str(session_id), {"checkin_url": checkin_url})
    await uow.commit()
    log_security_event(
        "checkin_token_generated",
        "success",
        detail={"session_id": str(session_id)},
    )
    if isinstance(record.get("expires_at"), datetime):
        record = {**record, "expires_at": record["expires_at"].isoformat()}
    return CheckinTokenRead(**record)


@router.post("/checkin/{token}")
async def checkin_via_token(
    token: str,
    current_user: _Member,
    current_member_id: _CurrentMemberId,
    token_repo: _TokRepo,
    session_repo: _SessRepo,
    attendance_repo: _AttRepo,
    uow: _UoW,
) -> AttendanceRead:
    member_id = _require_member_id(current_member_id)
    try:
        token_record = await token_repo.redeem(token)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Token already used"
        )
    if token_record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Invalid token"
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
        token_record["session_id"], member_id
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Already checked in"
        )
    record = await attendance_repo.check_in(
        token_record["session_id"], member_id, current_user.sub
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
) -> list[AttendanceRead]:
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
    return [AttendanceRead(**r) for r in records]
