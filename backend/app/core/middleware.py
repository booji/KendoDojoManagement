import asyncio
import logging
import time
from collections.abc import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from app import config
from app.core.request_ip import client_ip
from app.core.security_logger import request_ip

# The passkey "begin" endpoints answer for any email, registered or not. Their
# real path (known/authorized email) does strictly more work than their decoy
# path -- an extra SELECT, a pending_challenge UPDATE, a commit, and the
# session teardown that commit implies -- so it is measurably slower. That
# delta is a side channel: it enumerates registered emails from response
# latency alone, without reading a single response body.
_log = logging.getLogger(__name__)

_CONSTANT_TIME_PATHS = frozenset(
    config.API_PREFIX + path
    for path in (
        "/auth/register/passkey/begin",
        "/auth/login/passkey/begin",
        "/auth/invites/redeem/begin",
    )
)


class ConstantTimeAuthMiddleware(BaseHTTPMiddleware):
    """Hold the passkey begin endpoints to a fixed minimum response time.

    This lives in middleware rather than inside the service functions on
    purpose. An earlier revision padded inside `login_passkey_begin` /
    `register_passkey_begin` and still leaked ~1.3ms, because the unit-of-work
    is a `yield` dependency: its commit/rollback/close runs *after* the
    service function returns, so the most expensive asymmetry in the request
    sat outside the padded region. Raising the floor did not help -- the
    residual is not part of what was being padded. Measuring at the outermost
    layer is the only way to cover everything the client can observe, and it
    additionally covers request validation and rate-limit rejections.

    `config.AUTH_BEGIN_MIN_DURATION_MS` is read per request, not bound at
    import, so it can be tuned or overridden in tests. It must stay above the
    real path's p99: once the real path overruns the floor there is nothing
    left to pad and the delta reappears. That p99 is measured, not assumed --
    see docs/auth-timing-calibration.md for the numbers behind the default and
    for why the warning below is a capacity signal rather than a prompt to
    raise the floor.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path not in _CONSTANT_TIME_PATHS:
            return await call_next(request)

        start = time.perf_counter()
        try:
            return await call_next(request)
        finally:
            elapsed = time.perf_counter() - start
            remaining = (config.AUTH_BEGIN_MIN_DURATION_MS / 1000) - elapsed
            if remaining > 0:
                await asyncio.sleep(remaining)
            else:
                # The request already outran the floor, so there is nothing
                # left to pad and the real-vs-decoy delta is observable again.
                # This is the one condition that silently voids the fix, so it
                # has to be visible to an operator rather than inferred from a
                # breach. No email or user id is logged: the whole point is
                # that this path must not record who was being probed.
                _log.warning(
                    "Constant-time floor exceeded on %s: %.1fms elapsed vs "
                    "%dms floor. Timing side channel is no longer masked; "
                    "raise AUTH_BEGIN_MIN_DURATION_MS above the real path's "
                    "p99 or investigate the slowdown.",
                    request.url.path,
                    elapsed * 1000,
                    config.AUTH_BEGIN_MIN_DURATION_MS,
                )


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # img-src is widened deliberately: Admin Settings previews an upload
        # from a `blob:` URL while the POST is in flight, and Vite inlines
        # small assets as `data:` URIs in the built CSS. Neither is reachable
        # under a bare default-src 'self'. Everything else stays same-origin,
        # which means no inline <script> anywhere in the SPA — see
        # test_spa_html_has_no_inline_script, and frontend/public/theme.js for
        # where the pre-paint theme script went (#385). object-src and
        # base-uri are pinned because neither falls back to default-src in a
        # way worth relying on.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' blob: data:; "
            "object-src 'none'; base-uri 'self'"
        )
        return response


class ClientIPMiddleware:
    """Bind the client IP for every security event raised by this request.

    Pure ASGI rather than BaseHTTPMiddleware: the binding is reset when the
    request ends, so it never leaks into whatever runs next in the context.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        token = request_ip.set(client_ip(Request(scope)))
        try:
            await self.app(scope, receive, send)
        finally:
            request_ip.reset(token)
