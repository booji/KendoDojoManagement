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

- `POST /auth/login/passkey/begin`
- `POST /auth/invites/redeem/begin`

Two heavier endpoints have floors of their own, calibrated in
[Login complete and recovery redeem](#login-complete-and-recovery-redeem-594):
`LOGIN_COMPLETE_MIN_DURATION_MS` for `POST /auth/login/passkey/complete` and
`RECOVERY_REDEEM_MIN_DURATION_MS` for `POST /auth/recovery/redeem`.

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

Swept on `register/passkey/begin`, then the heaviest repeatable path (removed in
#472; a new run sweeps `login/passkey/begin`). "over 50ms" is
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

### Re-measured for #432 — one email, on the Member

[#432](https://github.com/booji/KendoDojoManagement/issues/432) changed every
query on these paths: `users.email` is gone, and an Account is found by joining
its Member on `members.email`. Registration and invite redemption now create
the Account from a Member id (invite redemption creates that Member first when
there is none). Same command, same environment class, 2026-10-03:

| endpoint | p50 | p90 | p95 | **p99** | max |
|---|---|---|---|---|---|
| `login/passkey/begin` | 5.0 | 5.7 | 5.9 | **6.5** | 32.9 |
| `register/passkey/begin` | 5.3 | 6.0 | 6.3 | **6.8** | 11.0 |
| `invites/redeem/begin` | 7.8 | 9.0 | 9.4 | **10.5** | 20.7 |

Server-side, sequential, n=1000 per row after 50 warmups. The join costs
nothing measurable: every p99 is below the August figures, which says more
about the workstation on the day than about the change. The worst single
request, 32.9ms, is a third of the 100ms floor, so the default stands. The
concurrency sweep kept its shape: queueing past ~4 requests in flight, as
above.

Parity between known and unknown emails is a separate check, and it is still
the one that gates: `test_passkey_timing.py` and `test_timing_convergence.py`
assert that the real and decoy paths converge, and both pass against the new
queries.

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

## Login complete and recovery redeem (#594)

[#594](https://github.com/booji/KendoDojoManagement/issues/594) put two more
endpoints behind the middleware, each with its own floor:

- **`login/passkey/complete`.** #587 made a known and an unknown email do the
  same work before a credential matches. That left no margin: its timing test
  failed on the pre-fix code by only 0.03ms. A floor gives a margin that does
  not depend on the machine.
- **`recovery/redeem`.** #588 padded the bcrypt work, but a known email still
  did database work an unknown one skipped, about 12ms: the lockout lookup,
  reading its codes and tokens, and writing a failed attempt.

The harness is `test_measure_redeem_and_login_complete_latency`, in the same
file and behind the same flag:

```bash
podman-compose -f docker-compose.test.yml run --rm \
  -e PYTEST_TARGET=tests/test_auth_begin_calibration.py \
  -e "PYTEST_ARGS=-k redeem_and_login_complete" \
  -e AUTH_BEGIN_BENCH=1 \
  -e AUTH_BEGIN_MIN_DURATION_MS=1 \
  -e LOGIN_COMPLETE_MIN_DURATION_MS=1 \
  -e RECOVERY_REDEEM_MIN_DURATION_MS=1 \
  -e RATE_LIMIT_PER_IP=1000000/minute \
  -e PYTEST_ADDOPTS=-s \
  test-backend > /tmp/bench.log 2>&1
```

The warning about the overrides above applies here too.

- **Login complete** is measured on a successful login, its heaviest path:
  signature check, sign count, a new Auth Session, a commit. The harness signs
  real assertions with a P-256 key.
- **Redeem** is measured on its slowest path: a known email with a full code
  set and an admin token, sending a wrong code. All nine hashes are compared at
  cost 12, and a failed attempt is written. Each Account is used once, so none
  reaches the lockout.

Same environment class as above, 2026-11-12. Milliseconds, after warmups.

| endpoint | n | p50 | p90 | p95 | **p99** | max |
|---|---|---|---|---|---|---|
| `login/passkey/complete`, success, seq | 1000 | 19.1 | 22.0 | 22.9 | **26.1** | 105.2 |
| `login/passkey/complete`, success, c=4 | 1000 | 49.0 | 58.5 | 61.6 | **70.6** | 203.2 |
| `login/passkey/complete`, success, c=8 | 1000 | 96.9 | 113.9 | 119.4 | **163.6** | 250.2 |
| `recovery/redeem`, known, seq | 200 | 1902.9 | 1949.0 | 1970.7 | **2018.8** | 2148.5 |
| `recovery/redeem`, unknown, seq | 200 | 1906.0 | 2193.5 | 2237.0 | **2337.0** | 2521.2 |
| `recovery/redeem`, known, c=2 | 200 | 2333.8 | 2448.3 | 2494.9 | **2568.8** | 2619.1 |
| `recovery/redeem`, known, c=4 | 200 | 2346.5 | 2452.9 | 2635.9 | **3016.9** | 3061.1 |

The redeem rows are server-side, from the middleware's warnings. The login
complete rows are client-observed, because the endpoint had no floor yet to
log one. Over loopback, that adds well under a millisecond. Redeem takes
seconds per request, so its rows have 200 samples, and each p99 rests on two.

**`LOGIN_COMPLETE_MIN_DURATION_MS` defaults to 250ms.** Its worst single
request one at a time, 105ms, already passes the begin endpoints' 100ms floor,
so complete needs a floor of its own. 250ms is 2.4 times that worst case. It
also clears every request at 4 in flight, and the p99 at 8.

**`RECOVERY_REDEEM_MIN_DURATION_MS` defaults to 5000ms.** That is 2.5 times
the sequential p99 and 1.6 times the worst request at 4 in flight. bcrypt is
CPU-bound, so a slower VPS core scales the whole figure, not only the commit.
Recovery is rare and deliberate, so a 5-second answer costs a user little.

The [Conclusions](#conclusions) above hold for both floors. A "Constant-time
floor exceeded" warning names the endpoint and its setting, and it is a
capacity signal, not a reason to keep raising the floor.

## The convergence assertion's own false-failure rate

Separately from the floor, `backend/tests/timing_support.py` asserts that the
real and decoy paths converge in latency. Its tolerance is calibrated against
the noise in the run being judged, but floored at the 1ms budget inherited from
#255 — so on a *quiet* run, where `3 × control` falls under that floor, the
calibration is switched off by its own lower bound and the run is judged
against a flat 1ms. Every observed false failure lived in that regime
([#364](https://github.com/booji/KendoDojoManagement/issues/364)): same-path
controls of 0.08–0.20ms against cross-path deltas of 1.12–1.34ms, on three
unrelated branches including `main`.

Raising the floor is not available as a remedy — it is the #255 budget, and it
would eat the margin `MAX_TOLERANCE_S` deliberately leaves under the ~2.02ms
leak that issue measured. Instead a tripped assertion is **re-measured from
scratch and fails only if it reproduces** (`assert_latency_converges_sampled`).
A false failure is a per-run sampling accident; a real asymmetry is present on
every run.

Measured by Monte Carlo, two branches drawn from an identical distribution at
the #298 noise level (±3ms spread, n=31, 100,000 trials):

| rounds required | false-failure rate |
|---|---|
| 1 | 5.503% |
| **2 (shipped)** | **0.317%** |

Detection is unaffected for every leak shape the suite has a fixture for; the
per-shape figures and the one shape that does pay for it are tabulated in the
`timing_support.py` module docstring. Cost is one extra sampling round on the
failing path only.

### Why a confirmed failure is worth reading

[#360](https://github.com/booji/KendoDojoManagement/issues/360) asked for the
delta to be measured directly, isolated and under load, before any bound was
touched — a load-dependent *real* asymmetry and a sampling accident look alike
in a single run. Sampling the redeem-begin pair over 15 rounds per condition,
varying only the number of tasks contending for the event loop:

| contending tasks | signed median delta | valid slower | control |
|---|---|---|---|
| 0 | +0.001 ms | 8/15 | 0.173 ms |
| 1 | −0.019 ms | 7/15 | 0.149 ms |
| 2 | +0.005 ms | 8/15 | 0.136 ms |
| **4** | **+1.514 ms** | **15/15** | 1.139 ms |

Unloaded, the delta is nil and its **sign is a coin flip** — the fingerprint of
a sampling accident, and the regime every observed false failure came from.
Under real contention the sign stops flipping, and the middleware logs
`Constant-time floor exceeded ... 169.3ms elapsed vs 20ms floor` alongside it.
That is not the harness misreading noise: the real path's work has overrun
`AUTH_BEGIN_MIN_DURATION_MS`, the floor has stopped masking it, and while the
load lasts the asymmetry is as visible to an attacker as to the test.

#360 poses the choice as *inherent to the endpoint, fix at source* versus
*load-induced, make the calibration load-robust*. The measurement says
neither. The observed false failures had quiet controls (0.08–0.20 ms), and
the quiet rows above show no delta to be robust *to* — under 0.02 ms, sign
random. They are accidents in the tail of that distribution. The loaded row is
a different event, and a true positive: the floor really has stopped masking,
so damping it with a quiet phase or a load term would suppress the one reading
worth having. What remains is to tell accident from asymmetry by whether it
recurs.

Confirmation therefore suppresses the accident without suppressing the
unmasking — the accident gets a fresh coin and mostly does not recur, the
unmasking holds for as long as the machine is busy. So 0.317% is the floor of
the achievable rate rather than a promise, and a failure that survives both
rounds should be read as *check whether the floor was exceeded* — which is what
the assertion message now says.

### CI reports these assertions; it does not gate on them

Since the confirmation round shipped, this assertion has failed **2 of 6** runs
on GitHub's hosted runners — against the 0.317% predicted above. Both failures
reproduced across both rounds, so whatever drives them persists rather than
resampling away, and the independence the 0.317% assumes does not hold there.

Neither documented mechanism explains it. The most recent failure had:

- same-path control **0.026 ms** — an exceptionally quiet run, not a contended one
- cross-path delta **1.317 ms**
- **no** `Constant-time floor exceeded` warning anywhere in the run, so every
  request finished inside the floor and both paths should have been padded to
  the same total

Two hypotheses were tested and ruled out:

| Hypothesis | Test | Result |
|---|---|---|
| Response length differs between paths | Compared bodies directly | Byte-identical, 1045 both — #354's equalisation holds |
| Residual is the post-response UoW teardown, outside the padded region | Raised the floor 20 ms → 200 ms under identical load | +3.529 ms → +0.072 ms. A residual outside the padded region could not be absorbed by a larger floor, so it is inside it |

So the **local contention case is understood** (the real path approaches the
floor, the mask stops working, a larger floor absorbs it) and the **CI case is
not**.

The same unexplained shape also shows up locally, so it is not specific to
GitHub's runners. On 2026-11-09, `test_invite_redeem_begin_valid_vs_invalid_median_latency_converges`
failed in a local full-suite run (Podman, `docker-compose.test.yml`, the `test`
service) on the #593 branch. That branch does not touch the invite or
floor-middleware code. The failure:

- same-path control **0.098 ms**
- cross-path delta **1.225 ms**, n=31, reproduced on both rounds
- **no** `Constant-time floor exceeded` warning

The same test passed in the full run before it, on the same branch, and when
`tests/test_invites.py` was rerun alone straight afterwards. During #589 it also
failed once and passed on two reruns.

### Explained: the pad's own wake-up (#596)

[#596](https://github.com/booji/KendoDojoManagement/issues/596) found the cause.
The delta was never in the endpoint's work or in teardown. It was in how late
the pad's `asyncio.sleep(remaining)` woke up, and that depended on `remaining`.

On Linux, asyncio's `EpollSelector` rounds a timeout up to whole milliseconds
as `math.ceil(t * 1e3) * 1e-3`. For some k, the float `k * 1e-3` lands just
above k/1000 (`18 * 1e-3 == 0.018000000000000002`), and CPython's
`epoll.poll` rounds it up again. A timeout of k ms then waits k+1 ms. Up to
200ms the affected values are 9, 13, 18, 26, 36, 52, 59, 67, 71, 72, 87, 103,
104, 118, 119, 134, 142, 143, 144, 174 and 175.

Under the invite test's 20ms floor, the decoy path had 17.x ms left to pad.
That rounds up to 18 and waited 19ms. The real path had 16.x ms, which rounds
up to 17 and waited 17ms. Which path lands in a bad bucket depends on how fast
the machine runs the handler. That is why the failure came and went with load
and runner, why its sign flipped, and why it reproduced on both rounds with a
quiet control and no floor-exceeded warning.

The earlier test that "ruled out" a residual outside the padded region was
taken under contention: the +3.529ms row is the loaded case. It never measured
the quiet case. In this test the residual couldn't be teardown anyway:
`DbSessionUnitOfWork`, which DB-backed tests use, does nothing on exit.

Measured with probes on the middleware, the service and each ASGI send,
Python 3.13.18, median sleep overshoot past the pad's deadline:

| run | valid | invalid | median delta | result |
|---|---|---|---|---|
| isolated | 0.67ms | 1.79ms | −0.98ms | pass, just under tolerance |
| full backend suite ×2 | 0.51–0.52ms | 1.72–1.78ms | −1.20 / −1.21ms | fail on both rounds |
| fixed, full suite ×2 | 0.002ms | 0.002ms | +0.024 / −0.015ms | pass |
| fixed, one shared CPU ×3 | 0.003–0.004ms | 0.003–0.004ms | +0.017 / +0.101 / −0.200ms | pass |

The pad now sleeps to 5ms short of its deadline and yields the rest
(`_sleep_until` in `app/core/middleware.py`). The coarse sleep woke at most
2.36ms late on one shared CPU, so 5ms leaves room. The cost is at most 5ms of
yielding per padded request. `tests/test_constant_time_pad.py` pins the
property: two handlers whose remaining time rounds up to 18 and to 17 must end
together.

This is a production fix, not only a test fix. With the 100ms floor, bucket 87
is hit when a path's work takes 13–14ms. That would have shown about a 1ms
real-versus-decoy difference over HTTP.

The CI step below stays advisory until runs on GitHub's runners show the
delta has gone there too.

Given that, `.github/workflows/backend-tests.yml` marks the three wall-clock
assertions `timing_sensitive` and runs them in a `continue-on-error` step. The
numbers stay visible for anyone investigating, while unrelated PRs stop being
painted red — a check that cries wolf trains people to re-run without reading,
which is how a real regression gets waved through. The strict assertion is kept
where a human is already reading output: a local run, and the full suite on
release-candidate tags (`tests.yml`), which does **not** exclude them.

**A green push is therefore not evidence these converged.** If the advisory step
fails on a run whose control is *not* unusually quiet, investigate rather than
dismiss.

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
