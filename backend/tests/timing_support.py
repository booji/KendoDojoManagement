"""Noise-calibrated latency comparison for the constant-time auth tests.

Issue #298: asserting a fixed 1ms budget on a median-vs-median latency delta
flakes under full-suite contention, because 1ms is inside the scheduling noise
of a loaded machine -- observed failures were 1.02ms-1.10ms on branches that
touched nothing on the auth path.

The tolerance here is derived from the noise present in the very run being
judged, rather than guessed in advance. Each branch's samples are split into
two interleaved halves and the delta between those halves' medians is a
*same-path control*: its true value is zero, so whatever it measures is
measurement noise. The cross-path delta is then judged against a multiple of
the noisier branch's control.

Two bounds keep that honest:

* a lower bound (`MIN_TOLERANCE_S`, 1ms) preserves the original strict budget
  on a quiet machine, so the check does not silently relax when it need not;
* an upper bound (`MAX_TOLERANCE_S`, 2ms) means load can never buy enough
  tolerance to hide the ~2ms signal issue #255 was filed about.

Note this is not the production defence -- that is the constant-time floor
(`AUTH_BEGIN_MIN_DURATION_MS`), asserted separately by the floor tests. This
assertion guards against asymmetry *above* that floor.
"""

import statistics

__all__ = ["assert_latency_medians_converge", "SAMPLE_COUNT"]

#: Samples to take per branch. Above the previous 15 so the median is less
#: sensitive to a single scheduling outlier, and enough that each split-half
#: control still rests on a meaningful number of points.
SAMPLE_COUNT = 31

#: Multiple of the observed same-path noise allowed for the cross-path delta.
NOISE_MULTIPLIER = 3.0

#: Floor for the tolerance: the historical fixed budget from issue #255.
MIN_TOLERANCE_S = 0.001

#: Ceiling for the tolerance: below the ~2ms leak the constant-time floor was
#: introduced to close, so no amount of noise can excuse that signal.
MAX_TOLERANCE_S = 0.002

#: Fewest samples per branch that can support a split-half control.
_MIN_SAMPLES = 8


def _split_half_control(samples: list[float]) -> float:
    """Median delta between two interleaved halves of one branch's samples.

    Both halves come from the same code path, so the true delta is zero and
    the result is a direct read on this run's measurement noise. Interleaving
    (odd/even index) rather than splitting front/back keeps warm-up and drift
    spread evenly across both halves.
    """
    return abs(statistics.median(samples[0::2]) - statistics.median(samples[1::2]))


def assert_latency_medians_converge(
    samples_a: list[float],
    samples_b: list[float],
    *,
    label_a: str,
    label_b: str,
) -> None:
    """Assert two code paths show no latency difference beyond run noise.

    Args:
        samples_a, samples_b: per-request wall-clock durations in seconds,
            gathered interleaved so neither branch absorbs warm-up skew.
        label_a, label_b: branch names, used in the failure message.

    Raises:
        ValueError: if either branch has too few samples to calibrate against.
        AssertionError: if the cross-path delta exceeds the calibrated
            tolerance.
    """
    if len(samples_a) < _MIN_SAMPLES or len(samples_b) < _MIN_SAMPLES:
        raise ValueError(
            f"need at least {_MIN_SAMPLES} samples per branch to calibrate "
            f"against run noise; got {len(samples_a)} and {len(samples_b)}"
        )

    delta = abs(statistics.median(samples_a) - statistics.median(samples_b))
    control = max(_split_half_control(samples_a), _split_half_control(samples_b))
    tolerance = min(max(NOISE_MULTIPLIER * control, MIN_TOLERANCE_S), MAX_TOLERANCE_S)

    assert delta < tolerance, (
        f"latency delta between {label_a!r} and {label_b!r} exceeds run noise: "
        f"delta={delta * 1000:.3f}ms, same-path control={control * 1000:.3f}ms, "
        f"tolerance={tolerance * 1000:.3f}ms "
        f"(n={len(samples_a)}/{len(samples_b)}). A delta this far above the "
        f"control suggests a real timing side channel, not scheduling noise."
    )
