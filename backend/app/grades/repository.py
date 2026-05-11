from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.grades.db_models import GradeHistory


class AbstractGradeRepository(ABC):
    @abstractmethod
    async def get_current_grade(self, member_id: str) -> str | None: ...

    @abstractmethod
    async def add_promotion(
        self,
        member_id: str,
        grade: str,
        display_name: str,
        assigned_by: str,
        promoted_at: str,
        status: str = "confirmed",
    ) -> dict[str, Any]: ...

    @abstractmethod
    async def get_history(self, member_id: str) -> list[dict[str, Any]]: ...


def _to_dict(obj: GradeHistory) -> dict[str, Any]:
    return {
        "id": obj.id,
        "member_id": obj.member_id,
        "grade": obj.grade,
        "display_name": obj.display_name,
        "promoted_at": obj.promoted_at,
        "assigned_by": obj.assigned_by,
        "status": obj.status,
    }


class SqlGradeRepository(AbstractGradeRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_current_grade(self, member_id: str) -> str | None:
        result = await self._session.execute(
            select(GradeHistory)
            .where(GradeHistory.member_id == member_id)
            .order_by(GradeHistory.promoted_at.desc())
            .limit(1)
        )
        obj = result.scalar_one_or_none()
        return obj.grade if obj else None

    async def add_promotion(
        self,
        member_id: str,
        grade: str,
        display_name: str,
        assigned_by: str,
        promoted_at: str,
        status: str = "confirmed",
    ) -> dict[str, Any]:
        obj = GradeHistory(
            id=str(uuid4()),
            member_id=member_id,
            grade=grade,
            display_name=display_name,
            assigned_by=assigned_by,
            promoted_at=promoted_at,
            status=status,
        )
        self._session.add(obj)
        await self._session.flush()
        return _to_dict(obj)

    async def get_history(self, member_id: str) -> list[dict[str, Any]]:
        result = await self._session.execute(
            select(GradeHistory)
            .where(GradeHistory.member_id == member_id)
            .order_by(GradeHistory.promoted_at.asc())
        )
        return [_to_dict(obj) for obj in result.scalars().all()]
