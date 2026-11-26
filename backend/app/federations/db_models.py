from __future__ import annotations

from sqlalchemy import Boolean, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import UUIDBase


class Federation(UUIDBase):
    __tablename__ = "federations"
    __table_args__ = (
        UniqueConstraint("name", name="uq_federations_name"),
        UniqueConstraint("source", "source_key", name="uq_federations_source_key"),
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    abbreviation: Mapped[str | None] = mapped_column(String(50), nullable=True)
    iso_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    website: Mapped[str | None] = mapped_column(String(512), nullable=True)
    continental_grouping: Mapped[str | None] = mapped_column(String(50), nullable=True)
    type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Set by the bundled-list sync (app.federations.fik_catalogue); null for
    # rows an Admin added.
    source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source_key: Mapped[str | None] = mapped_column(String(20), nullable=True)
