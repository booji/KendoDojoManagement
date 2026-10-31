"""Shared helpers for Playwright e2e tests.

Authenticated pages are gated by ``RequireProfile`` (frontend/src/App.tsx): any
profile-required route redirects to ``/onboarding`` unless the *acting* user has
a Member record with first_name, surname and dob. E2e tests authenticate as
synthetic users, so without seeding that profile every navigation lands on
``/onboarding`` and every assertion fails identically ("Locator expected to be
visible"). This module centralises the seeding so a test can put its acting user
past the gate in one call. See issue #221.

It also holds UI-driving helpers shared across e2e files, such as
``select_segment_type``.
"""

from __future__ import annotations

import uuid
from typing import Any

import requests
from playwright.sync_api import Locator, Page, expect

from app.auth.models import AccountClaims

BASE_URL = "http://localhost:5173"
API_URL = "http://localhost:8000/api"


def login_as(claims: AccountClaims) -> str:
    """Sign in as ``claims`` and return the session cookie value.

    Session cookies are Auth Session ids with a row behind them (#485), so a
    token can no longer be forged: the test-login endpoint creates the Account
    ``claims`` names, with its Member, and signs it in. An Account that
    already exists for the email is signed in as it is.
    """
    r = requests.post(
        f"{API_URL}/auth/login/test",
        json={"email": claims.email, "role": claims.role, "sub": claims.sub},
    )
    r.raise_for_status()
    return r.cookies["access_token"]


def make_token(
    role: str = "admin", *, sub: str | None = None, email: str | None = None
) -> str:
    """Sign in as a new synthetic user and return the session cookie value."""
    claims = AccountClaims(
        sub=sub or str(uuid.uuid4()),
        email=email or f"{role}-{uuid.uuid4().hex[:6]}@dojo.test",
        role=role,  # type: ignore[arg-type]
    )
    return login_as(claims)


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

    Signing in through the test-login endpoint (``login_as``) already made the
    Account and its Member (#432). The name and the date of birth onboarding
    asks for are filled in through the same endpoint the onboarding page posts
    to.

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

    existing.raise_for_status()

    resp = requests.put(
        f"{API_URL}/accounts/me/member",
        json={"first_name": first_name, "surname": surname, "dob": dob, **extra},
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
    """Sign in, set the cookie, and (by default) put the user past the
    onboarding gate. Returns the token so the caller can drive the API too.

    Pass ``with_profile=False`` for the handful of tests that deliberately
    exercise the no-profile / onboarding path.
    """
    token = make_token(role)
    set_cookie(page, token)
    if with_profile:
        complete_onboarding(token, **profile)
    return token


def select_segment_type(page: Page, segment: Locator, type_name: str) -> None:
    """Tick a session type for ``segment`` via its SessionTypeMultiSelect popover.

    The popover is portalled to ``<body>``, so its checkbox is located at page
    level. Escape closes the popover, which then animates out before it
    unmounts; waiting for the checkbox to go means the next call's page-level
    locator can never also match options in this still-closing popover
    (strict-mode violation, #493).
    """
    segment.get_by_role("button", name="Session types").click()
    # exact match: one type name can be a prefix of another ("Kihon" vs
    # "Kihon-Keiko-Ho"), and accessible-name matching is substring by default.
    option = page.get_by_role("checkbox", name=type_name, exact=True)
    option.click()
    page.keyboard.press("Escape")
    expect(option).to_be_hidden()
