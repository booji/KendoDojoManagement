"""Signing a test caller in, for route tests that go through the real guard.

The guard resolves the session cookie through ``get_auth_session_repo``
(#485). ``sign_in`` points that dependency at one in-memory fake per test —
installed on first use, reused after — and returns a cookie value the guard
will accept for ``claims``. Each test file's own ``dependency_overrides``
cleanup removes it again.
"""

from __future__ import annotations

from app.auth.dependencies import get_auth_session_repo
from app.auth.models import AccountClaims, AuthSessionKind
from tests.fake_repositories import InMemoryAuthSessionRepository


def sign_in(claims: AccountClaims, *, kind: AuthSessionKind = "sign_in") -> str:
    from app.main import app

    override = app.dependency_overrides.get(get_auth_session_repo)
    if override is None:
        fake = InMemoryAuthSessionRepository()
        override = app.dependency_overrides[get_auth_session_repo] = lambda: fake
    return override().sign_in(claims, kind=kind)
