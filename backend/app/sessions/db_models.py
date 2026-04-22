from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import UUIDBase


class SessionType(UUIDBase):
    __tablename__ = "session_types"

    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    colour: Mapped[str | None] = mapped_column(String(7), nullable=True, default=None)


class SessionTemplate(UUIDBase):
    __tablename__ = "session_templates"

    session_type_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("session_types.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    start_date: Mapped[str] = mapped_column(String(10), nullable=False)
    start_time: Mapped[str] = mapped_column(String(5), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    recurrence: Mapped[str] = mapped_column(
        String(20), nullable=False, default="weekly"
    )
    day_of_week: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=None
    )
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    recurrence_days: Mapped[str | None] = mapped_column(Text, nullable=True)
    interval_weeks: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    info: Mapped[str | None] = mapped_column(Text, nullable=True)
    coach_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class SessionInstance(UUIDBase):
    __tablename__ = "session_instances"

    session_type_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("session_types.id"), nullable=False
    )
    date: Mapped[str] = mapped_column(String(10), nullable=False)
    start_time: Mapped[str] = mapped_column(String(5), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    template_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("session_templates.id"), nullable=True
    )
    cancelled: Mapped[bool] = mapped_column(nullable=False, default=False)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    info: Mapped[str | None] = mapped_column(Text, nullable=True)
    coach_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    checkin_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
