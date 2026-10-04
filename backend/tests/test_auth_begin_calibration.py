"""Latency calibration harness for the constant-time auth floor (issue #268).

`AUTH_BEGIN_MIN_DURATION_MS` (issue #255) only masks the real-vs-decoy timing
delta on the passkey begin endpoints while the *real* path stays under it. Once
the real path overruns the floor there is nothing left to pad and the side
channel reopens. The 50ms default was a round number, never measured against
PostgreSQL under load — this module produces the measurement.

It is NOT part of the normal suite: it takes minutes, deliberately drives the
server far past a dojo's real traffic, and its output is a set of numbers to
read rather than an assertion to satisfy. It only collects when
`AUTH_BEGIN_BENCH=1`.

Run it (from the repo root) with the floor lowered out of the way, so what is
measured is the endpoint's own work rather than the pad, and with the per-IP
rate limit lifted, since every sample arrives from one address:

    docker compose -f docker-compose.test.yml run --rm \
      -e PYTEST_TARGET=tests/test_auth_begin_calibration.py \
      -e AUTH_BEGIN_BENCH=1 \
      -e AUTH_BEGIN_MIN_DURATION_MS=1 \
      -e RATE_LIMIT_PER_IP=1000000/minute \
      test -s > /tmp/bench.log 2>&1

Two independent views of the same requests come out of that run:

* client-observed latency, printed here as percentile tables — what an attacker
  timing the endpoint from outside actually sees;
* server-side elapsed, emitted by `ConstantTimeAuthMiddleware`'s "floor
  exceeded" warning, which fires on every request once the floor is 1ms. That
  is the quantity the floor is compared against, so it is the one the default
  has to clear. Parse it out of the same log.

Requests go over real HTTP to the uvicorn that `run_tests.sh` already started,
not through ASGITransport: the point is to include the whole stack the client
waits on, including the unit-of-work commit that runs *after* the route
returns (see ConstantTimeAuthMiddleware's docstring).
"""

import asyncio
import datetime as dt
import os
import statistics
import time
import uuid
from dataclasses import dataclass

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.auth.db_models import Account, Invite, PasskeyCredential
from app.auth.invite_service import hash_invite_token
from app.members.db_models import Member

pytestmark = pytest.mark.skipif(
    os.getenv("AUTH_BEGIN_BENCH") != "1",
    reason="calibration harness; set AUTH_BEGIN_BENCH=1 to collect (issue #268)",
)

API_URL = "http://localhost:8000/api"

#: Emails seeded for this run are tagged so teardown can delete exactly them
#: and nothing else — the benchmark commits, so it cannot lean on the
#: savepoint rollback the rest of the suite uses.
_TAG = "authbench"

#: Requests per scenario. Large enough that a p99 rests on ~10 samples in the
#: tail rather than one, without making a run take longer than a coffee.
SAMPLES = 1000

#: Concurrent in-flight requests for the loaded scenario. A single-dojo
#: instance rate-limits these endpoints to 20/min/IP, so 20 simultaneous
#: begin requests is already far beyond any honest peak; it stands in for a
#: server busy with other work (a check-in rush) rather than for real demand
#: on this endpoint.
CONCURRENCY = 20

#: Concurrency levels swept on the heaviest repeatable endpoint. The single
#: number that matters for setting the floor is not "how slow is it when
#: saturated" but "how much simultaneity does the configured floor survive",
#: and that needs points between idle and saturated.
SWEEP = (2, 4, 8, 12)

#: Discarded before measuring, so connection setup, JIT-ish first-call costs
#: and an empty Postgres buffer cache do not land in the tail.
WARMUP = 50

#: Requests issued per scenario, warmups included.
_PER_RUN = SAMPLES + WARMUP

#: Seeded invites must never expire mid-run — _is_usable rejects expired ones
#: and the request would silently take the decoy path instead.
_FAR_FUTURE = dt.datetime(2099, 1, 1, tzinfo=dt.UTC)


@dataclass
class Percentiles:
    label: str
    count: int
    p50: float
    p90: float
    p95: float
    p99: float
    p999: float
    maximum: float

    def render(self) -> str:
        return (
            f"{self.label:<46} n={self.count:<5} "
            f"p50={self.p50:6.1f}  p90={self.p90:6.1f}  p95={self.p95:6.1f}  "
            f"p99={self.p99:6.1f}  p99.9={self.p999:6.1f}  max={self.maximum:6.1f}"
        )


def percentiles(label: str, samples_ms: list[float]) -> Percentiles:
    ordered = sorted(samples_ms)

    def at(q: float) -> float:
        # Nearest-rank: with n=1000 the p99 is the 990th sample. Picking an
        # actual observation rather than interpolating keeps the number
        # defensible as "a request really took this long".
        index = min(len(ordered) - 1, max(0, round(q * len(ordered)) - 1))
        return ordered[index]

    return Percentiles(
        label=label,
        count=len(ordered),
        p50=at(0.50),
        p90=at(0.90),
        p95=at(0.95),
        p99=at(0.99),
        p999=at(0.999),
        maximum=ordered[-1],
    )


def _engine():
    return create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)


async def _seed() -> tuple[list[str], list[str]]:
    """Commit the rows the real paths need, returning (emails, invite tokens).

    Committed, not savepointed: the uvicorn process under measurement is a
    separate connection and would not see an uncommitted savepoint.
    """
    engine = _engine()
    emails = [f"{_TAG}-{i}-{uuid.uuid4().hex[:8]}@dojo.test" for i in range(_PER_RUN)]
    # Invites are single-use, so every request in both the sequential and the
    # concurrent run — warmups included — needs its own token.
    tokens = [uuid.uuid4().hex for _ in range(_PER_RUN * 2)]
    try:
        session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
        async with session_factory() as session:
            # One fully-registered account so register-begin is past bootstrap:
            # _is_bootstrap counts PasskeyCredential rows, and while it returns
            # True every email takes the real path, which is not the asymmetry
            # under test.
            anchor_id = str(uuid.uuid4())
            anchor_member_id = str(uuid.uuid4())
            await session.execute(
                insert(Member).values(
                    id=anchor_member_id,
                    email=f"{_TAG}-anchor-{uuid.uuid4().hex[:8]}@dojo.test",
                    first_name="Bench",
                    surname="Anchor",
                    join_date="2024-01-01",
                    membership_status="active",
                    is_coach=False,
                    is_first_aider=False,
                )
            )
            await session.execute(
                insert(Account).values(
                    id=anchor_id,
                    member_id=anchor_member_id,
                    role="admin",
                    is_active=True,
                )
            )
            await session.execute(
                insert(PasskeyCredential).values(
                    id=str(uuid.uuid4()),
                    user_id=anchor_id,
                    credential_id=uuid.uuid4().bytes,
                    public_key=b"bench-anchor-public-key",
                    sign_count=0,
                )
            )

            # register-begin's real path needs a Member with the email (the
            # #239 directory gate); login-begin's needs that Member's Account,
            # found by joining on members.email (#432).
            # Inserted as one executemany per table rather than a statement per
            # row: seeding is setup, not the thing being measured, and a few
            # thousand round trips is minutes of nothing.
            member_ids = [str(uuid.uuid4()) for _ in emails]
            await session.execute(
                insert(Member),
                [
                    {
                        "id": member_id,
                        "email": email,
                        "first_name": "Bench",
                        "surname": "Member",
                        # String(10) column, not a Date — see Member.join_date.
                        "join_date": "2024-01-01",
                        "membership_status": "active",
                        "is_coach": False,
                        "is_first_aider": False,
                    }
                    for member_id, email in zip(member_ids, emails, strict=True)
                ],
            )
            await session.execute(
                insert(Account),
                [
                    {
                        "id": str(uuid.uuid4()),
                        "member_id": member_id,
                        "role": "member",
                        "is_active": True,
                    }
                    for member_id in member_ids
                ],
            )

            # Invite redemption creates the account it invites, so a token only
            # takes the real path once — hence one seeded invite per request,
            # each for an email that has no Account yet.
            await session.execute(
                insert(Invite),
                [
                    {
                        "id": str(uuid.uuid4()),
                        "email": f"{_TAG}-inv-{uuid.uuid4().hex[:10]}@dojo.test",
                        "first_name": "Bench",
                        "surname": "Invitee",
                        "token_hash": hash_invite_token(token),
                        "expires_at": _FAR_FUTURE,
                    }
                    for token in tokens
                ],
            )
            await session.commit()
    finally:
        await engine.dispose()
    return emails, tokens


async def _assert_real_paths_taken(email_count: int, invite_count: int) -> None:
    """Fail loudly if the requests took the decoy path.

    The decoy responses are deliberately shape-identical to the real ones
    (issue #239), so a seeding mistake would not show up as a bad status code
    or a short body — it would show up as a suspiciously fast measurement that
    reads like good news. These are the side effects only the real path has.
    """
    engine = _engine()
    try:
        session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
        async with session_factory() as session:
            accounts = (
                select(func.count())
                .select_from(Account)
                .join(Member, Member.id == Account.member_id)
            )
            challenged = await session.scalar(
                accounts.where(
                    Member.email.like(f"{_TAG}-%"),
                    Account.pending_challenge.isnot(None),
                )
            )
            # The anchor is an Account too, but no request created it.
            linked = await session.scalar(
                accounts.where(
                    Member.email.like(f"{_TAG}-%"),
                    Member.email.notlike(f"{_TAG}-anchor-%"),
                )
            )
            invited_users = await session.scalar(
                accounts.where(Member.email.like(f"{_TAG}-inv-%"))
            )
    finally:
        await engine.dispose()

    # login/register begin both stamp pending_challenge; the invited accounts
    # created by redemption are stamped too, hence the sum.
    assert challenged == email_count + invite_count, (
        f"only {challenged} of {email_count + invite_count} accounts carry a "
        "challenge: some requests took the decoy path, so the numbers below "
        "understate the real path"
    )
    # Every Account belongs to a Member (#432), and invite redemption creates
    # its own, so the count covers the seeded members *and* the invited ones.
    assert linked == email_count + invite_count, (
        f"only {linked} of {email_count + invite_count} members have an "
        "account: register-begin or invite redemption took the decoy path"
    )
    assert invited_users == invite_count, (
        f"only {invited_users} of {invite_count} invited accounts exist: "
        "invite redemption took the decoy path"
    )


async def _teardown() -> None:
    """Delete only what this run seeded, by tag."""
    engine = _engine()
    try:
        session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
        async with session_factory() as session:
            tagged = Member.email.like(f"{_TAG}-%")
            user_ids = list(
                (
                    await session.execute(
                        select(Account.id)
                        .join(Member, Member.id == Account.member_id)
                        .where(tagged)
                    )
                ).scalars()
            )
            await session.execute(
                delete(PasskeyCredential).where(PasskeyCredential.user_id.in_(user_ids))
            )
            # Accounts before their Members: accounts.member_id is RESTRICT (#432).
            await session.execute(delete(Account).where(Account.id.in_(user_ids)))
            await session.execute(delete(Member).where(tagged))
            await session.execute(delete(Invite).where(Invite.email.like(f"{_TAG}-%")))
            await session.commit()
    finally:
        await engine.dispose()


async def _timed(client: AsyncClient, path: str, payload: dict) -> float:
    start = time.perf_counter()
    response = await client.post(path, json=payload)
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert response.status_code == 200, (path, response.status_code, response.text)
    return elapsed_ms


async def _run_sequential(path: str, payloads: list[dict]) -> list[float]:
    async with AsyncClient(base_url=API_URL, timeout=30.0) as client:
        for payload in payloads[:WARMUP]:
            await _timed(client, path, payload)
        return [await _timed(client, path, payload) for payload in payloads[WARMUP:]]


async def _run_concurrent(
    path: str, payloads: list[dict], concurrency: int = CONCURRENCY
) -> list[float]:
    """Same requests, CONCURRENCY of them in flight at once.

    Each worker holds its own client so connection reuse does not serialise
    the run onto one socket. The warmup requests are drained by a first pass
    whose timings are dropped, rather than by discarding the first N
    *completions* of the measured pass — under concurrency those are the
    fastest requests, not the coldest, so dropping them would trim the head of
    the distribution instead of its cold start.
    """

    async def drain(batch: list[dict], keep: bool) -> list[float]:
        queue: asyncio.Queue[dict] = asyncio.Queue()
        for payload in batch:
            queue.put_nowait(payload)
        collected: list[float] = []

        async def worker() -> None:
            async with AsyncClient(base_url=API_URL, timeout=30.0) as client:
                while True:
                    try:
                        payload = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        return
                    elapsed = await _timed(client, path, payload)
                    if keep:
                        collected.append(elapsed)

        await asyncio.gather(*(worker() for _ in range(concurrency)))
        return collected

    await drain(payloads[:WARMUP], keep=False)
    return await drain(payloads[WARMUP:], keep=True)


@pytest.mark.asyncio
async def test_measure_auth_begin_real_path_latency() -> None:
    """Print client-observed percentiles for every real path behind the floor.

    Asserts nothing about the numbers: the acceptance criterion for #268 is
    that they exist and are recorded, and an assertion here would only be a
    second, flakier copy of the floor the config already enforces.
    """
    emails, tokens = await _seed()
    try:
        login = [{"email": e} for e in emails]
        register = [{"email": e} for e in emails]
        invite = [{"token": t} for t in tokens]

        results = [
            percentiles(
                "login/passkey/begin  known email  seq",
                await _run_sequential("/auth/login/passkey/begin", login),
            ),
            percentiles(
                "register/passkey/begin  known email  seq",
                await _run_sequential("/auth/register/passkey/begin", register),
            ),
            percentiles(
                "invites/redeem/begin  valid token  seq",
                await _run_sequential("/auth/invites/redeem/begin", invite[:_PER_RUN]),
            ),
            percentiles(
                f"login/passkey/begin  known email  c={CONCURRENCY}",
                await _run_concurrent("/auth/login/passkey/begin", login),
            ),
            percentiles(
                f"register/passkey/begin  known email  c={CONCURRENCY}",
                await _run_concurrent("/auth/register/passkey/begin", register),
            ),
            percentiles(
                f"invites/redeem/begin  valid token  c={CONCURRENCY}",
                await _run_concurrent("/auth/invites/redeem/begin", invite[_PER_RUN:]),
            ),
        ]

        # Sweep the heaviest repeatable endpoint between idle and saturated, so
        # the doc can say which concurrency the chosen floor actually survives
        # rather than only that it survives an idle box and not a hammered one.
        sweep = [
            percentiles(
                f"register/passkey/begin  known email  c={level}",
                await _run_concurrent(
                    "/auth/register/passkey/begin", register, concurrency=level
                ),
            )
            for level in SWEEP
        ]

        results.extend(sweep)

        print("\n\n=== AUTH BEGIN LATENCY (client-observed, milliseconds) ===")
        for result in results:
            print(result.render())
        print(
            "\nWorst p99 across scenarios: "
            f"{max(r.p99 for r in results):.1f}ms\n"
            "Server-side elapsed for the same requests is in the "
            "'Constant-time floor exceeded' warnings above.\n"
        )
        print(
            "median-of-medians sanity: "
            f"{statistics.median([r.p50 for r in results]):.1f}ms"
        )

        # After printing, so a decoy-path mistake still shows its numbers next
        # to the explanation of why they are worthless.
        await _assert_real_paths_taken(len(emails), len(tokens))
    finally:
        await _teardown()
