"""Sliding session renewal (#387).

An access token past half its life is re-issued on the next authenticated
request, so a session in continuous use never hits the expiry cliff. The
re-issue carries the *original* session start (``sst``) forward, so the slide
cannot run past ``SESSION_MAX_MINUTES`` — that is the hard ceiling that keeps
"no cliff" from meaning "no idle timeout, ever".
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta

import pytest
from fastapi import FastAPI, HTTPException, Request
from httpx import ASGITransport, AsyncClient
from starlette.responses import Response

from app import config
from app.auth import token as token_module
from app.auth.guards import REQUIRE_ADMIN, REQUIRE_MEMBER
from app.auth.models import AccountClaims
from app.auth.session_cookie import set_session_cookie
from app.auth.token import decode_token, encode_token, renewal_due
from app.core.middleware import SessionRenewalMiddleware
from app.main import app

_MEMBER = AccountClaims(
    sub="member-uuid", email="member@dojo.test", role="member", is_active=True
)
_ADMIN = AccountClaims(
    sub="admin-uuid", email="admin@dojo.test", role="admin", is_active=True
)


@contextmanager
def _minted_ago(seconds: int) -> Iterator[None]:
    """Mint tokens as if it were ``seconds`` ago.

    Tokens have to be *old* to be due for renewal, and a zero-length token
    (JWT_EXPIRE_MINUTES = 0) is a flake waiting to happen: it expires the
    instant the clock's integer second ticks over, so the guard rejects it as
    expired instead of renewing it. Shifting the mint time backwards keeps the
    token comfortably valid and unambiguously past half its life.
    """
    real = token_module.datetime

    class _Shifted(real):  # type: ignore[misc, valid-type]
        @classmethod
        def now(cls, tz=None):  # noqa: ANN001, ANN206
            return real.now(tz) - timedelta(seconds=seconds)

    token_module.datetime = _Shifted
    try:
        yield
    finally:
        token_module.datetime = real


def _stale(claims: AccountClaims, session_started_at: int | None = None) -> str:
    """A valid token that is past half its life, so renewal is due."""
    with _minted_ago(int(config.JWT_EXPIRE_MINUTES * 60 * 0.75)):
        return encode_token(claims, session_started_at)


class _Scalar:
    def __init__(self, value: object | None) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object | None:
        return self._value


class _FakeSession:
    def __init__(self, user: object | None) -> None:
        self._user = user

    async def get(self, _model: type, _pk: str) -> object | None:
        return self._user

    async def execute(self, _statement: object) -> _Scalar:
        # Renewal's only query: the sign-in email, read from the Member (#432).
        return _Scalar(getattr(self._user, "email", None))


class _FakeUow:
    def __init__(self, user: object | None) -> None:
        self.session = _FakeSession(user)


class _AccountRow:
    """The Account row, plus the email its Member carries (#432)."""

    def __init__(self, email: str, role: str, is_active: bool = True) -> None:
        self.id = "user-row-id"
        self.email = email
        self.role = role
        self.is_active = is_active


def _request() -> Request:
    return Request({"type": "http", "headers": [], "method": "GET", "path": "/"})


# ── renewal_due ──────────────────────────────────────────────────────────────


def test_fresh_token_is_not_due_for_renewal() -> None:
    assert renewal_due(encode_token(_MEMBER)) is None


def test_token_past_half_its_life_is_due() -> None:
    assert renewal_due(_stale(_MEMBER)) is not None


def test_session_past_the_hard_ceiling_is_not_renewed() -> None:
    """The ceiling wins over staleness — a long session must end, not slide."""
    started = int(time.time()) - (config.SESSION_MAX_MINUTES * 60) - 1

    assert renewal_due(_stale(_MEMBER, session_started_at=started)) is None


def test_renewal_preserves_the_original_session_start() -> None:
    """Each re-issue restarts `exp`, never `sst` — otherwise no ceiling exists."""
    started = int(time.time()) - 600
    first = _stale(_MEMBER, session_started_at=started)

    reissued = _stale(_MEMBER, session_started_at=renewal_due(first))

    assert renewal_due(reissued) == started


def test_a_slid_token_never_outlives_the_ceiling() -> None:
    """Otherwise the documented maximum session is quietly a lifetime longer."""
    started = int(time.time()) - (config.SESSION_MAX_MINUTES * 60) + 60

    token = encode_token(_MEMBER, session_started_at=started)

    exp = int(
        token_module.jwt.decode(
            token, token_module._key(), algorithms=["HS256"]
        ).claims["exp"]
    )
    assert exp <= started + config.SESSION_MAX_MINUTES * 60


# ── the guard mints a replacement ────────────────────────────────────────────


async def test_guard_mints_a_replacement_token_when_due() -> None:
    request = _request()

    await REQUIRE_MEMBER(
        request=request,
        uow=_FakeUow(_AccountRow(_MEMBER.email, "member")),
        access_token=_stale(_MEMBER),
    )

    assert decode_token(request.state.renewed_token).sub == _MEMBER.sub


async def test_guard_leaves_a_fresh_token_alone() -> None:
    request = _request()

    await REQUIRE_MEMBER(
        request=request,
        uow=_FakeUow(_AccountRow(_MEMBER.email, "member")),
        access_token=encode_token(_MEMBER),
    )

    assert getattr(request.state, "renewed_token", None) is None


async def test_renewal_rereads_the_user_row_so_a_promotion_takes_effect() -> None:
    """Role lives in the claims; renewal is the moment it can be refreshed."""
    request = _request()

    claims = await REQUIRE_ADMIN(
        request=request,
        uow=_FakeUow(_AccountRow(_MEMBER.email, "admin")),
        access_token=_stale(_MEMBER),
    )

    assert claims.role == "admin"
    assert decode_token(request.state.renewed_token).role == "admin"


async def test_renewal_rereads_the_user_row_so_a_demotion_bites() -> None:
    with pytest.raises(HTTPException) as exc:
        await REQUIRE_ADMIN(
            request=_request(),
            uow=_FakeUow(_AccountRow(_ADMIN.email, "member")),
            access_token=_stale(_ADMIN),
        )

    assert exc.value.status_code == 403


@pytest.mark.parametrize(
    "user", [_AccountRow("member@dojo.test", "member", is_active=False), None]
)
async def test_a_deactivated_or_deleted_user_is_signed_out_with_401(user) -> None:
    """401, not 403: there is no session left, so the SPA must route to login."""
    with pytest.raises(HTTPException) as exc:
        await REQUIRE_MEMBER(
            request=_request(),
            uow=_FakeUow(user),
            access_token=_stale(_MEMBER),
        )

    assert exc.value.status_code == 401


async def test_a_recovery_session_is_never_slid() -> None:
    """Recovery tokens are deliberately short-lived and scoped to recovery."""
    request = _request()

    with pytest.raises(HTTPException) as exc:
        await REQUIRE_MEMBER(
            request=request,
            uow=_FakeUow(_AccountRow(_MEMBER.email, "member")),
            access_token=token_module.encode_recovery_token(_MEMBER.sub, _MEMBER.email),
        )

    assert exc.value.status_code == 403
    assert getattr(request.state, "renewed_token", None) is None


# ── the cookie reaches every kind of response ────────────────────────────────


async def test_the_cookie_is_set_on_a_route_returning_a_response_directly() -> None:
    """FastAPI merges a dependency's headers only when it serializes a return
    value, so the bare 204s and the CSV streams would drop the slid cookie if
    the guard set it itself."""
    inner = FastAPI()
    inner.add_middleware(SessionRenewalMiddleware)

    @inner.get("/streamed")
    async def _streamed(request: Request) -> Response:
        request.state.renewed_token = encode_token(_MEMBER)
        return Response(status_code=204)

    async with AsyncClient(
        transport=ASGITransport(app=inner), base_url="http://test"
    ) as c:
        response = await c.get("/streamed")

    assert "access_token=" in response.headers["set-cookie"]


async def test_the_cookie_is_set_on_an_error_response() -> None:
    """The exception handler builds its own response — the slide must survive
    it, or a session that keeps hitting validation errors never renews."""
    inner = FastAPI()
    inner.add_middleware(SessionRenewalMiddleware)

    @inner.get("/boom")
    async def _boom(request: Request) -> Response:
        request.state.renewed_token = encode_token(_MEMBER)
        raise HTTPException(status_code=404)

    async with AsyncClient(
        transport=ASGITransport(app=inner), base_url="http://test"
    ) as c:
        response = await c.get("/boom")

    assert response.status_code == 404
    assert "access_token=" in response.headers["set-cookie"]


def test_the_app_installs_the_renewal_middleware() -> None:
    """The guard's slide is inert without it."""
    assert any(m.cls is SessionRenewalMiddleware for m in app.user_middleware)


def test_the_cookie_never_outlives_the_token_it_carries() -> None:
    """Near the session ceiling the token's exp is clamped, so Max-Age must be
    too (#397) — otherwise the browser keeps sending a dead token and holds the
    stale cookie all the way to /login."""
    started = int(time.time()) - (60 * config.SESSION_MAX_MINUTES - 120)
    token = encode_token(_MEMBER, started)
    response = Response()

    set_session_cookie(response, token)

    max_age = int(
        response.headers["set-cookie"].split("Max-Age=")[1].split(";")[0].strip()
    )
    assert max_age <= 120, "Max-Age must follow the clamped exp, not the full lifetime"
