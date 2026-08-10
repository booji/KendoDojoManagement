# Calibrating `AUTH_BEGIN_MIN_DURATION_MS`

Issue [#268](https://github.com/booji/KendoDojoManagement/issues/268). Supersedes the
unmeasured 50ms default introduced with the constant-time floor in
[#255](https://github.com/booji/KendoDojoManagement/issues/255).

## What the setting does

The passkey "begin" endpoints answer for any email, registered or not, so that a
caller cannot tell the two apart from the response. The *real* path (known email,
valid invite) does strictly more work than the decoy path — an extra SELECT, a
`pending_challenge` UPDATE, a commit — and #255 measured that asymmetry at a
~2ms median delta: enough to enumerate registered emails from latency alone.

`ConstantTimeAuthMiddleware` closes it by holding every request to these paths
for a fixed minimum wall-clock time:

- `POST /auth/register/passkey/begin`
- `POST /auth/login/passkey/begin`
- `POST /auth/invites/redeem/begin`

**The masking only works while the real path finishes under the floor.** Once a
real request overruns it there is nothing left to pad, and the delta is
observable again. So the floor has to sit above the real path's p99 — which is
what this document measures, because 50ms was picked as a round number and never
checked against PostgreSQL.

## How to reproduce the measurement

The harness is `backend/tests/test_auth_begin_calibration.py`. It is skipped
unless `AUTH_BEGIN_BENCH=1`, so it costs the normal suite nothing.

```bash
docker compose -f docker-compose.test.yml run --rm \
  -e PYTEST_TARGET=tests/test_auth_begin_calibration.py \
  -e AUTH_BEGIN_BENCH=1 \
  -e AUTH_BEGIN_MIN_DURATION_MS=1 \
  -e RATE_LIMIT_PER_IP=1000000/minute \
  -e PYTEST_ADDOPTS=-s \
  test > /tmp/bench.log 2>&1
```

The floor is dropped to 1ms so the measurement captures the endpoint's own work
rather than the pad, and the per-IP rate limit is lifted because every sample
arrives from one address. **Those two overrides belong only to this command.**
Together they disable the timing-side-channel defence and the brute-force rate
limit; never copy them into a deployed environment file. The harness itself
cannot run anywhere dangerous — `conftest.py` refuses any `DATABASE_URL` that
is not a PostgreSQL database with "test" in its name — but the env vars would
apply anywhere. It seeds real accounts, members and invites; drives
1000 measured requests per scenario over real HTTP against the uvicorn that
`run_tests.sh` starts; and then asserts the side effects only the real path
produces, so a seeding mistake cannot quietly report decoy-path timings as good
news.

Two views come out of one run. The harness prints **client-observed** latency.
The numbers below are the **server-side elapsed** that
`ConstantTimeAuthMiddleware` logs — with the floor at 1ms its "floor exceeded"
warning fires on every request and carries the elapsed time. That is the
quantity the floor is actually compared against, so it is the one the default
has to clear. Extract it with:

```bash
grep -a "floor exceeded" /tmp/bench.log
```

## Measured results

Environment: `docker-compose.test.yml` (PostgreSQL 16, default `fsync=on`),
podman on WSL2, developer workstation, 2026-08-10. n=1000 per row after 50
discarded warmup requests. All figures in milliseconds, server-side.

### Sequential — one request at a time

| endpoint | p50 | p90 | p95 | **p99** | max |
|---|---|---|---|---|---|
| `login/passkey/begin` | 7.4 | 9.0 | 9.6 | **11.0** | 14.2 |
| `register/passkey/begin` | 12.1 | 14.3 | 15.1 | **16.7** | 27.9 |
| `invites/redeem/begin` | 12.4 | 14.4 | 15.1 | **16.8** | 23.8 |

**Real-path p99 is 16.8ms; the worst single request out of 3000 was 27.9ms.**

### Under concurrency

Swept on `register/passkey/begin`, the heaviest repeatable path. "over 50ms" is
the share of requests that would have breached the old default.

| in-flight requests | p50 | p90 | **p99** | max | over 50ms |
|---|---|---|---|---|---|
| 1 | 12.1 | 14.3 | **16.7** | 27.9 | 0% |
| 2 | 15.1 | 18.0 | **22.1** | 30.0 | 0% |
| 4 | 33.1 | 38.6 | **45.7** | 53.2 | 0.3% |
| 8 | 67.1 | 89.3 | **167.0** | 183.0 | 98.5% |
| 12 | 108.0 | 153.5 | **281.1** | 339.2 | 100% |
| 20 | 206.6 | 356.7 | **534.7** | 553.6 | 100% |

Latency is dominated by queueing, not by the database: past ~4 simultaneous
requests the single uvicorn worker's event loop is the bottleneck and every
figure scales with concurrency.

## Conclusions

**The default is raised from 50ms to 100ms.**

- At the concurrency a single-dojo instance actually sees, the real path's p99
  is 16.8ms and its observed worst case 27.9ms. 50ms did clear both — the old
  default was not wrong, just unevidenced.
- It did not clear them by much. These numbers come from a developer
  workstation; the real path's cost is dominated by the commit, and a
  production volume on modest VPS storage can be several times slower than an
  overlay filesystem on a laptop. A 2× slower commit puts the observed maximum
  at ~56ms, past the old floor. 100ms absorbs that; 50ms does not.
- The pad itself is cheap. The unit-of-work commits and releases its connection
  inside the measured region, so a padded request holds an idle asyncio task and
  no database connection. At the 20/min per-IP limit, doubling the hold time
  changes in-flight occupancy by a fraction of a request per source — the DoS
  analysis in #266 is unaffected.
- 100ms is still well below the threshold at which a user notices latency on a
  deliberate action like starting a login.

**No floor survives a saturated server.** At 8 simultaneous begin requests the
p99 is already 167ms, and holding *that* would need a floor an order of
magnitude above anything sane. Raising the floor is not the remedy for
saturation:

- The condition is detectable. `ConstantTimeAuthMiddleware` logs a warning
  naming the elapsed and configured times on every overrun. Alert on it.
- The remedy is capacity or rate limiting — a second worker, or a tighter
  `RATE_LIMIT_PER_IP` — not a larger `AUTH_BEGIN_MIN_DURATION_MS`. Reaching 4+
  simultaneous begin requests requires many distinct source addresses, given the
  20/min per-IP limit, which is itself the signal worth acting on.

## Caveats

- **Measured on a developer workstation, not on UAT or production hardware.**
  The 100ms figure carries deliberate headroom for that reason, but it is not a
  substitute for the real thing. The cheapest confirmation is the one #268
  suggests: check UAT/production logs for "Constant-time floor exceeded". If it
  never fires under real use, the floor is comfortable. If it fires regularly on
  an unsaturated instance, the real path there is slower than measured here and
  this document should be re-run and revised.
- The measurement uses one uvicorn worker, matching the deployed container.
  Adding workers would move the concurrency knee but not the sequential figures.
- These are server-side times. A client also pays network latency, which does
  not help an attacker — it is added to both the real and the decoy path.
