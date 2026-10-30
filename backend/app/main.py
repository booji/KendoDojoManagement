import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession
from starlette.exceptions import HTTPException
from starlette.requests import Request as StarletteRequest
from starlette.responses import JSONResponse, Response
from starlette.types import Scope

import app.attendance.db_models  # noqa: F401

# Import all models so their tables are registered with Base.metadata
import app.auth.db_models  # noqa: F401
import app.federations.db_models  # noqa: F401
import app.grades.db_models  # noqa: F401
import app.member_federations.db_models  # noqa: F401
import app.members.db_models  # noqa: F401
import app.sessions.db_models  # noqa: F401
import app.settings.models  # noqa: F401
from app.accounts.router import router as accounts_router
from app.attendance.router import router as attendance_router
from app.auth.attempt_repository import SqlAttemptRepository
from app.auth.rate_limiter import limiter
from app.auth.router import router as auth_router
from app.config import API_PREFIX, CORS_ORIGINS, validate_startup_config
from app.core.middleware import (
    ClientIPMiddleware,
    ConstantTimeAuthMiddleware,
    SecurityHeadersMiddleware,
)
from app.db.engine import engine
from app.federations.router import router as federations_router
from app.grades.router import router as grades_router
from app.member_federations.router import router as member_federations_router
from app.members.router import router as members_router
from app.reports.router import router as reports_router
from app.routers.health import router as health_router
from app.routers.setup import router as setup_router
from app.sessions.router import router as sessions_router
from app.sessions.seed import seed_session_types
from app.settings.router import router as settings_router

_log = logging.getLogger(__name__)


# Constraint name -> the 409 detail a client gets when the database refuses a
# write (#431). Application guards (e.g. check-in's "already checked in"
# lookup) are check-then-insert; the constraint is what decides a race. Any
# other integrity error is a bug and stays a 500.
_CONSTRAINT_CONFLICTS = {
    "uq_attendance_session_member": "Already checked in",
    "uq_member_federations_member_federation": (
        "This member already belongs to that federation"
    ),
    "uq_federations_name": "A federation with that name already exists",
}


async def _constraint_conflict_handler(
    request: StarletteRequest, exc: IntegrityError
) -> JSONResponse:
    message = str(exc.orig)
    for constraint, detail in _CONSTRAINT_CONFLICTS.items():
        if constraint in message:
            return JSONResponse({"detail": detail}, status_code=409)
    raise exc


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


async def _refuse_superuser(conn: AsyncConnection) -> None:
    """Refuse to serve over a superuser connection (ADR-0007, #453).

    The app needs row reads and writes only. A superuser connection would hand
    a compromised app `COPY ... TO PROGRAM`, the server's files, the schema and
    user creation, so pointing DATABASE_URL back at the superuser to dodge a
    missing grant must fail loudly instead.
    """
    is_superuser = await conn.execute(text("SELECT current_setting('is_superuser')"))
    if is_superuser.scalar() == "on":
        raise RuntimeError(
            "DATABASE_URL logs in as a database superuser. It must name the "
            "restricted app user the migration step provisions; the superuser "
            "belongs in MIGRATION_DATABASE_URL, given to the migration step "
            "only (ADR-0007)."
        )


async def _init_db() -> None:
    """Refuse a superuser connection, seed default session types, and clear
    expired recovery-attempt IPs (#467; kendo-ip-retention.timer repeats that
    daily under Quadlet). Does NOT migrate.

    `alembic upgrade head` runs in its own unit before this process starts —
    the `migrate` service in docker-compose.yml, kendo-migrate.service under
    Quadlet, and `python -m app.db.bootstrap` in run_tests.sh — so that a
    failed migration fails as itself rather than as an app that crashed, and
    two app instances could never race each other up the chain (#391). This
    therefore assumes the schema is already at head.
    """
    async with engine.begin() as conn:
        await _refuse_superuser(conn)
        await seed_session_types(conn)
    async with AsyncSession(engine) as session, session.begin():
        await SqlAttemptRepository(session).clear_expired_ip_addresses()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    validate_startup_config()
    await _init_db()
    yield


app = FastAPI(title="KendoDojoManagement", lifespan=lifespan)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_exception_handler(IntegrityError, _constraint_conflict_handler)
app.add_middleware(ClientIPMiddleware)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
# Added after SlowAPI so it sits *outside* it: the constant-time floor must
# cover rate-limit rejections and unit-of-work teardown too, not just the
# handler body, or the passkey begin endpoints leak which emails are
# registered through response latency.
app.add_middleware(ConstantTimeAuthMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Root, not /api: the container healthcheck and Traefik both hit /health, and
# it is not part of the SPA's API surface.
app.include_router(health_router)
app.include_router(setup_router, prefix=API_PREFIX)
app.include_router(auth_router, prefix=API_PREFIX)
app.include_router(sessions_router, prefix=API_PREFIX)
app.include_router(members_router, prefix=API_PREFIX)
app.include_router(member_federations_router, prefix=API_PREFIX)
app.include_router(accounts_router, prefix=API_PREFIX)
app.include_router(grades_router, prefix=API_PREFIX)
app.include_router(attendance_router, prefix=API_PREFIX)
app.include_router(reports_router, prefix=API_PREFIX)
app.include_router(settings_router, prefix=API_PREFIX)
app.include_router(federations_router, prefix=API_PREFIX)

_STATIC_DIR = os.environ.get("STATIC_DIR", "/tmp/static/logos")
os.makedirs(_STATIC_DIR, exist_ok=True)
app.mount("/static/logos", StaticFiles(directory=_STATIC_DIR), name="logos")

_STATIC_BACKGROUNDS_DIR = os.environ.get(
    "STATIC_BACKGROUNDS_DIR",
    os.path.join(os.path.dirname(_STATIC_DIR.rstrip("/")), "backgrounds"),
)
os.makedirs(_STATIC_BACKGROUNDS_DIR, exist_ok=True)
app.mount(
    "/static/backgrounds",
    StaticFiles(directory=_STATIC_BACKGROUNDS_DIR),
    name="backgrounds",
)


class _SpaFiles(StaticFiles):
    """StaticFiles that serves index.html for unknown paths.

    Starlette's `html=True` only serves index.html for a *directory*; an unknown
    path still 404s. The SPA routes client-side, so `/members/<uuid>` must
    return the shell rather than a 404 when someone refreshes or deep-links.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            return await super().get_response("index.html", scope)


def mount_spa(target: FastAPI, directory: str) -> None:
    """Serve the built SPA at the root, if this image has one.

    The production image copies `frontend/dist` to `static/`; the dev image runs
    from source with Vite serving the frontend, so the directory is absent and
    there is nothing to mount.

    Mounted last: a mount at "/" matches everything left, so it must be
    registered after the /api routers and the /static upload mounts.
    """
    if not os.path.isfile(os.path.join(directory, "index.html")):
        return
    target.mount("/", _SpaFiles(directory=directory, html=True), name="spa")


mount_spa(app, os.environ.get("SPA_DIR", "static"))
