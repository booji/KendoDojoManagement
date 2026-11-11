"""Noise-calibrated latency comparison for the constant-time auth tests.

Issue #298: asserting a fixed 1ms budget on a median-vs-median latency delta
flakes under full-suite contention, because 1ms is inside the scheduling noise
of a loaded machine -- observed failures were 1.02ms-1.10ms on branches that
touched nothing on the auth path.

The tolerance here is derived from the noise present in the very run being
judged, rather than guessed in advance. Each branch's samples are split into
two interleaved halves and the delta between those halves' statistic is a
*same-path control*: its true value is zero, so whatever it measures is
measurement noise. The cross-path delta is then judged against a multiple of
that control.

Two bounds keep that honest:

* a lower bound (`MIN_TOLERANCE_S`, 1ms) preserves the original strict budget
  on a quiet machine, so the check does not silently relax when it need not;
* an upper bound (`MAX_TOLERANCE_S`, 1.5ms) sits clearly below the ~2.02ms
  delta issue #255 actually measured, so load can never buy enough tolerance
  to hide that signal -- or a milder regression of the same class.

Calibration alone was not sufficient. Sampling order matters too: see
`sample_counterbalanced`, which exists because a fixed A-then-B loop let
run-scale drift masquerade as a cross-path difference.

Issue #306: taking the *noisier* branch's control (as issue #298 originally
did) has a blind spot -- a conditional slow path (cache miss, retry,
early-return) that only a subset of requests take doesn't shift the median
much, but it does inflate that branch's own split-half control, since the
slow/fast split falls independently into each half. The leaked branch then
finances its own tolerance: the very asymmetry that should fail the check
instead widens the budget it is judged against. The fix has two parts:

* a p90 comparison runs alongside the median, with its own split-half
  control and its own (looser) bounds, because a low-duty-cycle conditional
  slow path can leave the median almost untouched while still moving the
  tail. This is what actually closes the #306 gap: a 200,000-trial Monte
  Carlo sweep (`slow_fraction` 5-30%, spread_s=0.1ms) found detection is
  carried almost entirely by the p90 check, whose own false-failure rate at
  the #298 noise level is ~0.07-0.1%;
* the same-path control *may* prefer the quieter of the two branches over
  the noisier one, gated by `CONTROL_RATIO_MIN_ABS_S` -- see that constant
  for why the gate is necessary and what it buys. A first cut of this idea
  (unconditionally discarding the wider control once the ratio passed
  `CONTROL_RATIO_SIGNAL_THRESHOLD`) shipped in #306 without the gate and
  made things worse: two independent Monte Carlo reviews measured its
  false-failure rate at the #298 noise level (±3ms spread, n=31, 20,000+
  trials) at ~6.2-6.4%, *above* the pre-#306 `max()` baseline of ~5.4-5.6%.
  The mechanism turned out to add no measured detection power of its own --
  the p90 check catches every fixture in this suite regardless of which
  control the median comparison picks -- so it is kept only because the
  gated version is a strict improvement on false-failure rate (empirically
  identical to the `max()` baseline) and there is no evidence it hurts;
  drop it in a future revision if that continues to hold and the extra
  moving part isn't earning its keep.

Issue #364: the residual false-failure rate is a *floored-tolerance* effect.
`3 x control` only sets the budget while the control exceeds
`MIN_TOLERANCE_S / 3` (~0.33ms); below that the calibration is switched off
by its own lower bound and the run is judged against a flat 1ms budget its
measured noise had no part in setting. That is where every observed false
failure lived -- controls of 0.08-0.20ms against deltas of 1.12-1.34ms, on
three unrelated branches including `main`. Widening the floor is not
available as a fix: it is the historical #255 budget, and it would eat the
margin `MAX_TOLERANCE_S` deliberately leaves under the ~2.02ms real leak.

So a tripped assertion is instead re-measured from scratch and reported only
if it reproduces -- see `assert_latency_converges_sampled`. A false failure
is a per-run sampling accident and mostly does not recur; a real asymmetry is
present on every run. Measured over 100,000 trials of two branches drawn from
an *identical* distribution at the #298 noise level (+/-3ms spread, n=31):

    rounds required   false-failure rate
    1                 5.503%
    2 (shipped)       0.317%

Detection was measured over 20,000 trials per fixture shape, single round vs.
confirmed:

    #255-class 2.02ms offset, quiet     100.000% -> 100.000%
    1.7ms offset under 1ms noise         98.735% ->  97.380%
    4ms offset under 3ms noise          100.000% -> 100.000%
    bimodal 30% duty cycle, +6ms         99.840% ->  99.725%
    bimodal 20% duty cycle, +8ms         96.055% ->  92.645%
    bimodal 5% duty cycle, +6ms          19.860% ->   3.975%

Everything the suite has a fixture for keeps its detection. The 5%-duty-cycle
row is the honest cost: confirmation roughly squares a detection rate too,
so a shape the check was already mostly blind to (19.9% -- it never had a
fixture, and n=31 cannot see 1-2 slow samples) becomes near-invisible.
Detecting that class wants more samples, not fewer confirmations.

Both figures assume the two rounds are independent, which sustained
contention breaks -- and the direct measurement issue #360 asked for shows
that a load-induced failure is not one this check should suppress anyway.
Sampling the redeem-begin pair over 15 rounds per condition, varying only
the number of tasks contending for the event loop:

    contending tasks   signed median delta   valid slower   control
    0                  +0.001ms              8/15           0.173ms
    1                  -0.019ms              7/15           0.149ms
    2                  +0.005ms              8/15           0.136ms
    4                  +1.514ms              15/15          1.139ms

Unloaded, the delta is nil and its *sign* is a coin flip -- the fingerprint
of a sampling accident, and the regime every observed false failure came
from (quiet controls of 0.08-0.20ms). Under real contention the sign stops
flipping: 15 rounds out of 15 put the valid path ahead, with the middleware
logging `Constant-time floor exceeded ... 169.3ms elapsed vs 20ms floor`
alongside. That is not the harness misreading noise. The real path's work has
overrun `AUTH_BEGIN_MIN_DURATION_MS`, so the constant-time floor is no longer
masking it, and for as long as the load lasts the asymmetry is as visible to
an attacker as it is to the test.

Note which regime the observed false failures came from, because #360 poses
the choice as "inherent to the endpoint, fix at source" versus "load-induced,
make the calibration load-robust" and the answer is neither. The failures had
quiet controls (0.08-0.20ms), and the quiet rows above show no delta to be
robust *to*: at 0-2 contending tasks the median delta is under 0.02ms and its
sign is a coin flip. They are sampling accidents in the tail of that
distribution. The loaded row is a different event -- a true positive that
should fail, since the floor really has stopped masking -- so suppressing it
with a quiet phase or a load term would be suppressing the one reading worth
having. What is left is to separate accident from asymmetry by whether it
recurs, which is what confirmation does.

So confirmation suppresses the accident and keeps the unmasking: the first
has a fresh coin to flip and mostly does not recur, while the second holds
for as long as the machine is busy.

That is the theory. In practice, on GitHub's hosted runners, it has not held:
since confirmation shipped this assertion failed 2 of 6 CI runs, against the
0.317% above. Both failures reproduced across both rounds, so whatever drives
them persists rather than resampling away.

Neither documented mechanism explains the CI case. The most recent had a
same-path control of 0.026ms -- an exceptionally *quiet* run, not a contended
one -- a cross-path delta of 1.317ms, and no `Constant-time floor exceeded`
warning anywhere in the run, so every request finished inside the floor and
both paths should have been padded to the same total. Two hypotheses were
tested and ruled out: the response bodies are byte-identical (1045 bytes for
both paths, so #354's equalisation holds), and the asymmetry is not in the
post-response unit-of-work teardown -- raising the floor from 20ms to 200ms
under identical load collapsed a +3.529ms delta to +0.072ms, which a residual
outside the padded region could not do.

The local contention case is therefore understood and the CI case is not.
Because of that, the per-push CI job reports these assertions rather than
gating on them (`timing_sensitive` marker; see
.github/workflows/backend-tests.yml). The strict assertion is kept where a
human reads the output: a local run, and the full suite on release-candidate
tags. Do not read a green push as evidence these converged. 0.317% is the floor of the achievable
false-failure rate rather than a promise, and a failure that survives both
rounds should be read as "check whether the floor was exceeded", which is
what the assertion message now says.

Note this is not the production defence -- that is the constant-time floor
(`AUTH_BEGIN_MIN_DURATION_MS`), asserted separately by the floor tests. This
assertion guards against asymmetry *above* that floor.
"""

import statistics
from collections.abc import Awaitable, Callable

__all__ = [
    "assert_latency_converges_sampled",
    "assert_latency_medians_converge",
    "sample_counterbalanced",
    "SAMPLE_COUNT",
]

#: Samples to take per branch. Above the previous 15 so the median is less
#: sensitive to a single scheduling outlier, and enough that each split-half
#: control still rests on a meaningful number of points.
SAMPLE_COUNT = 31

#: Multiple of the observed same-path noise allowed for the cross-path delta.
#: Shared between the median and p90 checks -- both bound their tolerance the
#: same number of controls wide; it is the bounds themselves (below) that
#: differ per statistic.
NOISE_MULTIPLIER = 3.0

#: Floor for the median tolerance: the historical fixed budget from issue
#: #255. Below a control of `MIN_TOLERANCE_S / NOISE_MULTIPLIER` this bound
#: rather than the run's own noise sets the budget, which is the regime issue
#: #364's confirmation round exists to cover -- see the module docstring.
MIN_TOLERANCE_S = 0.001

#: Ceiling for the median tolerance. Issue #255 measured the real leak at a
#: median delta of ~2.02ms, so this must sit clearly *below* that rather than
#: at it: a capped-out tolerance must still fail a regression of the same
#: class that happens to land somewhat under the originally-measured figure.
MAX_TOLERANCE_S = 0.0015

#: Bounds for the p90 tolerance (issue #306). A p90 estimate on 31 samples
#: rests on roughly its top 3-4 points, so it swings more per-run than a
#: median does; both bounds sit above the median's for that reason. Chosen
#: empirically so every convergence fixture (including the heavy-noise and
#: linear-drift cases, whose p90 controls run wider than their median
#: controls) still passes, while the bimodal leak fixtures -- whose p90 delta
#: lands at ~5.9-6.3ms, far beyond either bound -- still fail.
P90_MIN_TOLERANCE_S = 0.0015
P90_MAX_TOLERANCE_S = 0.0025

#: Ratio, between one branch's split-half control and its sibling's, above
#: which the wider one is *candidate* to be excluded as that branch's own
#: signal rather than shared run noise (issue #306) -- subject to the
#: `CONTROL_RATIO_MIN_ABS_S` gate below, which decides whether the ratio is
#: trusted at all.
#:
#: 20x was chosen from two fixture fingerprints (~19x for two identical
#: branches, ~30x for a genuine leak) and looked like a clean separation.
#: It was not: a 200,000-trial Monte Carlo over two branches drawn from an
#: *identical* distribution at n=31 found the hi/lo control ratio itself
#: distributes as p50~2.4, p90~12.5, p95~24.9, p99~122, with a tail into the
#: thousands. Pure sampling luck alone clears 20x roughly 6% of the time, so
#: the threshold sits inside the ordinary noise distribution, not past it.
#: The 20x cutoff is kept anyway (it still separates the two fingerprints
#: that motivated it, and raising it further only weakens an already-inert
#: mechanism -- see `CONTROL_RATIO_MIN_ABS_S`), but it is no longer trusted
#: to decide anything on its own.
CONTROL_RATIO_SIGNAL_THRESHOLD = 20.0

#: Absolute floor the *quieter* control must clear before its ratio to the
#: wider one is trusted to discard the wider one (issue #306 fix-round).
#:
#: A ratio computed between two near-zero controls carries no information --
#: dividing noise by noise produces huge, meaningless ratios, and that is
#: exactly what was driving the false-failure regression: at the #298 noise
#: level (±3ms spread, n=31), the quieter-of-the-pair control for two
#: *identical* branches has p10~0.07ms, p25~0.17ms, p50~0.39ms. Below this
#: floor there are not enough real counts backing the control for a 20x
#: separation to mean anything, so the wider (more conservative) control is
#: kept instead, as it was before #306.
#:
#: 0.2ms sits just above the p25 of that quieter-control distribution --
#: enough of the low tail that the ratio mechanism's contribution to the
#: false-failure rate at ±3ms drops to being empirically indistinguishable
#: from the pre-#306 `max()` baseline (100,000-trial Monte Carlo: 5.370% for
#: both, versus 6.193% for the ungated ratio). Detection of the bimodal leak
#: fixtures (5-30% duty cycle) was unaffected in the same sweep -- it never
#: depended on this control in the first place; see the module docstring.
CONTROL_RATIO_MIN_ABS_S = 0.0002

#: Independent sampling rounds a tripped assertion must survive before it is
#: reported as a failure (issue #364). See `assert_latency_converges_sampled`.
CONFIRMATION_ATTEMPTS = 2

#: Fewest samples per branch that can support a split-half control.
_MIN_SAMPLES = 8


async def sample_counterbalanced(
    measure_a: Callable[[], Awaitable[float]],
    measure_b: Callable[[], Awaitable[float]],
    *,
    count: int = SAMPLE_COUNT,
) -> tuple[list[float], list[float]]:
    """Sample two branches, alternating which one is measured first.

    Naive interleaving (always A then B within each iteration) pins one branch
    permanently in the "first" slot. Any drift over the run -- cache warming,
    CPU frequency scaling, a slow oscillation in host load -- then lands on the
    two branches at different phases and shows up as a delta that no amount of
    sampling will average away, because it is systematic in the *ordering*, not
    random.

    That is not hypothetical: on an idle machine, runs of the naive loop
    produced a ~1.1ms cross-path delta against a ~0.1ms same-path control, in
    both the passkey and invite tests at once, roughly one run in three (issue
    #298 QA). A delta ten times the noise floor that fails to reproduce on the
    next run is an artefact of the harness, not of the code under test.

    Swapping the order every iteration (ABBA) cancels that first-order drift:
    each branch spends half its samples first and half second.

    Args:
        measure_a, measure_b: awaitables returning one wall-clock duration in
            seconds for their respective branch.
        count: samples to collect per branch.

    Returns:
        (samples_a, samples_b), each of length `count`.
    """
    samples_a: list[float] = []
    samples_b: list[float] = []

    for index in range(count):
        if index % 2 == 0:
            samples_a.append(await measure_a())
            samples_b.append(await measure_b())
        else:
            samples_b.append(await measure_b())
            samples_a.append(await measure_a())

    return samples_a, samples_b


def _percentile_90(samples: list[float]) -> float:
    """The 90th percentile of one branch's samples."""
    return statistics.quantiles(samples, n=100)[89]


def _split_half_control(
    samples: list[float], statistic: Callable[[list[float]], float]
) -> float:
    """`statistic` delta between two interleaved halves of one branch's
    samples.

    Both halves come from the same code path, so the true delta is zero and
    the result is a direct read on this run's measurement noise. Splitting by
    odd/even index rather than front/back keeps warm-up and drift spread
    evenly across both halves.

    Under `sample_counterbalanced`, index parity within a branch also tracks
    whether that sample was taken first or second in its iteration -- so this
    additionally picks up any residual ordering bias. That biases the control
    slightly high while the cross-path delta has the same bias cancelled out,
    which errs toward tolerating noise rather than toward false confidence.
    """
    return abs(statistic(samples[0::2]) - statistic(samples[1::2]))


def _same_path_control(control_a: float, control_b: float) -> float:
    """Pick the same-path control to calibrate against from a branch pair.

    Defaults to the wider (more conservative) of the two controls. It is
    only replaced by the quieter one when both `CONTROL_RATIO_MIN_ABS_S` and
    `CONTROL_RATIO_SIGNAL_THRESHOLD` agree that the wider control looks like
    the branch's own signal rather than shared run noise: the quieter
    control must itself be large enough to make a ratio meaningful (the
    absolute-floor gate -- see that constant for why this is necessary), and
    only then does a wide ratio count as evidence (the threshold gate).
    """
    lo, hi = (
        (control_a, control_b) if control_a <= control_b else (control_b, control_a)
    )
    if lo >= CONTROL_RATIO_MIN_ABS_S and hi / lo > CONTROL_RATIO_SIGNAL_THRESHOLD:
        return lo
    return hi


def _check_statistic(
    name: str,
    statistic: Callable[[list[float]], float],
    samples_a: list[float],
    samples_b: list[float],
    *,
    min_tolerance: float,
    max_tolerance: float,
    label_a: str,
    label_b: str,
) -> str | None:
    """Compare one statistic across branches; return a failure message, or
    None if it converges."""
    delta = abs(statistic(samples_a) - statistic(samples_b))
    control = _same_path_control(
        _split_half_control(samples_a, statistic),
        _split_half_control(samples_b, statistic),
    )
    tolerance = min(max(NOISE_MULTIPLIER * control, min_tolerance), max_tolerance)

    if delta < tolerance:
        return None

    return (
        f"{name} latency delta between {label_a!r} and {label_b!r} exceeds run "
        f"noise: {name} delta={delta * 1000:.3f}ms, same-path control="
        f"{control * 1000:.3f}ms, tolerance={tolerance * 1000:.3f}ms "
        f"(n={len(samples_a)}/{len(samples_b)}). A {name} delta this far above "
        f"the control suggests a real timing side channel, not scheduling noise."
    )


def _first_failure(
    samples_a: list[float],
    samples_b: list[float],
    *,
    label_a: str,
    label_b: str,
) -> None:
    """Assert two code paths show no latency difference beyond run noise.

    Checks both the median and the p90 (issue #306): a conditional slow path
    taken by only a minority of requests can leave the median all but
    unmoved while still shifting the tail, so a median-only comparison is
    blind to it.

    Args:
        samples_a, samples_b: per-request wall-clock durations in seconds,
            gathered interleaved so neither branch absorbs warm-up skew.
        label_a, label_b: branch names, used in the failure message.

    Raises:
        ValueError: if either branch has too few samples to calibrate against.
        AssertionError: if the median or the p90 cross-path delta exceeds its
            calibrated tolerance. The message names which statistic tripped
            it.
    """
    if len(samples_a) < _MIN_SAMPLES or len(samples_b) < _MIN_SAMPLES:
        raise ValueError(
            f"need at least {_MIN_SAMPLES} samples per branch to calibrate "
            f"against run noise; got {len(samples_a)} and {len(samples_b)}"
        )

    failure = _check_statistic(
        "median",
        statistics.median,
        samples_a,
        samples_b,
        min_tolerance=MIN_TOLERANCE_S,
        max_tolerance=MAX_TOLERANCE_S,
        label_a=label_a,
        label_b=label_b,
    ) or _check_statistic(
        "p90",
        _percentile_90,
        samples_a,
        samples_b,
        min_tolerance=P90_MIN_TOLERANCE_S,
        max_tolerance=P90_MAX_TOLERANCE_S,
        label_a=label_a,
        label_b=label_b,
    )

    return failure


def assert_latency_medians_converge(
    samples_a: list[float],
    samples_b: list[float],
    *,
    label_a: str,
    label_b: str,
) -> None:
    """Assert one already-collected sample pair converges.

    Judges the samples it is given and nothing more. Where the samples can be
    re-collected, prefer `assert_latency_converges_sampled`, which confirms a
    tripped assertion against a fresh run before failing (issue #364).
    """
    failure = _first_failure(samples_a, samples_b, label_a=label_a, label_b=label_b)
    assert failure is None, failure


async def assert_latency_converges_sampled(
    measure_a: Callable[[], Awaitable[float]],
    measure_b: Callable[[], Awaitable[float]],
    *,
    label_a: str,
    label_b: str,
    count: int = SAMPLE_COUNT,
    attempts: int = CONFIRMATION_ATTEMPTS,
) -> None:
    """Sample two branches and assert they converge, confirming any failure.

    Issue #364: the calibrated tolerance is floored at `MIN_TOLERANCE_S`, so
    on a run whose measured noise falls below `MIN_TOLERANCE_S / 3` the
    calibration is switched off by its own lower bound and the run is judged
    against a flat budget its own noise had no part in setting. That regime
    is where the residual ~5% false-failure rate lives, and it is common:
    every observed false failure had a control of 0.08-0.20ms.

    Rather than trade the floor's sensitivity for quiet, a tripped assertion
    is re-measured from scratch and fails only if it reproduces. A false
    failure is a per-run sampling accident, so the rate falls roughly as its
    own square; a real asymmetry is present on every run and reproduces by
    construction. See the module docstring for the measured figures.

    Args:
        measure_a, measure_b: awaitables returning one wall-clock duration in
            seconds for their respective branch, callable repeatedly.
        label_a, label_b: branch names, used in the failure message.
        count: samples per branch per attempt.
        attempts: independent sampling rounds a failure must survive.

    Raises:
        AssertionError: if the same statistic exceeds its calibrated tolerance
            on every attempt.
    """
    for attempt in range(1, attempts + 1):
        samples_a, samples_b = await sample_counterbalanced(
            measure_a, measure_b, count=count
        )
        failure = _first_failure(samples_a, samples_b, label_a=label_a, label_b=label_b)
        if failure is None:
            return

    raise AssertionError(
        f"{failure} Reproduced on {attempts} independent sampling rounds, so "
        f"this is not the per-run sampling accident described in issue #364; "
        f"the figures above are from the final round. First check the captured "
        f"log for 'Constant-time floor exceeded': under sustained contention "
        f"the real path overruns AUTH_BEGIN_MIN_DURATION_MS and the floor "
        f"stops masking it, which reproduces exactly like a code-level "
        f"asymmetry because while the load lasts it is one. If that warning "
        f"is ABSENT and the control above is small, first check that the pad "
        f"still ends at its deadline (tests/test_constant_time_pad.py, #596): "
        f"a pad whose wake-up depends on the time left to pad produced exactly "
        f"this shape. If it does, report the figures in "
        f"docs/auth-timing-calibration.md rather than assuming either a leak "
        f"or a flake."
    )
