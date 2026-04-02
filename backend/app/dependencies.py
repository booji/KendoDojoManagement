from collections.abc import AsyncGenerator

from app.db.engine import session_factory
from app.db.unit_of_work import AbstractUnitOfWork, SQLAlchemyUnitOfWork


async def get_uow() -> AsyncGenerator[AbstractUnitOfWork]:
    async with SQLAlchemyUnitOfWork(session_factory) as uow:
        yield uow
