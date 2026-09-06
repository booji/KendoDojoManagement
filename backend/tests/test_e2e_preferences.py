"""
E2E tests for issue #26 — User preferences API (theme persistence).

These tests call the live backend API directly via Playwright's request context
(no UI needed — issue #26 is a backend-only feature).
Requires a running backend at BASE_API (http://localhost:8000/api).
"""

import json

import requests
from playwright.sync_api import Playwright

BASE_API = "http://localhost:8000/api"

_EMAIL = "e2e_prefs@dojo.test"


def _get_token(playwright: Playwright) -> str:
    """Create-or-get a test user and return the raw access_token value."""
    resp = requests.post(
        f"{BASE_API}/auth/login/test",
        json={"email": _EMAIL, "role": "admin"},
    )
    assert resp.ok, f"test login failed: {resp.text}"
    token = resp.cookies["access_token"]
    assert token, "access_token cookie not found in test login response"
    return token


# ---------------------------------------------------------------------------
# AC1 — GET /users/me/preferences returns {"theme": "system"} with no saved pref
# ---------------------------------------------------------------------------


def test_preferences_get_returns_system_theme_by_default(
    playwright: Playwright,
) -> None:
    token = _get_token(playwright)
    ctx = playwright.request.new_context(base_url=BASE_API)

    resp = ctx.get(
        f"{BASE_API}/users/me/preferences", headers={"Cookie": f"access_token={token}"}
    )
    assert resp.ok, f"expected 200, got {resp.status}: {resp.text()}"
    assert resp.json()["theme"] == "system"
    ctx.dispose()


# ---------------------------------------------------------------------------
# AC2 — PUT /users/me/preferences with {"theme": "dark"} persists and returns it
# ---------------------------------------------------------------------------


def test_preferences_put_dark_theme_persists_and_is_returned(
    playwright: Playwright,
) -> None:
    token = _get_token(playwright)
    ctx = playwright.request.new_context(base_url=BASE_API)
    auth = {"Cookie": f"access_token={token}"}

    put_resp = ctx.fetch(
        f"{BASE_API}/users/me/preferences",
        method="PUT",
        headers={**auth, "Content-Type": "application/json"},
        data=json.dumps({"theme": "dark"}),
    )
    assert put_resp.ok, f"PUT failed: {put_resp.status} {put_resp.text()}"
    assert put_resp.json()["theme"] == "dark"

    get_resp = ctx.get(f"{BASE_API}/users/me/preferences", headers=auth)
    assert get_resp.json()["theme"] == "dark"
    ctx.dispose()


# ---------------------------------------------------------------------------
# AC3 — PUT /users/me/preferences with invalid theme returns 422
# ---------------------------------------------------------------------------


def test_preferences_put_invalid_theme_returns_422(playwright: Playwright) -> None:
    token = _get_token(playwright)
    ctx = playwright.request.new_context(base_url=BASE_API)
    auth = {"Cookie": f"access_token={token}"}

    resp = ctx.fetch(
        f"{BASE_API}/users/me/preferences",
        method="PUT",
        headers={**auth, "Content-Type": "application/json"},
        data=json.dumps({"theme": "invalid_value"}),
    )
    assert resp.status == 422, f"expected 422, got {resp.status}: {resp.text()}"
    ctx.dispose()


# ---------------------------------------------------------------------------
# AC4 — GET /users/me/preferences returns 401 for unauthenticated requests
# ---------------------------------------------------------------------------


def test_preferences_get_unauthenticated_returns_401(playwright: Playwright) -> None:
    ctx = playwright.request.new_context(base_url=BASE_API)
    resp = ctx.get(f"{BASE_API}/users/me/preferences")
    assert resp.status == 401, f"expected 401, got {resp.status}: {resp.text()}"
    ctx.dispose()


# ---------------------------------------------------------------------------
# AC5 — PUT /users/me/preferences returns 401 for unauthenticated requests
# ---------------------------------------------------------------------------


def test_preferences_put_unauthenticated_returns_401(playwright: Playwright) -> None:
    ctx = playwright.request.new_context(base_url=BASE_API)
    resp = ctx.fetch(
        f"{BASE_API}/users/me/preferences",
        method="PUT",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"theme": "dark"}),
    )
    assert resp.status == 401, f"expected 401, got {resp.status}: {resp.text()}"
    ctx.dispose()
