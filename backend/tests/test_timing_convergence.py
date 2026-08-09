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
    assert_latency_medians_converge,
    sample_counterbalanced,
)

MS = 0.001


def _noisy(centre_s: float, *, spread_s: float, n: int, seed: int) -> list[float]:
    """n samples around `centre_s`, jittered uniformly by +/- spread_s."""
    rng = random.Random(seed)
    return [rng.uniform(centre_s - spread_s, centre_s + spread_s) for _ in range(n)]


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


def _median(values: list[float]) -> float:
    import statistics

    return statistics.median(values)
