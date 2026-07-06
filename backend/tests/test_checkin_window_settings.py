"""
Unit tests for issue #192 AC2/AC3 — DojoSettings check-in window default
minute columns.

Scope: DOJO-WIDE DEFAULTS ONLY (checkin_window_before_minutes /
checkin_window_after_minutes). Per-session overrides are a separate, later
slice and are out of scope here.

Uses StubRepository pattern — NO real DB — mirroring test_settings.py.

Acceptance criteria exercised here:
  2. Two new DojoSettings columns default to 60 (before) and 120 (after).
  3. Both are readable via GET /settings/dojo and updatable via
     PUT /settings/dojo; validation rejects negative values and values
     greater than 1440.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.guards import REQUIRE_ADMIN, REQUIRE_MEMBER
from app.auth.models import UserClaims
from app.main import app

_ADMIN = UserClaims(
    sub="admin-uuid", email="admin@dojo.test", role="admin", is_active=True
)


def _admin_override():
    return _ADMIN


class StubDojoSettingsRepo:
    """In-memory stand-in for a dojo settings repository, carrying the new
    check-in window default minute columns."""

    _DEFAULT_COLOUR = "#4F46E5"
    _DEFAULT_BEFORE_MINUTES = 60
    _DEFAULT_AFTER_MINUTES = 120

    def __init__(self) -> None:
        self._settings: dict[str, Any] | None = None

    async def get(self) -> dict[str, Any]:
        if self._settings is None:
            return {
                "dojo_name": "My Dojo",
                "logo_url": None,
                "primary_colour": self._DEFAULT_COLOUR,
                "checkin_window_before_minutes": self._DEFAULT_BEFORE_MINUTES,
                "checkin_window_after_minutes": self._DEFAULT_AFTER_MINUTES,
            }
        return dict(self._settings)

    async def update(self, data: dict[str, Any]) -> dict[str, Any]:
        current = await self.get()
        current.update(data)
        self._settings = current
        return dict(self._settings)


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def settings_repo() -> StubDojoSettingsRepo:
    from app.settings.dependencies import get_dojo_settings_repo  # noqa: PLC0415

    repo = StubDojoSettingsRepo()
    app.dependency_overrides[get_dojo_settings_repo] = lambda: repo
    return repo


# ---------------------------------------------------------------------------
# AC2 — defaults of 60 / 120
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_dojo_settings_returns_checkin_window_defaults(
    settings_repo: StubDojoSettingsRepo,
) -> None:
    """GET /settings/dojo includes the new fields, defaulting to 60/120."""
    app.dependency_overrides[REQUIRE_MEMBER] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/settings/dojo")

    assert response.status_code == 200
    body = response.json()
    assert body["checkin_window_before_minutes"] == 60
    assert body["checkin_window_after_minutes"] == 120


# ---------------------------------------------------------------------------
# AC3 — updatable via PUT /settings/dojo
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_put_dojo_settings_updates_checkin_window_minutes(
    settings_repo: StubDojoSettingsRepo,
) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.put(
            "/settings/dojo",
            json={
                "checkin_window_before_minutes": 30,
                "checkin_window_after_minutes": 90,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["checkin_window_before_minutes"] == 30
    assert body["checkin_window_after_minutes"] == 90


@pytest.mark.anyio
async def test_put_dojo_settings_checkin_window_visible_on_get(
    settings_repo: StubDojoSettingsRepo,
) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override
    app.dependency_overrides[REQUIRE_MEMBER] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        await c.put(
            "/settings/dojo",
            json={
                "checkin_window_before_minutes": 15,
                "checkin_window_after_minutes": 45,
            },
        )
        get_resp = await c.get("/settings/dojo")

    assert get_resp.status_code == 200
    assert get_resp.json()["checkin_window_before_minutes"] == 15
    assert get_resp.json()["checkin_window_after_minutes"] == 45


# ---------------------------------------------------------------------------
# AC3 — validation: non-negative integer <= 1440
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_put_dojo_settings_rejects_negative_before_minutes(
    settings_repo: StubDojoSettingsRepo,
) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.put(
            "/settings/dojo",
            json={"checkin_window_before_minutes": -1},
        )

    assert response.status_code == 422


@pytest.mark.anyio
async def test_put_dojo_settings_rejects_negative_after_minutes(
    settings_repo: StubDojoSettingsRepo,
) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.put(
            "/settings/dojo",
            json={"checkin_window_after_minutes": -5},
        )

    assert response.status_code == 422


@pytest.mark.anyio
async def test_put_dojo_settings_rejects_before_minutes_over_1440(
    settings_repo: StubDojoSettingsRepo,
) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.put(
            "/settings/dojo",
            json={"checkin_window_before_minutes": 1441},
        )

    assert response.status_code == 422


@pytest.mark.anyio
async def test_put_dojo_settings_rejects_after_minutes_over_1440(
    settings_repo: StubDojoSettingsRepo,
) -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.put(
            "/settings/dojo",
            json={"checkin_window_after_minutes": 1441},
        )

    assert response.status_code == 422


@pytest.mark.anyio
async def test_put_dojo_settings_accepts_boundary_value_1440(
    settings_repo: StubDojoSettingsRepo,
) -> None:
    """1440 (a full day) is the inclusive upper bound and must be accepted."""
    app.dependency_overrides[REQUIRE_ADMIN] = _admin_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.put(
            "/settings/dojo",
            json={"checkin_window_before_minutes": 1440},
        )

    assert response.status_code == 200
    assert response.json()["checkin_window_before_minutes"] == 1440
