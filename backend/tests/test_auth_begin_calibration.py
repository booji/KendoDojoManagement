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
import base64
import datetime as dt
import hashlib
import json
import os
import statistics
import struct
import time
import uuid
from dataclasses import dataclass

import bcrypt
import cbor2
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from httpx import AsyncClient
from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.auth.db_models import (
    Account,
    AdminRecoveryToken,
    Invite,
    PasskeyCredential,
    RecoveryAttempt,
    RecoveryCode,
)
from app.auth.invite_service import hash_invite_token
from app.auth.recovery_service import BCRYPT_ROUNDS
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
            # One fully-registered account so the instance is claimed, as a
            # live one is.
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

            # login-begin's real path needs an Account, found by joining on
            # members.email (#432).
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

    # login begin stamps pending_challenge; the invited accounts created by
    # redemption are stamped too, hence the sum.
    assert challenged == email_count + invite_count, (
        f"only {challenged} of {email_count + invite_count} accounts carry a "
        "challenge: some requests took the decoy path, so the numbers below "
        "understate the real path"
    )
    # Every Account belongs to a Member (#432), and invite redemption creates
    # its own, so the count covers the seeded members *and* the invited ones.
    assert linked == email_count + invite_count, (
        f"only {linked} of {email_count + invite_count} members have an "
        "account: invite redemption took the decoy path"
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
            for table in (
                PasskeyCredential,
                RecoveryCode,
                RecoveryAttempt,
                AdminRecoveryToken,
            ):
                await session.execute(delete(table).where(table.user_id.in_(user_ids)))
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
        invite = [{"token": t} for t in tokens]

        results = [
            percentiles(
                "login/passkey/begin  known email  seq",
                await _run_sequential("/auth/login/passkey/begin", login),
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
                f"invites/redeem/begin  valid token  c={CONCURRENCY}",
                await _run_concurrent("/auth/invites/redeem/begin", invite[_PER_RUN:]),
            ),
        ]

        # Sweep the heaviest repeatable endpoint between idle and saturated, so
        # the doc can say which concurrency the chosen floor actually survives
        # rather than only that it survives an idle box and not a hammered one.
        sweep = [
            percentiles(
                f"login/passkey/begin  known email  c={level}",
                await _run_concurrent(
                    "/auth/login/passkey/begin", login, concurrency=level
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


# ── recovery/redeem and login/passkey/complete (#594) ─────────────────────────

#: Redeem runs nine bcrypt comparisons at cost 12, seconds per request, so it
#: gets fewer samples: a p99 on ~2 tail samples, read with that in mind.
REDEEM_SAMPLES = 200
REDEEM_WARMUP = 10
REDEEM_SWEEP = (2, 4)

#: login/passkey/complete is as cheap as the begin endpoints are.
COMPLETE_SWEEP = (4, 8)

_RP_ID = os.environ.get("WEBAUTHN_RP_ID", "localhost")
_ORIGIN = os.environ.get("WEBAUTHN_ORIGIN", "http://localhost:5173")


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


class _SoftAuthenticator:
    """One P-256 key standing in for every benched Account's passkey, so a
    login completes for real: signature verified, sign count bumped, an Auth
    Session started and committed."""

    def __init__(self) -> None:
        self._key = ec.generate_private_key(ec.SECP256R1())
        numbers = self._key.public_key().public_numbers()
        self.cose_public_key = cbor2.dumps(
            {
                1: 2,  # kty: EC2
                3: -7,  # alg: ES256
                -1: 1,  # crv: P-256
                -2: numbers.x.to_bytes(32, "big"),
                -3: numbers.y.to_bytes(32, "big"),
            }
        )

    def assertion(self, credential_id: bytes, challenge: str) -> dict:
        client_data = json.dumps(
            {"type": "webauthn.get", "challenge": challenge, "origin": _ORIGIN}
        ).encode()
        # rpIdHash, flags UP|UV, sign count 1 (each credential is used once).
        auth_data = (
            hashlib.sha256(_RP_ID.encode()).digest() + b"\x05" + struct.pack(">I", 1)
        )
        signature = self._key.sign(
            auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256())
        )
        return {
            "id": _b64url(credential_id),
            "rawId": _b64url(credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": _b64url(client_data),
                "authenticatorData": _b64url(auth_data),
                "signature": _b64url(signature),
            },
        }


async def _seed_accounts(
    count: int, *, authenticator: _SoftAuthenticator | None, secret_hashes: list[str]
) -> list[tuple[str, bytes]]:
    """`count` tagged Accounts, each with a passkey from `authenticator` and,
    when `secret_hashes` is given, eight recovery codes and one admin token
    hashed from it. Returns (email, credential id) per Account."""
    engine = _engine()
    emails = [f"{_TAG}-{uuid.uuid4().hex[:12]}@dojo.test" for _ in range(count)]
    member_ids = [str(uuid.uuid4()) for _ in emails]
    account_ids = [str(uuid.uuid4()) for _ in emails]
    credential_ids = [uuid.uuid4().bytes for _ in emails]
    expires = dt.datetime.now(dt.UTC) + dt.timedelta(hours=6)
    try:
        session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
        async with session_factory() as session:
            await session.execute(
                insert(Member),
                [
                    {
                        "id": member_id,
                        "email": email,
                        "first_name": "Bench",
                        "surname": "Member",
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
                    {"id": account_id, "member_id": member_id, "role": "member"}
                    for account_id, member_id in zip(
                        account_ids, member_ids, strict=True
                    )
                ],
            )
            if authenticator is not None:
                await session.execute(
                    insert(PasskeyCredential),
                    [
                        {
                            "id": str(uuid.uuid4()),
                            "user_id": account_id,
                            "credential_id": credential_id,
                            "public_key": authenticator.cose_public_key,
                            "sign_count": 0,
                        }
                        for account_id, credential_id in zip(
                            account_ids, credential_ids, strict=True
                        )
                    ],
                )
            if secret_hashes:
                set_id = str(uuid.uuid4())
                await session.execute(
                    insert(RecoveryCode),
                    [
                        {
                            "id": str(uuid.uuid4()),
                            "user_id": account_id,
                            "code_hash": code_hash,
                            "set_id": set_id,
                        }
                        for account_id in account_ids
                        for code_hash in secret_hashes[:8]
                    ],
                )
                await session.execute(
                    insert(AdminRecoveryToken),
                    [
                        {
                            "id": str(uuid.uuid4()),
                            "user_id": account_id,
                            "token_hash": secret_hashes[8],
                            "expires_at": expires,
                        }
                        for account_id in account_ids
                    ],
                )
            await session.commit()
    finally:
        await engine.dispose()
    return list(zip(emails, credential_ids, strict=True))


async def _post_timed(
    client: AsyncClient, path: str, payload: dict, expected: int
) -> float:
    start = time.perf_counter()
    response = await client.post(path, json=payload)
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert response.status_code == expected, (path, response.status_code, response.text)
    return elapsed_ms


async def _sweep(measure, items: list, warmup: int, concurrency: int) -> list[float]:
    """`measure(client, item)` for every item, `concurrency` at a time, the
    first `warmup` items' timings dropped (see `_run_concurrent`)."""

    async def drain(batch: list, keep: bool) -> list[float]:
        queue: asyncio.Queue = asyncio.Queue()
        for item in batch:
            queue.put_nowait(item)
        collected: list[float] = []

        async def worker() -> None:
            async with AsyncClient(base_url=API_URL, timeout=120.0) as client:
                while True:
                    try:
                        item = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        return
                    elapsed = await measure(client, item)
                    if keep:
                        collected.append(elapsed)

        await asyncio.gather(*(worker() for _ in range(concurrency)))
        return collected

    await drain(items[:warmup], keep=False)
    return await drain(items[warmup:], keep=True)


@pytest.mark.asyncio
async def test_measure_redeem_and_login_complete_latency() -> None:
    """Percentiles for the work a recovery redeem and a successful passkey
    login do, to calibrate their floors (#594). Asserts nothing about them,
    for the reason `test_measure_auth_begin_real_path_latency` gives.

    Redeem is measured on its slowest path: a known email sending a wrong
    code, so all nine hashes are compared and a failed attempt is written.
    Each Account is used once, so none reaches the lockout.
    """
    secret_hashes = [
        bcrypt.hashpw(
            f"bench-secret-{i}".encode(), bcrypt.gensalt(BCRYPT_ROUNDS)
        ).decode()
        for i in range(9)
    ]
    redeem_runs = 1 + len(REDEEM_SWEEP)
    redeem_per_run = REDEEM_SAMPLES + REDEEM_WARMUP
    complete_runs = 1 + len(COMPLETE_SWEEP)
    authenticator = _SoftAuthenticator()
    try:
        redeem_accounts = await _seed_accounts(
            redeem_per_run * redeem_runs,
            authenticator=None,
            secret_hashes=secret_hashes,
        )
        complete_accounts = await _seed_accounts(
            _PER_RUN * complete_runs, authenticator=authenticator, secret_hashes=[]
        )

        async def redeem(client: AsyncClient, account: tuple[str, bytes]) -> float:
            email, _ = account
            return await _post_timed(
                client,
                "/auth/recovery/redeem",
                {"email": email, "code": "wrong-code-zzzz"},
                401,
            )

        async def unknown_redeem(client: AsyncClient, _: object) -> float:
            return await _post_timed(
                client,
                "/auth/recovery/redeem",
                {"email": f"{_TAG}-nobody@dojo.test", "code": "wrong-code-zzzz"},
                401,
            )

        async def complete(client: AsyncClient, account: tuple[str, bytes]) -> float:
            email, credential_id = account
            begun = await client.post(
                "/auth/login/passkey/begin", json={"email": email}
            )
            challenge = begun.json()["publicKey"]["challenge"]
            return await _post_timed(
                client,
                "/auth/login/passkey/complete",
                {
                    "email": email,
                    "credential": authenticator.assertion(credential_id, challenge),
                },
                200,
            )

        def chunk(items: list, index: int, size: int) -> list:
            return items[index * size : (index + 1) * size]

        results = [
            percentiles(
                "recovery/redeem  known, wrong code  seq",
                await _sweep(
                    redeem, chunk(redeem_accounts, 0, redeem_per_run), REDEEM_WARMUP, 1
                ),
            ),
            percentiles(
                "recovery/redeem  unknown email  seq",
                await _sweep(unknown_redeem, [None] * redeem_per_run, REDEEM_WARMUP, 1),
            ),
        ]
        for run, level in enumerate(REDEEM_SWEEP, start=1):
            results.append(
                percentiles(
                    f"recovery/redeem  known, wrong code  c={level}",
                    await _sweep(
                        redeem,
                        chunk(redeem_accounts, run, redeem_per_run),
                        REDEEM_WARMUP,
                        level,
                    ),
                )
            )
        results.append(
            percentiles(
                "login/passkey/complete  success  seq",
                await _sweep(
                    complete, chunk(complete_accounts, 0, _PER_RUN), WARMUP, 1
                ),
            )
        )
        for run, level in enumerate(COMPLETE_SWEEP, start=1):
            results.append(
                percentiles(
                    f"login/passkey/complete  success  c={level}",
                    await _sweep(
                        complete, chunk(complete_accounts, run, _PER_RUN), WARMUP, level
                    ),
                )
            )

        print("\n\n=== REDEEM / COMPLETE LATENCY (client-observed, milliseconds) ===")
        for result in results:
            print(result.render())
        print(
            "\nServer-side elapsed for redeem is in the 'Constant-time floor "
            "exceeded' warnings above.\n"
        )
    finally:
        await _teardown()
