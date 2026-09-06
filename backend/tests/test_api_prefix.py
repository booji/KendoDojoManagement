"""
Every API route is served under `/api`, and the built SPA is served from the
same origin (ADR-0001).

Before this, routers were mounted at the root and Vite's dev proxy rewrote
`/api` away, so the prefixed URLs the frontend actually calls existed only in
development — both production stacks answered 404 for every one of them.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.routing import Mount

from app.main import app, mount_spa

# Paths that deliberately stay at the root: the container healthcheck target
# and FastAPI's own docs. Everything else belongs behind /api.
ROOT_ALLOWED = {"/health", "/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}


def test_every_api_route_is_under_the_api_prefix() -> None:
    unprefixed = [
        path
        for path in app.openapi()["paths"]
        if not path.startswith("/api/") and path not in ROOT_ALLOWED
    ]
    assert unprefixed == [], f"routes outside /api: {unprefixed}"


def test_static_upload_mounts_stay_at_the_root() -> None:
    mounts = {route.path for route in app.routes if isinstance(route, Mount)}
    assert {"/static/logos", "/static/backgrounds"} <= mounts


@pytest.mark.asyncio
async def test_health_is_still_served_at_the_root() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get("/health")).status_code == 200


@pytest.mark.asyncio
async def test_spa_is_served_when_a_build_is_present(tmp_path) -> None:
    (tmp_path / "index.html").write_text("<!doctype html><title>kendo</title>")
    spa_app = FastAPI()
    mount_spa(spa_app, str(tmp_path))

    async with AsyncClient(
        transport=ASGITransport(app=spa_app), base_url="http://test"
    ) as client:
        # A client-side route, not a file on disk: html=True falls back to
        # index.html so a deep link survives a page refresh.
        response = await client.get("/members/some-uuid")

    assert response.status_code == 200
    assert "kendo" in response.text


def test_no_spa_mount_without_a_build(tmp_path) -> None:
    """The dev image runs from source and has no `static/index.html`."""
    spa_app = FastAPI()
    mount_spa(spa_app, str(tmp_path))
    assert [r for r in spa_app.routes if isinstance(r, Mount)] == []
