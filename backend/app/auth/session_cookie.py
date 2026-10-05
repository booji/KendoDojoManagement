"""The session cookie's attributes, defined once.

A cookie is identified for overwrite and deletion by ``(name, domain, path)``,
and browsers additionally apply their own rules to ``Secure`` and ``SameSite``.
So a logout that clears the cookie without naming the same attributes login set
it with is relying on Starlette's defaults coinciding with them — true today by
accident, and silently false the moment the login cookie's path or domain
changes. Issuing and clearing both go through here so the two can never drift.
"""

from fastapi import Response

from app import config

COOKIE_NAME = "access_token"

# The theme cookie is the saved preference mirrored somewhere the pre-paint
# script (frontend/public/theme.js) can read it, so a client that has never
# seen this user resolves their theme before first paint instead of flashing
# the wrong one while GET /accounts/me/preferences is in flight (#324). Not
# HttpOnly: JS must read it, and a theme carries no auth value.
THEME_COOKIE_NAME = "theme"
THEME_MAX_AGE = 60 * 60 * 24 * 365

# Shared by set and clear: the attributes that make up the cookie's identity,
# plus the ones a browser checks before honouring an overwrite.
_ATTRS: dict = {
    "path": "/",
    "httponly": True,
    "samesite": "strict",
}

_THEME_ATTRS: dict = {**_ATTRS, "httponly": False}


def set_session_cookie(response: Response, token: str) -> None:
    """Issue the session cookie carrying Auth Session id ``token``.

    Set once, at sign-in, and never re-set mid-session (ADR-0008): ``max_age``
    is the absolute ceiling, and the server enforces the idle window. So a
    cookie can outlive an idle-expired Auth Session; the id it carries is then
    refused, and the SPA routes to /login on the 401.
    """
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        secure=config.COOKIE_SECURE,
        max_age=60 * config.SESSION_MAX_MINUTES,
        **_ATTRS,
    )


def clear_session_cookie(response: Response) -> None:
    """Expire the session and theme cookies, matching how they were issued."""
    response.delete_cookie(
        key=COOKIE_NAME,
        secure=config.COOKIE_SECURE,
        **_ATTRS,
    )
    response.delete_cookie(
        key=THEME_COOKIE_NAME,
        secure=config.COOKIE_SECURE,
        **_THEME_ATTRS,
    )


def set_theme_cookie(response: Response, theme: str) -> None:
    """Mirror the saved theme into the readable cookie the pre-paint script uses."""
    response.set_cookie(
        key=THEME_COOKIE_NAME,
        value=theme,
        secure=config.COOKIE_SECURE,
        max_age=THEME_MAX_AGE,
        **_THEME_ATTRS,
    )
