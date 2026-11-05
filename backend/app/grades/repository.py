from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.grades.db_models import GradeHistory
from app.members.db_models import Member
from app.members.models import member_name


class AbstractGradeRepository(ABC):
    @abstractmethod
    async def get_current_grades(
        self, member_ids: list[str]
    ) -> dict[str, dict[str, Any]]:
        """Each Member's current Grade, by member id: their latest *confirmed*
        Promotion.

        A pending, self-reported Promotion is nobody's current Grade until an
        Admin confirms it (#565). A Member with no confirmed Promotion (Mukyū)
        is absent from the result.
        """
        ...

    async def get_current_grade(self, member_id: str) -> dict[str, Any] | None:
        """get_current_grades for one Member; None when they are Mukyū."""
        return (await self.get_current_grades([member_id])).get(member_id)

    @abstractmethod
    async def add_promotion(
        self,
        member_id: str,
        grade: str,
        display_name: str,
        assigned_by: str | None,
        promoted_at: str,
        status: str = "confirmed",
    ) -> dict[str, Any]: ...

    @abstractmethod
    async def get_history(self, member_id: str) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def approve_entry(
        self, member_id: str, entry_id: str, approved_by: str
    ) -> dict[str, Any]:
        """Transition a pending entry to confirmed, setting assigned_by.

        Raises KeyError if entry not found.
        Raises ValueError if entry is not pending.
        """
        ...

    @abstractmethod
    async def delete_entry(self, member_id: str, entry_id: str) -> None:
        """Remove a pending entry.

        Raises KeyError if entry not found.
        Raises ValueError if entry is not pending (confirmed entries cannot be deleted).
        """
        ...

    @abstractmethod
    async def list_pending(self) -> list[dict[str, Any]]: ...


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

    async def get_current_grades(
        self, member_ids: list[str]
    ) -> dict[str, dict[str, Any]]:
        # The one place the confirmed-only rule lives (#565).
        if not member_ids:
            return {}
        result = await self._session.execute(
            select(GradeHistory)
            .where(
                GradeHistory.member_id.in_(member_ids),
                GradeHistory.status == "confirmed",
            )
            .order_by(GradeHistory.member_id, GradeHistory.promoted_at.desc())
            .distinct(GradeHistory.member_id)
        )
        return {obj.member_id: _to_dict(obj) for obj in result.scalars().all()}

    async def add_promotion(
        self,
        member_id: str,
        grade: str,
        display_name: str,
        assigned_by: str | None,
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

    async def approve_entry(
        self, member_id: str, entry_id: str, approved_by: str
    ) -> dict[str, Any]:
        result = await self._session.execute(
            select(GradeHistory).where(
                GradeHistory.id == entry_id,
                GradeHistory.member_id == member_id,
            )
        )
        obj = result.scalar_one_or_none()
        if obj is None:
            raise KeyError(f"Entry {entry_id} not found")
        if obj.status != "pending":
            raise ValueError("Entry is not pending")
        obj.status = "confirmed"
        obj.assigned_by = approved_by
        await self._session.flush()
        return _to_dict(obj)

    async def delete_entry(self, member_id: str, entry_id: str) -> None:
        result = await self._session.execute(
            select(GradeHistory).where(
                GradeHistory.id == entry_id,
                GradeHistory.member_id == member_id,
            )
        )
        obj = result.scalar_one_or_none()
        if obj is None:
            raise KeyError(f"Entry {entry_id} not found")
        if obj.status != "pending":
            raise ValueError("Only pending entries may be deleted")
        await self._session.delete(obj)
        await self._session.flush()

    async def list_pending(self) -> list[dict[str, Any]]:
        result = await self._session.execute(
            select(GradeHistory, Member.display_name, Member.first_name, Member.surname)
            .join(Member, GradeHistory.member_id == Member.id)
            .where(GradeHistory.status == "pending")
            .order_by(GradeHistory.promoted_at.asc())
        )
        return [
            {
                **_to_dict(gh),
                "member_name": member_name(display_name, first_name, surname),
            }
            for gh, display_name, first_name, surname in result.all()
        ]
