import asyncio
import logging
import time
from collections.abc import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app import config

# The passkey "begin" endpoints answer for any email, registered or not. Their
# real path (known/authorized email) does strictly more work than their decoy
# path -- an extra SELECT, a pending_challenge UPDATE, a commit, and the
# session teardown that commit implies -- so it is measurably slower. That
# delta is a side channel: it enumerates registered emails from response
# latency alone, without reading a single response body.
_log = logging.getLogger(__name__)

_CONSTANT_TIME_PATHS = frozenset(
    {
        "/auth/register/passkey/begin",
        "/auth/login/passkey/begin",
        "/auth/invites/redeem/begin",
    }
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
    left to pad and the delta reappears.
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
        response.headers["Content-Security-Policy"] = "default-src 'self'"
        return response
