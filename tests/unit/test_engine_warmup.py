"""Stage 1: MSER-5 warm-up truncation.

Not a validation case against a published reference number -- MSER-5 is
a heuristic, not an exact formula, so these tests check the two
properties any correct implementation must have (too-short series
truncate to nothing; an obvious transient followed by a flat steady
state gets at least the transient's own batch discarded) rather than a
single hand-computed reference value.
"""

from __future__ import annotations

import numpy as np

from daysofcover.engine.warmup import mser5_truncation_point


def test_a_series_shorter_than_two_batches_truncates_to_zero() -> None:
    assert mser5_truncation_point([1.0, 2.0, 3.0]) == 0
    assert mser5_truncation_point([1.0] * 9) == 0  # 9 // 5 == 1 batch only


def test_a_perfectly_flat_series_discards_nothing() -> None:
    assert mser5_truncation_point([5.0] * 30) == 0


def test_a_decaying_transient_followed_by_a_flat_steady_state_is_discarded() -> None:
    transient = [100.0, 80.0, 60.0, 40.0, 20.0]
    steady = [10.0, 10.1, 9.9, 10.0, 10.1] * 8  # 40 points
    truncation = mser5_truncation_point(transient + steady)

    assert truncation >= 5  # at least the transient's own batch is gone
    assert truncation % 5 == 0  # always a whole number of batches


def test_truncation_point_never_exceeds_a_series_length_minus_two_batches() -> None:
    rng = np.random.default_rng(seed=3)
    series = rng.standard_normal(50).tolist()
    truncation = mser5_truncation_point(series)

    assert 0 <= truncation <= 50 - 2 * 5


def test_a_larger_batch_size_still_returns_a_multiple_of_that_batch_size() -> None:
    rng = np.random.default_rng(seed=4)
    series = [200.0] * 10 + rng.normal(loc=10.0, scale=0.1, size=40).tolist()
    truncation = mser5_truncation_point(series, batch_size=10)

    assert truncation % 10 == 0
