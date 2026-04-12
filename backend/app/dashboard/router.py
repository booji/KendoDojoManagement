from __future__ import annotations

from datetime import date, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.auth.guards import REQUIRE_ADMIN
from app.auth.models import UserClaims
from app.dashboard.dependencies import get_dashboard_repo
from app.dashboard.repository import AbstractDashboardRepository

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_Admin = Annotated[UserClaims, Depends(REQUIRE_ADMIN)]
_DashboardRepo = Annotated[AbstractDashboardRepository, Depends(get_dashboard_repo)]


@router.get("/admin")
async def admin_dashboard(
    claims: _Admin,
    repo: _DashboardRepo,
) -> dict[str, Any]:
    """Admin-only — returns headline stats for the dashboard."""
    today = date.today()
    current_start = today - timedelta(days=30)
    prev_end = current_start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=30)

    active_members = await repo.active_member_count()
    sessions_this_week = await repo.sessions_this_week()
    current_rate = await repo.attendance_rate_for_period(current_start, today)
    prev_rate = await repo.attendance_rate_for_period(prev_start, prev_end)

    if current_rate > prev_rate:
        trend = "positive"
    elif current_rate < prev_rate:
        trend = "negative"
    else:
        trend = "neutral"

    return {
        "active_members": active_members,
        "sessions_this_week": sessions_this_week,
        "attendance_rate": current_rate,
        "attendance_trend": trend,
    }
