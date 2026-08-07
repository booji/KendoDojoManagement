import uuid

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


class UUIDType(TypeDecorator):
    impl = String(36)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(PG_UUID(as_uuid=False))


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
