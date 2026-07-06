from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import UUIDBase, UUIDType


class SessionType(UUIDBase):
    __tablename__ = "session_types"

    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    colour: Mapped[str | None] = mapped_column(String(7), nullable=True, default=None)


class SessionTemplate(UUIDBase):
    __tablename__ = "session_templates"

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    start_date: Mapped[str] = mapped_column(String(10), nullable=False)
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

    segments: Mapped[list["SessionTemplateSegment"]] = relationship(
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="SessionTemplateSegment.position",
    )


class SessionTemplateSegment(UUIDBase):
    __tablename__ = "session_template_segments"

    template_id: Mapped[str] = mapped_column(
        UUIDType(),
        ForeignKey("session_templates.id", ondelete="CASCADE"),
        nullable=False,
    )
    start_time: Mapped[str] = mapped_column(String(5), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(100), nullable=True)
    note: Mapped[str | None] = mapped_column(String(280), nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    template: Mapped[SessionTemplate] = relationship(back_populates="segments")
    type_links: Mapped[list["SessionTemplateSegmentType"]] = relationship(
        back_populates="segment",
        cascade="all, delete-orphan",
        order_by="SessionTemplateSegmentType.position",
    )


class SessionTemplateSegmentType(UUIDBase):
    __tablename__ = "session_template_segment_types"

    segment_id: Mapped[str] = mapped_column(
        UUIDType(),
        ForeignKey("session_template_segments.id", ondelete="CASCADE"),
        nullable=False,
    )
    session_type_id: Mapped[str] = mapped_column(
        UUIDType(), ForeignKey("session_types.id"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    segment: Mapped[SessionTemplateSegment] = relationship(back_populates="type_links")


class SessionInstance(UUIDBase):
    __tablename__ = "session_instances"

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    date: Mapped[str] = mapped_column(String(10), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    template_id: Mapped[str | None] = mapped_column(
        UUIDType(), ForeignKey("session_templates.id"), nullable=True
    )
    cancelled: Mapped[bool] = mapped_column(nullable=False, default=False)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    info: Mapped[str | None] = mapped_column(Text, nullable=True)
    coach_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    checkin_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    segments: Mapped[list["SessionInstanceSegment"]] = relationship(
        back_populates="instance",
        cascade="all, delete-orphan",
        order_by="SessionInstanceSegment.position",
    )


class SessionInstanceSegment(UUIDBase):
    __tablename__ = "session_instance_segments"

    instance_id: Mapped[str] = mapped_column(
        UUIDType(),
        ForeignKey("session_instances.id", ondelete="CASCADE"),
        nullable=False,
    )
    start_time: Mapped[str] = mapped_column(String(5), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(100), nullable=True)
    note: Mapped[str | None] = mapped_column(String(280), nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    instance: Mapped[SessionInstance] = relationship(back_populates="segments")
    type_links: Mapped[list["SessionInstanceSegmentType"]] = relationship(
        back_populates="segment",
        cascade="all, delete-orphan",
        order_by="SessionInstanceSegmentType.position",
    )


class SessionInstanceSegmentType(UUIDBase):
    __tablename__ = "session_instance_segment_types"

    segment_id: Mapped[str] = mapped_column(
        UUIDType(),
        ForeignKey("session_instance_segments.id", ondelete="CASCADE"),
        nullable=False,
    )
    session_type_id: Mapped[str] = mapped_column(
        UUIDType(), ForeignKey("session_types.id"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    segment: Mapped[SessionInstanceSegment] = relationship(back_populates="type_links")
