"""Shared helpers for Playwright e2e tests.

Authenticated pages are gated by ``RequireProfile`` (frontend/src/App.tsx): any
profile-required route redirects to ``/onboarding`` unless the *acting* user has
a Member record with first_name, surname and dob. E2e tests authenticate as
synthetic users, so without seeding that profile every navigation lands on
``/onboarding`` and every assertion fails identically ("Locator expected to be
visible"). This module centralises the seeding so a test can put its acting user
past the gate in one call. See issue #221.
"""

from __future__ import annotations

import uuid
from typing import Any

import requests
from playwright.sync_api import Page

from app.auth.models import AccountClaims
from app.auth.token import decode_token, encode_token

BASE_URL = "http://localhost:5173"
API_URL = "http://localhost:8000/api"


def make_token(
    role: str = "admin", *, sub: str | None = None, email: str | None = None
) -> str:
    """Forge a signed access token for a synthetic user."""
    claims = AccountClaims(
        sub=sub or str(uuid.uuid4()),
        email=email or f"{role}-{uuid.uuid4().hex[:6]}@dojo.test",
        role=role,  # type: ignore[arg-type]
        is_active=True,
    )
    return encode_token(claims)


def set_cookie(page: Page, token: str) -> None:
    """Attach an access-token cookie to the browser context."""
    page.context.add_cookies(
        [
            {
                "name": "access_token",
                "value": token,
                "domain": "localhost",
                "path": "/",
                "httpOnly": True,
                "sameSite": "Strict",
            }
        ]
    )


def complete_onboarding(
    token: str,
    *,
    first_name: str = "Test",
    surname: str = "User",
    dob: str = "1990-01-01",
    **extra: Any,
) -> dict[str, Any]:
    """Ensure the acting user has a complete Member so RequireProfile lets them through.

    Tokens here are forged, so at first no Account stands behind them. Every
    Account belongs to a Member (#432), so the test-login endpoint makes the
    forged subject a real Account with a Member of this name; the date of
    birth onboarding asks for is then filled in through the same endpoint the
    onboarding page posts to.

    Non-clobbering: a profile that is already complete is left untouched and
    returned, so callers can seed the same user repeatedly (e.g. mint-token
    twice) without overwriting a name deliberately set elsewhere.
    """
    existing = requests.get(
        f"{API_URL}/accounts/me/member",
        cookies={"access_token": token},
    )
    if existing.status_code == 200 and existing.json().get("dob"):
        return existing.json()

    if existing.status_code == 404:
        claims = decode_token(token)
        requests.post(
            f"{API_URL}/auth/login/test",
            json={
                "email": claims.email,
                "role": claims.role,
                "sub": claims.sub,
                "first_name": first_name,
                "surname": surname,
            },
        ).raise_for_status()

    resp = requests.put(
        f"{API_URL}/accounts/me/member",
        json={"dob": dob, **extra},
        cookies={"access_token": token},
    )
    resp.raise_for_status()
    return resp.json()


def authenticate(
    page: Page,
    role: str = "admin",
    *,
    with_profile: bool = True,
    **profile: Any,
) -> str:
    """Forge a token, set the cookie, and (by default) put the user past the
    onboarding gate. Returns the token so the caller can drive the API too.

    Pass ``with_profile=False`` for the handful of tests that deliberately
    exercise the no-profile / onboarding path.
    """
    token = make_token(role)
    set_cookie(page, token)
    if with_profile:
        complete_onboarding(token, **profile)
    return token
