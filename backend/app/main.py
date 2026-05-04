import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import insert, select
from starlette.requests import Request as StarletteRequest
from starlette.responses import JSONResponse

import app.attendance.db_models  # noqa: F401

# Import all models so their tables are registered with Base.metadata
import app.auth.db_models  # noqa: F401
import app.federations.db_models  # noqa: F401
import app.grades.db_models  # noqa: F401
import app.member_federations.db_models  # noqa: F401
import app.members.db_models  # noqa: F401
import app.sessions.db_models  # noqa: F401
import app.settings.models  # noqa: F401
from app.attendance.router import router as attendance_router
from app.auth.rate_limiter import limiter
from app.auth.router import router as auth_router
from app.config import CORS_ORIGINS
from app.core.middleware import SecurityHeadersMiddleware
from app.dashboard.router import router as dashboard_router
from app.db.base import Base
from app.db.engine import engine
from app.federations.router import router as federations_router
from app.grades.router import router as grades_router
from app.member_federations.router import router as member_federations_router
from app.members.router import router as members_router
from app.reports.router import router as reports_router
from app.routers.health import router as health_router
from app.routers.setup import router as setup_router
from app.sessions.db_models import SessionType
from app.sessions.router import router as sessions_router
from app.settings.router import router as settings_router
from app.users.router import router as users_router


def _rate_limit_exceeded_handler(
    request: StarletteRequest, exc: RateLimitExceeded
) -> JSONResponse:
    """Return 429 with Retry-After header when a rate limit is exceeded."""
    response = JSONResponse(
        {"detail": f"Rate limit exceeded: {exc.detail}"},
        status_code=429,
    )
    response.headers["Retry-After"] = "60"
    return response


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with engine.begin() as conn:
        result = await conn.execute(select(SessionType))
        if not result.fetchone():
            await conn.execute(
                insert(SessionType).values(id=str(uuid4()), name="General Training")
            )
    yield


app = FastAPI(title="KendoDojoManagement", lifespan=lifespan)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(setup_router)
app.include_router(auth_router)
app.include_router(sessions_router)
app.include_router(members_router)
app.include_router(member_federations_router)
app.include_router(users_router)
app.include_router(grades_router)
app.include_router(attendance_router)
app.include_router(reports_router)
app.include_router(settings_router)
app.include_router(dashboard_router)
app.include_router(federations_router)

_STATIC_DIR = os.environ.get("STATIC_DIR", "/tmp/static/logos")
os.makedirs(_STATIC_DIR, exist_ok=True)
app.mount("/static/logos", StaticFiles(directory=_STATIC_DIR), name="logos")
