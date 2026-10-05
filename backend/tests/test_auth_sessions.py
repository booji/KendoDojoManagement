"""Auth Session lifetime (#455, ADR-0008): idle expiry, the absolute ceiling,
and when ``expires_at`` slides.

Idle is ``JWT_EXPIRE_MINUTES``, the ceiling ``SESSION_MAX_MINUTES``. A session
in continuous use never hits the idle cliff, and the ceiling keeps "no cliff"
from meaning "no sign-in, ever".
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app import config
from app.auth.auth_sessions import (
    hash_token,
    resolve_auth_session,
    slid_expiry,
    start_auth_session,
)
from app.auth.models import AccountClaims
from tests.fake_repositories import InMemoryAuthSessionRepository

_MEMBER = AccountClaims(
    sub="member-uuid", email="member@dojo.test", role="member", is_active=True
)
_T0 = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _lifetime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "JWT_EXPIRE_MINUTES", 60)
    monkeypatch.setattr(config, "SESSION_MAX_MINUTES", 180)


def _minutes(n: float) -> timedelta:
    return timedelta(minutes=n)


def test_no_slide_in_the_first_half_of_the_idle_window() -> None:
    assert slid_expiry(_T0, _T0 + _minutes(60), _T0 + _minutes(29)) is None


def test_slides_a_full_idle_window_past_the_halfway_mark() -> None:
    now = _T0 + _minutes(31)
    assert slid_expiry(_T0, _T0 + _minutes(60), now) == now + _minutes(60)


def test_slide_is_clamped_to_the_absolute_ceiling() -> None:
    now = _T0 + _minutes(150)
    assert slid_expiry(_T0, _T0 + _minutes(170), now) == _T0 + _minutes(180)


def test_no_slide_once_at_the_ceiling() -> None:
    assert slid_expiry(_T0, _T0 + _minutes(180), _T0 + _minutes(170)) is None


async def test_idle_past_the_window_is_no_auth_session() -> None:
    repo = InMemoryAuthSessionRepository()
    token = repo.sign_in(_MEMBER, now=datetime.now(UTC) - _minutes(61))

    assert await resolve_auth_session(repo, token) is None


async def test_active_past_the_ceiling_is_no_auth_session() -> None:
    """Slid right up to the ceiling, and the ceiling has now passed."""
    repo = InMemoryAuthSessionRepository()
    token = repo.sign_in(_MEMBER, now=datetime.now(UTC) - _minutes(181))
    await repo.slide(hash_token(token), datetime.now(UTC) - _minutes(1))

    assert await resolve_auth_session(repo, token) is None


async def test_a_live_auth_session_resolves_to_its_account() -> None:
    repo = InMemoryAuthSessionRepository()
    token = repo.sign_in(_MEMBER)

    assert await resolve_auth_session(repo, token) == _MEMBER


async def test_a_request_in_the_first_half_writes_nothing() -> None:
    repo = InMemoryAuthSessionRepository()
    token = repo.sign_in(_MEMBER)
    before = (await repo.find(hash_token(token)))["expires_at"]

    await resolve_auth_session(repo, token)

    assert (await repo.find(hash_token(token)))["expires_at"] == before


async def test_a_request_past_halfway_slides_the_expiry() -> None:
    repo = InMemoryAuthSessionRepository()
    token = repo.sign_in(_MEMBER, now=datetime.now(UTC) - _minutes(40))
    before = (await repo.find(hash_token(token)))["expires_at"]

    await resolve_auth_session(repo, token)

    assert (await repo.find(hash_token(token)))["expires_at"] > before


async def test_starting_an_auth_session_sweeps_expired_rows() -> None:
    repo = InMemoryAuthSessionRepository()
    stale = repo.sign_in(_MEMBER, now=datetime.now(UTC) - _minutes(61))

    await start_auth_session(repo, _MEMBER.sub)

    assert await repo.find(hash_token(stale)) is None


async def test_the_row_stores_a_hash_not_the_cookie_value() -> None:
    repo = InMemoryAuthSessionRepository()
    token = await start_auth_session(repo, _MEMBER.sub)
    repo.seed_account(_MEMBER)

    assert await repo.find(token) is None
    assert await repo.find(hash_token(token)) is not None
