"""Tests for the passkey begin-endpoint timing side channel (issue #255).

`login_passkey_begin` and `register_passkey_begin` currently take measurably
different wall-clock time depending on whether the email is known/authorized
(extra SELECT + UPDATE + commit) or unknown/unauthorized (a single SELECT and
an early return). The issue reports a ~2ms median delta, which is enough to
run as a timing side channel for enumerating emails.

The chosen fix is a constant-time floor: both branches of each begin endpoint
are held to a fixed minimum wall-clock duration (`asyncio.sleep` of whatever
remains), configured via `app.config.AUTH_BEGIN_MIN_DURATION_MS` (env var
`AUTH_BEGIN_MIN_DURATION_MS`, default 100ms since the calibration in #268 --
50ms when these tests were written). None of that exists yet -- these tests
are the red phase.

Written against the shared PostgreSQL test database via the `db_client`
fixture (conftest.py), following the fixture conventions in test_passkey.py /
test_passkey_enumeration.py. Timing assertions monkeypatch
the config value down to a small floor (20ms) instead of using the 50ms
default, so the suite stays fast; per the repo's TDD skill, monkeypatching a
config attribute that does not exist yet raises AttributeError -- that is the
expected failure mode until app/config.py grows the new setting.

No Playwright/e2e coverage is added for this issue: every acceptance
criterion here is about wall-clock latency of a service/HTTP call, which a
headless browser cannot measure meaningfully -- it would only add flake.
"""

import time
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert

from app import config
from app.auth.db_models import PasskeyCredential, User
from app.main import app
from app.members.db_models import Member
from tests.timing_support import assert_latency_converges_sampled

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


async def _seed_user(session, email: str, role: str = "member") -> str:
    """Seed a fully-registered user: a User row plus a PasskeyCredential.

    The credential is what makes register-begin count as "not bootstrap" --
    see the note in test_passkey_enumeration.py.
    """
    user_id = str(uuid.uuid4())
    await session.execute(
        insert(User).values(
            id=user_id,
            email=email,
            role=role,
            is_active=True,
        )
    )
    await session.execute(
        insert(PasskeyCredential).values(
            id=str(uuid.uuid4()),
            user_id=user_id,
            credential_id=uuid.uuid4().bytes,
            public_key=b"seeded-public-key",
            sign_count=0,
        )
    )
    await session.flush()
    return user_id


async def _seed_member(session, email: str) -> str:
    member_id = str(uuid.uuid4())
    await session.execute(
        insert(Member).values(
            id=member_id,
            email=email,
            first_name="Test",
            surname="Member",
            join_date="2024-01-01",
            membership_status="active",
            is_coach=False,
            is_first_aider=False,
        )
    )
    await session.flush()
    return member_id


async def _timed_post(client: AsyncClient, path: str, email: str) -> float:
    """POST to a begin endpoint, returning wall-clock duration in seconds."""
    start = time.perf_counter()
    response = await client.post(path, json={"email": email})
    elapsed = time.perf_counter() - start
    assert response.status_code == 200
    return elapsed


# ── AC1-AC4: each begin endpoint enforces the configured floor ──────────────


@pytest.mark.asyncio
async def test_login_begin_known_email_meets_floor(db_client, monkeypatch) -> None:
    """login_passkey_begin for a KNOWN email takes at least the configured
    minimum duration."""
    monkeypatch.setattr(config, "AUTH_BEGIN_MIN_DURATION_MS", 20)
    session = db_client
    await _seed_user(session, "known-floor@dojo.test")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        elapsed = await _timed_post(
            c, "/auth/login/passkey/begin", "known-floor@dojo.test"
        )

    assert elapsed >= 0.020


@pytest.mark.asyncio
async def test_login_begin_unknown_email_meets_floor(db_client, monkeypatch) -> None:
    """login_passkey_begin for an UNKNOWN email takes at least the configured
    minimum duration (the decoy path must not be faster than the floor)."""
    monkeypatch.setattr(config, "AUTH_BEGIN_MIN_DURATION_MS", 20)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        elapsed = await _timed_post(
            c, "/auth/login/passkey/begin", "nobody-floor@dojo.test"
        )

    assert elapsed >= 0.020


@pytest.mark.asyncio
async def test_register_begin_authorized_email_meets_floor(
    db_client, monkeypatch
) -> None:
    """register_passkey_begin for an AUTHORIZED email (matching Member) takes
    at least the configured minimum duration."""
    monkeypatch.setattr(config, "AUTH_BEGIN_MIN_DURATION_MS", 20)
    session = db_client
    await _seed_user(session, "existing-admin@dojo.test", role="admin")
    await _seed_member(session, "authorized-floor@dojo.test")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        elapsed = await _timed_post(
            c, "/auth/register/passkey/begin", "authorized-floor@dojo.test"
        )

    assert elapsed >= 0.020


@pytest.mark.asyncio
async def test_register_begin_bootstrap_email_meets_floor(
    db_client, monkeypatch
) -> None:
    """register_passkey_begin on a fresh (zero-User) instance -- the bootstrap
    real path -- takes at least the configured minimum duration."""
    monkeypatch.setattr(config, "AUTH_BEGIN_MIN_DURATION_MS", 20)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        elapsed = await _timed_post(
            c, "/auth/register/passkey/begin", "bootstrap-floor@dojo.test"
        )

    assert elapsed >= 0.020


@pytest.mark.asyncio
async def test_register_begin_unauthorized_email_meets_floor(
    db_client, monkeypatch
) -> None:
    """register_passkey_begin for an UNAUTHORIZED email (decoy path) takes at
    least the configured minimum duration."""
    monkeypatch.setattr(config, "AUTH_BEGIN_MIN_DURATION_MS", 20)
    session = db_client
    await _seed_user(session, "existing-admin@dojo.test", role="admin")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        elapsed = await _timed_post(
            c, "/auth/register/passkey/begin", "unauthorized-floor@dojo.test"
        )

    assert elapsed >= 0.020


# ── AC5: median latency difference between real and decoy paths is tiny ─────


@pytest.mark.asyncio
@pytest.mark.timing_sensitive
async def test_login_begin_known_vs_unknown_median_latency_converges(
    db_client, monkeypatch
) -> None:
    """Over interleaved samples, the median latency for a KNOWN email and an
    UNKNOWN email must differ by far less than the ~2ms signal in the issue.

    Interleaved sampling (not two separate blocks) avoids attributing warm-up
    or GC-pause skew to one branch. The tolerance is calibrated per run
    against same-path noise -- see tests/timing_support.py and issue #298.
    """
    # The floor must sit above the real path's p99 on whatever host is running
    # this, or there is nothing left to pad and the delta this test measures
    # reappears through no fault of the application (see ConstantTimeFloor's
    # docstring and docs/auth-timing-calibration.md). 20ms clears the 16.8ms
    # p99 measured on a dev machine by only 3ms — too thin for a shared CI
    # runner, where it voided the floor and failed this test with a 1.2ms
    # median delta against a 0.17ms control (#336). Use the shipped 100ms
    # default instead: production's own headroom, at ~5s per test.
    monkeypatch.setattr(config, "AUTH_BEGIN_MIN_DURATION_MS", 100)
    session = db_client
    await _seed_user(session, "known-median@dojo.test")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        await assert_latency_converges_sampled(
            lambda: _timed_post(
                c, "/auth/login/passkey/begin", "known-median@dojo.test"
            ),
            lambda: _timed_post(
                c, "/auth/login/passkey/begin", "unknown-median@dojo.test"
            ),
            label_a="known email",
            label_b="unknown email",
        )


@pytest.mark.asyncio
@pytest.mark.timing_sensitive
async def test_register_begin_authorized_vs_unauthorized_median_latency_converges(
    db_client, monkeypatch
) -> None:
    """Over interleaved samples, the median latency for an AUTHORIZED email
    and an UNAUTHORIZED email must differ by far less than the ~2ms signal in
    the issue."""
    # The floor must sit above the real path's p99 on whatever host is running
    # this, or there is nothing left to pad and the delta this test measures
    # reappears through no fault of the application (see ConstantTimeFloor's
    # docstring and docs/auth-timing-calibration.md). 20ms clears the 16.8ms
    # p99 measured on a dev machine by only 3ms — too thin for a shared CI
    # runner, where it voided the floor and failed this test with a 1.2ms
    # median delta against a 0.17ms control (#336). Use the shipped 100ms
    # default instead: production's own headroom, at ~5s per test.
    monkeypatch.setattr(config, "AUTH_BEGIN_MIN_DURATION_MS", 100)
    session = db_client
    await _seed_user(session, "existing-admin@dojo.test", role="admin")
    await _seed_member(session, "authorized-median@dojo.test")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        await assert_latency_converges_sampled(
            lambda: _timed_post(
                c, "/auth/register/passkey/begin", "authorized-median@dojo.test"
            ),
            lambda: _timed_post(
                c, "/auth/register/passkey/begin", "unauthorized-median@dojo.test"
            ),
            label_a="authorized email",
            label_b="unauthorized email",
        )


# ── AC6: the floor is configurable ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_login_begin_floor_is_configurable(db_client, monkeypatch) -> None:
    """Changing AUTH_BEGIN_MIN_DURATION_MS changes the observed minimum
    duration of login_passkey_begin."""
    session = db_client
    await _seed_user(session, "configurable-floor@dojo.test")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        monkeypatch.setattr(config, "AUTH_BEGIN_MIN_DURATION_MS", 15)
        low_elapsed = await _timed_post(
            c, "/auth/login/passkey/begin", "configurable-floor@dojo.test"
        )

        monkeypatch.setattr(config, "AUTH_BEGIN_MIN_DURATION_MS", 60)
        high_elapsed = await _timed_post(
            c, "/auth/login/passkey/begin", "configurable-floor@dojo.test"
        )

    assert low_elapsed >= 0.015
    assert high_elapsed >= 0.060
    # The higher floor must actually raise the observed duration, not be a
    # no-op setting.
    assert high_elapsed - low_elapsed >= 0.030


# ── Misconfiguration must not silently disable the floor ────────────────────


@pytest.mark.parametrize("bad_value", ["0", "-1", "not-a-number", ""])
def test_non_positive_or_invalid_floor_falls_back_to_default(
    bad_value, monkeypatch
) -> None:
    """A zero, negative or non-numeric AUTH_BEGIN_MIN_DURATION_MS must not be
    honoured.

    Any of these would make `remaining` permanently negative, so the pad would
    never fire and the timing leak would silently return with no indication
    that protection had been turned off. Treat it as misconfiguration and fall
    back to the safe default instead.
    """
    import importlib

    monkeypatch.setenv("AUTH_BEGIN_MIN_DURATION_MS", bad_value)
    reloaded = importlib.reload(config)
    try:
        # 100ms is the calibrated default (#268) — see
        # docs/auth-timing-calibration.md. Spelled out rather than read from
        # config, so lowering the default without revisiting the measurement
        # fails here instead of passing tautologically.
        assert reloaded.AUTH_BEGIN_MIN_DURATION_MS == 100
    finally:
        monkeypatch.delenv("AUTH_BEGIN_MIN_DURATION_MS", raising=False)
        importlib.reload(config)
