"""Shared test helpers describing the dojo settings response shape.

The dojo settings payload (GET/PUT /settings/dojo) is asserted by several test
files. Historically each carried its own copy of the default settings dict, so
adding a settings field silently broke unrelated files with a ``KeyError`` — a
new ``background_image_url`` field from the login-branding work (#213) took out
every test in ``test_checkin_window_settings.py`` this way.

Describing the shape once, here, localises that coupling: a new settings field
is added in one obvious place, and any test still asserting the old shape fails
with an explicit mismatch rather than an obscure ``KeyError`` in a file that has
nothing to do with the change. See issue #221.
"""

from __future__ import annotations

from typing import Any

# Canonical default dojo-settings payload — the shape returned by
# GET /settings/dojo when nothing has been saved. Keep this in step with the
# response body assembled in app/settings/router.py.
DEFAULT_DOJO_SETTINGS: dict[str, Any] = {
    "dojo_name": "My Dojo",
    "logo_url": None,
    "primary_colour": "#4F46E5",  # indigo-600
    "checkin_window_before_minutes": 60,
    "checkin_window_after_minutes": 120,
    "background_image_url": None,
    "login_show_background": False,
    "login_show_logo": True,
    "login_show_name": False,
}


def default_dojo_settings(**overrides: Any) -> dict[str, Any]:
    """A fresh copy of the canonical default settings, with optional overrides."""
    payload = dict(DEFAULT_DOJO_SETTINGS)
    payload.update(overrides)
    return payload


class StubDojoSettingsRepo:
    """In-memory stand-in for the dojo settings repository — no real DB.

    Starts from the canonical default payload so it stays in step with the real
    response shape. ``update`` merges partial data exactly as the router expects,
    and both ``get`` and ``update`` hand back copies so callers can't mutate the
    stored state by accident.
    """

    def __init__(self, **overrides: Any) -> None:
        self._settings: dict[str, Any] = default_dojo_settings(**overrides)

    async def get(self) -> dict[str, Any]:
        return dict(self._settings)

    async def update(self, data: dict[str, Any]) -> dict[str, Any]:
        self._settings.update(data)
        return dict(self._settings)
