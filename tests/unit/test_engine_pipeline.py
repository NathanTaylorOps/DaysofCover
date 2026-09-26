"""Stage 1, session 7: validation cases 5 and 6.

Both check the per-shipment record shape introduced in
:mod:`daysofcover.engine.pipeline`, which the aggregate day-indexed
pipeline arrays in the Stage 1 spike (:mod:`daysofcover.engine.single_node`)
could not represent: case 5 needs crossing (independent per-order lead
times, not FIFO array slots), case 6 needs each unit's own order day and
sale day.

Both are marked ``validation`` and run in the full workflow, matching
cases 2 and 3 (statistical cross-checks, not exact identities).
"""

from __future__ import annotations

import pytest

from daysofcover.engine.pipeline import lognormal_mean_days, simulate_unit_base_stock_pipeline


@pytest.mark.validation
def test_case_5_palms_theorem_outstanding_orders() -> None:
    """Case 5: Palm's theorem.

    Reference: under base-stock with unit Poisson demand and i.i.d.
    lognormal lead times with crossing allowed, outstanding orders ~
    Poisson(lambda * E[L]). Tolerance: 2%. Only the mean is checked here
    (matching cases 2 and 3's tolerance-on-a-mean shape); the full
    Poisson-distribution claim is the stronger M/G/infinity result behind
    it, not something a 2% budget is meant to certify.

    ``order_up_to`` (60) is chosen generously above the target mean
    outstanding orders (~21) so stockouts stay rare -- this case tests the
    pipeline arithmetic, not backorder recovery.
    """
    lam_per_day = 2.0
    lead_time_median_days = 10.0
    lead_time_sigma = 0.3

    target = lam_per_day * lognormal_mean_days(lead_time_median_days, lead_time_sigma)

    stats = simulate_unit_base_stock_pipeline(
        lam_per_day=lam_per_day,
        lead_time_median_days=lead_time_median_days,
        lead_time_sigma=lead_time_sigma,
        order_up_to=60,
        n_reps=40,
        n_days=3000,
        warmup_days=300,
        seed=2000,
    )

    relative_diff = abs(stats.mean_outstanding_orders - target) / target
    assert relative_diff <= 0.02, (
        f"mean outstanding orders {stats.mean_outstanding_orders:.3f} vs "
        f"lambda*E[L] {target:.3f} (relative diff {relative_diff:.4%}, budget 2%)"
    )


@pytest.mark.validation
def test_case_6_littles_law_on_shipment_pipeline() -> None:
    """Case 6: Little's law on the shipment pipeline.

    Reference: in-transit + on-hand = arrival rate * order-to-receipt
    time, read from per-shipment records. Tolerance: 1%. This is a general
    accounting identity, not a distributional claim, so the tight
    tolerance is really a check on the record-keeping itself (each unit's
    order day and sale day) rather than on any statistical approximation.

    Reuses case 5's simulation and parameters -- this is the other
    reading of the same per-shipment records, not a separate run.
    """
    stats = simulate_unit_base_stock_pipeline(
        lam_per_day=2.0,
        lead_time_median_days=10.0,
        lead_time_sigma=0.3,
        order_up_to=60,
        n_reps=40,
        n_days=3000,
        warmup_days=300,
        seed=2000,
    )

    littles_law_rhs = stats.arrival_rate_per_day * stats.mean_sojourn_days
    relative_diff = abs(stats.mean_pipeline - littles_law_rhs) / stats.mean_pipeline
    assert relative_diff <= 0.01, (
        f"mean pipeline {stats.mean_pipeline:.3f} vs arrival_rate * sojourn "
        f"{littles_law_rhs:.3f} (relative diff {relative_diff:.4%}, budget 1%)"
    )
