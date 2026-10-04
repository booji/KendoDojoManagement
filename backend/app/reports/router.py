from __future__ import annotations

import csv
import io
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.auth.guards import REQUIRE_ADMIN
from app.auth.models import AccountClaims
from app.reports.dependencies import get_report_repo
from app.reports.repository import AbstractReportRepository

router = APIRouter(prefix="/reports", tags=["reports"])

_Admin = Annotated[AccountClaims, Depends(REQUIRE_ADMIN)]
_ReportRepo = Annotated[AbstractReportRepository, Depends(get_report_repo)]

_MAX_RANGE_DAYS = 366


def _validate_date_range(date_from: date, date_to: date) -> None:
    if date_to < date_from:
        raise HTTPException(status_code=422, detail="date_to must be >= date_from")
    if (date_to - date_from).days > _MAX_RANGE_DAYS:
        raise HTTPException(
            status_code=422,
            detail=f"Date range must not exceed {_MAX_RANGE_DAYS} days",
        )


_CSV_INJECTION_CHARS = frozenset("=+-@\t\r")


def _safe_csv(value: Any) -> Any:
    if isinstance(value, str) and value and value[0] in _CSV_INJECTION_CHARS:
        return "'" + value
    return value


def _sanitize_row(row: dict[str, Any]) -> dict[str, Any]:
    return {k: _safe_csv(v) for k, v in row.items()}


@router.get("/attendance")
async def attendance_report(
    date_from: date,
    date_to: date,
    claims: _Admin,
    repo: _ReportRepo,
) -> dict[str, Any]:
    _validate_date_range(date_from, date_to)
    sessions = await repo.attendance_report(date_from.isoformat(), date_to.isoformat())
    member_rates = await repo.member_attendance_rates(
        date_from.isoformat(), date_to.isoformat()
    )
    return {"sessions": sessions, "member_rates": member_rates}


@router.get("/members")
async def members_report(
    claims: _Admin,
    repo: _ReportRepo,
) -> list[dict[str, Any]]:
    return await repo.members_report()


@router.get("/attendance/csv")
async def attendance_csv(
    date_from: date,
    date_to: date,
    claims: _Admin,
    repo: _ReportRepo,
) -> StreamingResponse:
    _validate_date_range(date_from, date_to)
    sessions = await repo.attendance_report(date_from.isoformat(), date_to.isoformat())
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["session_id", "date", "headcount"])
    writer.writeheader()
    writer.writerows(_sanitize_row(r) for r in sessions)
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=attendance.csv"},
    )


@router.get("/members/csv")
async def members_csv(
    claims: _Admin,
    repo: _ReportRepo,
) -> StreamingResponse:
    members = await repo.members_report()
    output = io.StringIO()
    writer = csv.DictWriter(
        output, fieldnames=["member_id", "display_name", "join_date", "current_grade"]
    )
    writer.writeheader()
    writer.writerows(_sanitize_row(r) for r in members)
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=members.csv"},
    )
