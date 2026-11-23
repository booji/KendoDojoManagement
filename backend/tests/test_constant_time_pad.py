"""The constant-time pad must end at its deadline whatever is left to pad (#596).

`asyncio.sleep` on Linux does not wake at a duration-independent offset from
its deadline. asyncio's `EpollSelector` rounds the timeout up to whole
milliseconds as `math.ceil(t * 1e3) * 1e-3`; for some k that float lands just
above k/1000 (`18 * 1e-3 == 0.018000000000000002`), and CPython's `epoll.poll`
rounds it up again, so a timeout of 9, 13, 18, 26, ... 87 ms waits a whole
extra millisecond. A pad that is one `asyncio.sleep(remaining)` therefore ends
~1ms later for a path whose `remaining` rounds up to one of those values than
for a path whose `remaining` does not -- the real and decoy paths diverge by
exactly the amount the pad exists to hide.

This drives two handlers through `ConstantTimeAuthMiddleware` whose work
differs by 1ms, so that under a 20ms floor one has ~17.5ms left to pad (rounds
up to the bad 18) and the other ~16.5ms (rounds up to 17), and asserts their
end-to-end latency still matches.
"""

import statistics
import time

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Route

from app import config
from app.core.middleware import ConstantTimeAuthMiddleware

_PADDED_PATH = config.API_PREFIX + "/auth/login/passkey/begin"
_FLOOR_MS = 20
_SAMPLES = 15


def _busy(seconds: float) -> None:
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        pass


async def _work(request):
    # Blocking on purpose: the work must sit inside the measured region at a
    # known length, not yield to the loop.
    _busy(float(request.query_params["work_ms"]) / 1000)
    return JSONResponse({})


@pytest.mark.timing_sensitive
async def test_pad_ends_at_the_same_time_whatever_is_left_to_pad(monkeypatch) -> None:
    monkeypatch.setattr(config, "AUTH_BEGIN_MIN_DURATION_MS", _FLOOR_MS)
    app = Starlette(
        routes=[Route(_PADDED_PATH, _work, methods=["POST"])],
        middleware=[Middleware(ConstantTimeAuthMiddleware)],
    )
    # ~17.5ms left to pad rounds up to 18, which epoll overshoots by a whole
    # millisecond; ~16.5ms rounds up to 17, which it does not.
    bad_bucket, good_bucket = "2.5", "3.5"
    samples: dict[str, list[float]] = {bad_bucket: [], good_bucket: []}

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        for i in range(_SAMPLES * 2):
            # Alternate which goes first, so drift cannot favour either.
            order = (bad_bucket, good_bucket) if i % 2 else (good_bucket, bad_bucket)
            for work_ms in order:
                start = time.perf_counter()
                r = await c.post(_PADDED_PATH, params={"work_ms": work_ms})
                samples[work_ms].append(time.perf_counter() - start)
                assert r.status_code == 200

    delta_ms = (
        statistics.median(samples[bad_bucket]) - statistics.median(samples[good_bucket])
    ) * 1000
    assert abs(delta_ms) < 0.5, (
        f"pad end depends on what was left to pad: median delta {delta_ms:+.3f}ms "
        f"between {bad_bucket}ms and {good_bucket}ms of work under a "
        f"{_FLOOR_MS}ms floor (#596)"
    )
