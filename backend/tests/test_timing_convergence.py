"""Tests for the shared latency-convergence assertion (issue #298).

The constant-time auth tests (test_passkey_timing.py, test_invites.py) assert
that two code paths converge in median latency. They did so against a fixed
1ms budget, which sits inside full-suite scheduling noise: measured deltas of
1.02ms-1.10ms failed intermittently on a branch that touched nothing on the
auth path.

The fix is a single assertion helper that calibrates its tolerance against the
measurement noise present in the *same* run: each branch is split in half and
the median delta between its own halves gives a same-path control, whose true
value is zero. Whatever that control shows is pure noise, so the cross-path
delta is judged against a multiple of it -- bounded below by the original 1ms
so a quiet machine keeps a tight bound, and bounded above so the check can
never loosen into uselessness under load.

These are pure-function tests over synthetic sample lists: no DB, no HTTP, no
wall-clock measurement, so they are themselves immune to the flakiness they
exist to fix.
"""

import random

import pytest

from tests.timing_support import (
    SAMPLE_COUNT,
    assert_latency_converges_sampled,
    assert_latency_medians_converge,
    sample_counterbalanced,
)

MS = 0.001


def _noisy(centre_s: float, *, spread_s: float, n: int, seed: int) -> list[float]:
    """n samples around `centre_s`, jittered uniformly by +/- spread_s."""
    rng = random.Random(seed)
    return [rng.uniform(centre_s - spread_s, centre_s + spread_s) for _ in range(n)]


def _bimodal(
    centre_s: float,
    *,
    spread_s: float,
    n: int,
    seed: int,
    slow_fraction: float,
    slow_offset_s: float,
) -> list[float]:
    """n samples where each draw independently takes a slow path.

    Models a conditional slow branch (cache miss, retry, early-return) rather
    than a clean systematic offset: `slow_fraction` of samples are centred at
    `centre_s + slow_offset_s`, the rest at `centre_s`; both groups are then
    jittered uniformly by +/- spread_s. With `slow_fraction` below 0.5 the
    median stays near `centre_s` (the majority group) while the upper tail --
    and therefore p90 once `slow_fraction` exceeds ~0.1 -- absorbs the slow
    group. That is exactly what a median-only, same-path-noise-calibrated
    check is blind to: the leaked branch's own control also widens, because
    the slow/fast split falls independently into each split-half.
    """
    rng = random.Random(seed)
    samples = []
    for _ in range(n):
        this_centre = (
            centre_s + slow_offset_s if rng.random() < slow_fraction else centre_s
        )
        samples.append(rng.uniform(this_centre - spread_s, this_centre + spread_s))
    return samples


def test_identical_samples_converge() -> None:
    """Two branches with no difference at all pass."""
    samples = [0.020] * 31
    assert_latency_medians_converge(samples, list(samples), label_a="a", label_b="b")


def test_quiet_machine_small_delta_converges() -> None:
    """A sub-millisecond delta under low noise passes -- the historical 1ms
    floor is retained as the minimum tolerance."""
    a = _noisy(0.0200, spread_s=0.05 * MS, n=31, seed=1)
    b = _noisy(0.0200 + 0.8 * MS, spread_s=0.05 * MS, n=31, seed=2)

    assert_latency_medians_converge(a, b, label_a="known", label_b="unknown")


def test_scheduling_noise_without_systematic_offset_converges() -> None:
    """Heavy noise with no underlying difference passes.

    This is the flake in issue #298: both branches drawn from the same
    distribution, but noisy enough that the raw median-vs-median delta exceeds
    the old fixed 1ms budget. The self-calibrated tolerance absorbs it.
    """
    a = _noisy(0.020, spread_s=3 * MS, n=31, seed=3)
    b = _noisy(0.020, spread_s=3 * MS, n=31, seed=7)

    assert (
        abs(_median(a) - _median(b)) > 1 * MS
    ), "fixture must reproduce the flake: raw delta should exceed the old 1ms bound"
    assert_latency_medians_converge(a, b, label_a="valid", label_b="invalid")


def test_systematic_offset_on_a_quiet_machine_fails() -> None:
    """The ~2ms signal reported in issue #255 is still caught."""
    a = _noisy(0.0200, spread_s=0.05 * MS, n=31, seed=21)
    b = _noisy(0.0200 + 2 * MS, spread_s=0.05 * MS, n=31, seed=22)

    with pytest.raises(AssertionError):
        assert_latency_medians_converge(a, b, label_a="known", label_b="unknown")


def test_systematic_offset_under_heavy_noise_still_fails() -> None:
    """Noise must not be able to buy unlimited tolerance.

    Without an upper bound, a loaded machine's control delta would scale the
    budget past the very signal the test exists to detect.
    """
    a = _noisy(0.0200, spread_s=3 * MS, n=31, seed=31)
    b = _noisy(0.0200 + 4 * MS, spread_s=3 * MS, n=31, seed=32)

    with pytest.raises(AssertionError):
        assert_latency_medians_converge(a, b, label_a="known", label_b="unknown")


def test_failure_message_reports_delta_control_and_tolerance() -> None:
    """A failure must say why it failed, so a real regression is not mistaken
    for the flake this helper replaced."""
    a = _noisy(0.0200, spread_s=0.05 * MS, n=31, seed=41)
    b = _noisy(0.0200 + 5 * MS, spread_s=0.05 * MS, n=31, seed=42)

    with pytest.raises(AssertionError) as excinfo:
        assert_latency_medians_converge(a, b, label_a="known", label_b="unknown")

    message = str(excinfo.value)
    assert "known" in message and "unknown" in message
    for term in ("delta", "control", "tolerance"):
        assert term in message.lower()


def test_mismatched_or_tiny_sample_sets_are_rejected() -> None:
    """Too few samples cannot support a split-half control, and silently
    accepting them would make the assertion meaningless."""
    with pytest.raises(ValueError):
        assert_latency_medians_converge(
            [0.02] * 3, [0.02] * 3, label_a="a", label_b="b"
        )


def test_near_cap_offset_under_heavy_noise_still_fails() -> None:
    """A leak somewhat *under* the originally-measured ~2.02ms signal must
    still fail even when noise has pushed the tolerance to its ceiling.

    Setting the ceiling at the measured signal rather than below it would let
    a 1.6-1.9ms regression -- the same defect class, merely milder -- ride a
    capped-out tolerance and pass.
    """
    a = _noisy(0.0200, spread_s=1 * MS, n=31, seed=7)
    b = _noisy(0.0200 + 1.7 * MS, spread_s=1 * MS, n=31, seed=8)

    with pytest.raises(AssertionError):
        assert_latency_medians_converge(a, b, label_a="known", label_b="unknown")


@pytest.mark.asyncio
async def test_sampling_alternates_which_branch_goes_first() -> None:
    """Counterbalancing: neither branch may sit permanently in the "first"
    slot, or run-scale drift lands on the two branches at different phases.

    Recording call order rather than durations asserts the discipline itself,
    independently of any timing.
    """
    order: list[str] = []

    async def measure_a() -> float:
        order.append("a")
        return 0.020

    async def measure_b() -> float:
        order.append("b")
        return 0.020

    samples_a, samples_b = await sample_counterbalanced(measure_a, measure_b, count=10)

    assert len(samples_a) == 10 and len(samples_b) == 10
    firsts = [order[i * 2] for i in range(10)]
    assert firsts.count("a") == 5, f"branch order not balanced: {firsts}"
    assert firsts.count("b") == 5, f"branch order not balanced: {firsts}"


@pytest.mark.asyncio
async def test_counterbalancing_cancels_a_linear_drift() -> None:
    """A drift affecting whichever call happens next must not be attributed to
    one branch.

    This is the isolation flake from issue #298 in synthetic form: a steadily
    rising cost per call. Under naive A-then-B interleaving branch B would
    absorb the whole per-iteration increment; alternating cancels it.
    """
    tick = 0.0

    async def drifting() -> float:
        nonlocal tick
        tick += 0.1 * MS
        return 0.020 + tick

    samples_a, samples_b = await sample_counterbalanced(drifting, drifting, count=31)

    assert_latency_medians_converge(
        samples_a, samples_b, label_a="drift a", label_b="drift b"
    )


def test_bimodal_leak_with_convergent_median_is_detected() -> None:
    """A conditional slow path -- not a clean offset -- must still be caught.

    Branch b takes a ~6ms-slower route on ~30% of requests (e.g. a cache
    miss). With slow_fraction well under 0.5 the median sits in the fast
    majority for both branches, so a median-only check sees near-equal
    medians and passes -- exactly the blind spot in issue #306: the leaked
    branch inflates its own split-half control (the slow/fast split falls
    independently into each half), which raises its own tolerance and
    finances the very thing that should fail it. The explicit sub-1ms
    assertion below proves this fixture exercises that blind spot rather than
    the already-covered systematic-offset path.
    """
    a = _noisy(0.0200, spread_s=0.1 * MS, n=31, seed=101)
    b = _bimodal(
        0.0200,
        spread_s=0.1 * MS,
        n=31,
        seed=102,
        slow_fraction=0.3,
        slow_offset_s=6 * MS,
    )

    assert (
        abs(_median(a) - _median(b)) < 1 * MS
    ), "fixture must keep the median-shaped signal below the historical 1ms budget"

    with pytest.raises(AssertionError):
        assert_latency_medians_converge(a, b, label_a="fast-only", label_b="cache-miss")


def test_low_duty_cycle_bimodal_leak_moves_p90_and_is_detected() -> None:
    """A rarer slow path (~20% of requests) must still be caught via the tail.

    A lower duty cycle than the 30% case above, but still far above the ~10%
    needed to pull p90 itself into the slow cluster. Medians are
    near-identical (20% is nowhere near the 50% needed to shift the median),
    so this is only detectable by a statistic that looks at the tail rather
    than the centre.
    """
    a = _noisy(0.0200, spread_s=0.1 * MS, n=31, seed=201)
    b = _bimodal(
        0.0200,
        spread_s=0.1 * MS,
        n=31,
        seed=202,
        slow_fraction=0.2,
        slow_offset_s=8 * MS,
    )

    assert abs(_median(a) - _median(b)) < 1 * MS, "medians must stay near-identical"

    with pytest.raises(AssertionError):
        assert_latency_medians_converge(a, b, label_a="fast-only", label_b="retry-path")


def test_branch_cannot_finance_its_own_tolerance_via_max_control() -> None:
    """A noisy branch must not be allowed to widen the budget it is judged by.

    Branch b is drawn with far more spread than branch a, so its split-half
    control is much wider (~2.3ms vs ~0.08ms here). Taking max() of the two
    controls -- the pre-#306 behaviour -- lets that width buy tolerance up to
    the 1.5ms ceiling, under which the real ~1.4ms cross-path delta slips
    through. Calibrating against min() instead holds the budget to the
    quieter branch's noise floor (~1.0ms here), which the same delta clears.
    Measurement noise is a property of the run and should be common to both
    branches; a branch whose control is far wider than its sibling's is
    showing signal, not shared noise, and must not get to set the bar for
    its own comparison.
    """
    a = _noisy(0.0200, spread_s=0.1 * MS, n=31, seed=301)
    b = _noisy(0.0200 + 1.2 * MS, spread_s=6 * MS, n=31, seed=315)

    with pytest.raises(AssertionError):
        assert_latency_medians_converge(a, b, label_a="known", label_b="unknown")


def test_failure_message_names_the_failing_statistic() -> None:
    """A failure must say WHICH statistic tripped it -- median or tail --
    each with its own delta/control/tolerance, so a bimodal leak is not
    mistaken for a plain offset (or vice versa) when triaging a failure.
    """
    a_median = _noisy(0.0200, spread_s=0.05 * MS, n=31, seed=41)
    b_median = _noisy(0.0200 + 5 * MS, spread_s=0.05 * MS, n=31, seed=42)

    with pytest.raises(AssertionError) as median_excinfo:
        assert_latency_medians_converge(
            a_median, b_median, label_a="known", label_b="unknown"
        )

    median_message = str(median_excinfo.value).lower()
    assert "median" in median_message

    a_tail = _noisy(0.0200, spread_s=0.1 * MS, n=31, seed=101)
    b_tail = _bimodal(
        0.0200,
        spread_s=0.1 * MS,
        n=31,
        seed=102,
        slow_fraction=0.3,
        slow_offset_s=6 * MS,
    )

    with pytest.raises(AssertionError) as tail_excinfo:
        assert_latency_medians_converge(
            a_tail, b_tail, label_a="fast-only", label_b="cache-miss"
        )

    tail_message = str(tail_excinfo.value).lower()
    assert "p90" in tail_message or "tail" in tail_message
    assert tail_message != median_message


def test_symmetric_noise_and_symmetric_bimodal_both_converge() -> None:
    """New checks must not introduce new flakiness.

    Two shapes with no real asymmetry must both still pass: heavy symmetric
    noise on both branches (the original issue #298 flake, unimodal), and a
    conditional slow path present *equally* on both branches (same cache-miss
    behaviour on both sides of the comparison). The second case matters
    specifically for the new tail statistic -- a bimodal distribution is not
    inherently a leak; it only is one when it is asymmetric between branches.
    """
    a_noise = _noisy(0.020, spread_s=3 * MS, n=31, seed=511)
    b_noise = _noisy(0.020, spread_s=3 * MS, n=31, seed=512)
    assert_latency_medians_converge(
        a_noise, b_noise, label_a="valid", label_b="invalid"
    )

    a_bimodal = _bimodal(
        0.0200,
        spread_s=0.1 * MS,
        n=31,
        seed=501,
        slow_fraction=0.3,
        slow_offset_s=6 * MS,
    )
    b_bimodal = _bimodal(
        0.0200,
        spread_s=0.1 * MS,
        n=31,
        seed=502,
        slow_fraction=0.3,
        slow_offset_s=6 * MS,
    )
    assert_latency_medians_converge(
        a_bimodal, b_bimodal, label_a="cache-miss-a", label_b="cache-miss-b"
    )


def _median(values: list[float]) -> float:
    import statistics

    return statistics.median(values)


# ── issue #364: confirm before failing ───────────────────────────────────────


@pytest.mark.asyncio
async def test_sampled_assertion_retries_before_failing_a_one_off_artefact() -> None:
    """A tripping delta that does not reproduce is a harness artefact.

    The module already documents non-reproduction as the artefact fingerprint
    (see `sample_counterbalanced`); issue #364 acts on it. Branch b is 5ms
    slower for the first sampling round only, so the first round trips the
    assertion and the second converges.
    """
    rounds = 0

    async def measure_a() -> float:
        return 0.020

    async def measure_b() -> float:
        nonlocal rounds
        rounds += 1
        return 0.025 if rounds <= SAMPLE_COUNT else 0.020

    await assert_latency_converges_sampled(
        measure_a, measure_b, label_a="valid", label_b="invalid"
    )

    assert (
        rounds == 2 * SAMPLE_COUNT
    ), "a tripped assertion must re-measure exactly once"


@pytest.mark.asyncio
async def test_sampled_assertion_fails_when_the_delta_reproduces() -> None:
    """A real asymmetry is present on every round, so confirming cannot hide
    it -- only the cost of failing doubles."""

    async def measure_a() -> float:
        return 0.020

    async def measure_b() -> float:
        return 0.025

    with pytest.raises(AssertionError) as excinfo:
        await assert_latency_converges_sampled(
            measure_a, measure_b, label_a="known", label_b="unknown"
        )

    message = str(excinfo.value)
    assert "median" in message
    assert "reproduced" in message.lower(), "message must say the delta was confirmed"
    assert "floor" in message.lower(), (
        "a confirmed delta is most often sustained contention overrunning the "
        "constant-time floor, so the message must point the reader there"
    )


def _stream(
    centre_s: float,
    *,
    spread_s: float,
    seed: int,
    slow_fraction: float = 0.0,
    slow_offset_s: float = 0.0,
):
    """A re-callable measure function drawing fresh samples from one seeded
    stream, so each confirmation round sees different draws of the same shape
    while the test as a whole stays deterministic."""
    rng = random.Random(seed)

    async def measure() -> float:
        centre = centre_s
        if slow_fraction and rng.random() < slow_fraction:
            centre += slow_offset_s
        return rng.uniform(centre - spread_s, centre + spread_s)

    return measure


@pytest.mark.asyncio
async def test_systematic_offset_still_fails_through_the_sampled_assertion() -> None:
    """The #255 fixture shape must still fail the assertion the auth tests
    actually call now (issue #364 acceptance).

    The single-round assertion keeps its own coverage above; this is the same
    2ms offset judged through the confirmation path, which is the one
    test_invites.py and test_passkey_timing.py route through.
    """
    with pytest.raises(AssertionError, match="median"):
        await assert_latency_converges_sampled(
            _stream(0.0200, spread_s=0.05 * MS, seed=201),
            _stream(0.0200 + 2 * MS, spread_s=0.05 * MS, seed=202),
            label_a="fast path",
            label_b="slow path",
        )


@pytest.mark.asyncio
async def test_bimodal_leak_still_fails_through_the_sampled_assertion() -> None:
    """A conditional slow branch must survive confirmation too.

    Confirmation squares a detection rate as well as a false-failure rate, so
    the shapes the suite has fixtures for are re-checked through the sampled
    path rather than assumed to carry over from the single-round tests.
    """
    with pytest.raises(AssertionError):
        await assert_latency_converges_sampled(
            _stream(0.0200, spread_s=0.1 * MS, seed=203),
            _stream(
                0.0200,
                spread_s=0.1 * MS,
                seed=204,
                slow_fraction=0.30,
                slow_offset_s=6 * MS,
            ),
            label_a="fast path",
            label_b="leaky path",
        )
