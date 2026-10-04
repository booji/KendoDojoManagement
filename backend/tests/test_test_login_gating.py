"""
Tests for issue #240 — `/auth/login/test` must not exist in a production build.

The endpoint mints an admin cookie for an arbitrary email with no credential.
Env-gating it at request time (`if not _ALLOW_TEST_AUTH: 404`) leaves the route
registered and one bad env var away from being a full auth bypass. These tests
pin two stronger properties:

  1. The route is not registered at all unless ALLOW_TEST_AUTH is true.
  2. `role` is constrained to the known roles, not an arbitrary string.

Pure/stub tests — no DB.
"""

from __future__ import annotations

import importlib
import sys

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


def _load_auth_router(monkeypatch: pytest.MonkeyPatch, allow: str | None):
    """Import a fresh copy of app.auth.router under a given ALLOW_TEST_AUTH.

    Reloads in place and restores the original module afterwards so the
    already-mounted app keeps working for every other test.
    """
    if allow is None:
        monkeypatch.delenv("ALLOW_TEST_AUTH", raising=False)
    else:
        monkeypatch.setenv("ALLOW_TEST_AUTH", allow)
    return importlib.reload(sys.modules["app.auth.router"])


def _paths(module) -> set[str]:
    return {getattr(r, "path", None) for r in module.router.routes}


class TestRouteIsCompiledOut:
    def test_absent_when_env_var_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        try:
            module = _load_auth_router(monkeypatch, None)
            assert "/auth/login/test" not in _paths(module)
        finally:
            _load_auth_router(monkeypatch, "true")

    def test_absent_when_env_var_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        try:
            module = _load_auth_router(monkeypatch, "false")
            assert "/auth/login/test" not in _paths(module)
        finally:
            _load_auth_router(monkeypatch, "true")

    def test_present_when_explicitly_enabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        try:
            module = _load_auth_router(monkeypatch, "true")
            assert "/auth/login/test" in _paths(module)
        finally:
            _load_auth_router(monkeypatch, "true")


class TestRoleIsValidated:
    @pytest.mark.parametrize("role", ["superuser", "", "admin; DROP TABLE users"])
    async def test_unknown_role_is_rejected(self, role: str) -> None:
        """`role` lands directly on Account.role — it must not be a free string."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test/api"
        ) as c:
            response = await c.post(
                "/auth/login/test",
                json={"email": "nobody@dojo.test", "role": role},
            )

        assert response.status_code == 422
