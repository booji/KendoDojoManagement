from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import UUIDBase


class DojoSettings(UUIDBase):
    __tablename__ = "dojo_settings"
    # One row per instance, held by the database (#431): a unique index on a
    # constant makes every row collide with every other.
    __table_args__ = (
        Index("uq_dojo_settings_single_row", text("(true)"), unique=True),
    )

    dojo_name: Mapped[str] = mapped_column(
        String(255), nullable=False, default="My Dojo"
    )
    logo_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    primary_colour: Mapped[str] = mapped_column(
        String(7), nullable=False, default="#1a1a2e"
    )
    checkin_window_before_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=60
    )
    checkin_window_after_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=120
    )
    background_image_url: Mapped[str | None] = mapped_column(
        String(1024), nullable=True
    )
    login_show_background: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    login_show_logo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    login_show_name: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
