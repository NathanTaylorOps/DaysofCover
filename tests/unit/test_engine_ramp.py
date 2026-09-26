"""Stage 1, session 10: validation case 12.

Unlike every other validation case so far, this one is neither a
statistical estimate nor a single noisy published sample -- it is
closed-form arithmetic on three deterministic capacity profiles, so
the test checks an exact number alongside the qualitative bound. See
:mod:`daysofcover.engine.ramp` for why the three profiles are safe to
compare directly.
"""

from __future__ import annotations

from daysofcover.engine.ramp import lost_sales_bounds


def test_case_12_linear_ramp_lost_sales_between_the_two_step_bounds() -> None:
    """Case 12: Ramp bounds.

    Reference: a linear ramp's lost sales sit strictly between the
    step-at-restart total (least lost sales for this downtime) and the
    step-at-(restart + ramp) total (most lost sales for the same
    downtime and ramp length). Tolerance: asserted.
    """
    daily_demand = 500.0
    downtime_days = 10
    ramp_days = 6
    n_days = 30  # covers downtime + ramp plus a run of full-capacity days after

    lower, actual, upper = lost_sales_bounds(
        daily_demand=daily_demand,
        downtime_days=downtime_days,
        ramp_days=ramp_days,
        n_days=n_days,
    )

    assert lower < actual < upper, (
        f"linear ramp's lost sales ({actual:.2f}) should sit strictly between the "
        f"step-at-restart bound ({lower:.2f}) and the step-at-(restart+ramp) bound "
        f"({upper:.2f})"
    )

    # Each bound and the ramp itself is also exact closed-form arithmetic, not a
    # simulated sample, so pin the actual numbers down too.
    assert lower == downtime_days * daily_demand
    assert upper == (downtime_days + ramp_days) * daily_demand
    assert actual == downtime_days * daily_demand + daily_demand * (ramp_days - 1) / 2


def test_case_12_zero_ramp_collapses_all_three_to_the_same_total() -> None:
    """A zero-length ramp is just a step at restart from every viewpoint.

    With ``ramp_days == 0`` there is no ramp window for the three
    profiles to disagree about, so all three totals must coincide
    exactly, confirming the bound is not an artefact of always giving
    the ramp some width.
    """
    daily_demand = 200.0
    downtime_days = 4
    n_days = 15

    lower, actual, upper = lost_sales_bounds(
        daily_demand=daily_demand,
        downtime_days=downtime_days,
        ramp_days=0,
        n_days=n_days,
    )

    assert lower == actual == upper == downtime_days * daily_demand
