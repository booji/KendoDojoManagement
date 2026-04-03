from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

from app.auth.router import router as auth_router
from app.config import DATABASE_URL
from app.db.base import Base
from app.db.engine import engine
from app.routers.health import router as health_router

# Import all models so their tables are registered with Base.metadata
import app.auth.db_models  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    if DATABASE_URL.startswith("sqlite"):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(title="KendoDojoManagement", lifespan=lifespan)

app.include_router(health_router)
app.include_router(auth_router)
