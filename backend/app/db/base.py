import uuid
from datetime import UTC, date, datetime, time

from sqlalchemy import Date, DateTime, String, Time
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


class UUIDType(TypeDecorator):
    impl = String(36)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(PG_UUID(as_uuid=False))


class IsoDate(TypeDecorator):
    """A `date` column the app reads and writes as 'YYYY-MM-DD' (#433).

    Comparisons bind through here too, so `col >= "2026-10-01"` compares
    dates in SQL.
    """

    impl = Date
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return date.fromisoformat(value) if isinstance(value, str) else value

    def process_result_value(self, value, dialect):
        return value.isoformat() if value is not None else None


class IsoTime(TypeDecorator):
    """A `time` column the app reads and writes as 'HH:MM' (#433)."""

    impl = Time
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return time.fromisoformat(value) if isinstance(value, str) else value

    def process_result_value(self, value, dialect):
        return value.strftime("%H:%M") if value is not None else None


class IsoTimestamp(TypeDecorator):
    """A `timestamptz` column the app reads and writes as ISO-8601 (#433).

    Reads come back in UTC, as the app has always written them.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return datetime.fromisoformat(value) if isinstance(value, str) else value

    def process_result_value(self, value, dialect):
        return value.astimezone(UTC).isoformat() if value is not None else None


class Base(DeclarativeBase):
    pass


class UUIDBase(Base):
    """Abstract base model with a UUID primary key."""

    __abstract__ = True

    id: Mapped[str] = mapped_column(
        UUIDType(),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
