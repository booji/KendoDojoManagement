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

# Shared by set and clear: the attributes that make up the cookie's identity,
# plus the ones a browser checks before honouring an overwrite.
_ATTRS: dict = {
    "path": "/",
    "httponly": True,
    "samesite": "strict",
}


def set_session_cookie(response: Response, token: str) -> None:
    """Issue the session cookie carrying ``token``."""
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        secure=config.COOKIE_SECURE,
        max_age=60 * int(config.JWT_EXPIRE_MINUTES),
        **_ATTRS,
    )


def clear_session_cookie(response: Response) -> None:
    """Expire the session cookie, matching how ``set_session_cookie`` issued it."""
    response.delete_cookie(
        key=COOKIE_NAME,
        secure=config.COOKIE_SECURE,
        **_ATTRS,
    )
