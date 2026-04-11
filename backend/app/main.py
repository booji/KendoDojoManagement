from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI
from sqlalchemy import insert, select

import app.attendance.db_models  # noqa: F401

# Import all models so their tables are registered with Base.metadata
import app.auth.db_models  # noqa: F401
import app.grades.db_models  # noqa: F401
import app.members.db_models  # noqa: F401
import app.sessions.db_models  # noqa: F401
from app.attendance.router import router as attendance_router
from app.auth.router import router as auth_router
from app.db.base import Base
from app.db.engine import engine
from app.grades.router import router as grades_router
from app.members.router import router as members_router
from app.reports.router import router as reports_router
from app.routers.health import router as health_router
from app.sessions.db_models import SessionType
from app.sessions.router import router as sessions_router
from app.users.router import router as users_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with engine.begin() as conn:
        result = await conn.execute(select(SessionType))
        if not result.fetchone():
            await conn.execute(
                insert(SessionType).values(
                    id=str(uuid4()), name="General Training"
                )
            )
    yield


app = FastAPI(title="KendoDojoManagement", lifespan=lifespan)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(sessions_router)
app.include_router(members_router)
app.include_router(users_router)
app.include_router(grades_router)
app.include_router(attendance_router)
app.include_router(reports_router)
