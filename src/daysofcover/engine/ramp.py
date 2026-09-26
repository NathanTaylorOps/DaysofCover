"""Linear capacity ramp after a restart, validation case 12.

A plant that has been down does not, in reality, snap back to full
output the instant it restarts -- staffing back up, requeuing a
production line, clearing a backlog of setup work all take real days.
This module models that with the simplest shape the build plan asks
for: a linear ramp from zero capacity at restart to full capacity
``ramp_days`` later.

Case 12 does not ask this module to match a number -- its tolerance is
"asserted" -- it asks for a *bound*: whatever a linear ramp costs a
site in lost sales, that cost has to sit between two idealised
extremes for the same downtime:

- a step at restart: capacity jumps straight to full the moment the
  plant comes back, the least lost sales a restart of this length
  could possibly cause;
- a step at (restart + ramp): capacity stays at zero for the *entire*
  ramp window and only then jumps to full, the most lost sales the
  same ramp length could cause.

The three capacity profiles below share one demand-served accounting
rule: with no inventory buffer to draw down, a day's sales are capped
at that day's capacity, and whatever demand capacity could not cover
is lost outright (no backorder, no catch-up production). That keeps
the comparison exact rather than reference-noisy: every quantity here
is closed-form arithmetic, not a simulated sample.
"""

from __future__ import annotations


def step_at_restart_capacity(day: int, *, downtime_days: int, daily_demand: float) -> float:
    """Best case: full capacity resumes the instant downtime ends."""
    return 0.0 if day < downtime_days else daily_demand


def step_at_restart_plus_ramp_capacity(
    day: int, *, downtime_days: int, ramp_days: int, daily_demand: float
) -> float:
    """Worst case: capacity stays at zero for the whole ramp window."""
    return 0.0 if day < downtime_days + ramp_days else daily_demand


def linear_ramp_capacity(
    day: int, *, downtime_days: int, ramp_days: int, daily_demand: float
) -> float:
    """The actual shape: capacity climbs linearly over ``ramp_days``.

    Day ``downtime_days`` (the first day back) runs at ``1/ramp_days``
    of full capacity, day ``downtime_days + 1`` at ``2/ramp_days``, and
    so on, reaching full capacity on day ``downtime_days + ramp_days -
    1`` and every day after.
    """
    if day < downtime_days:
        return 0.0
    days_since_restart = day - downtime_days
    if days_since_restart >= ramp_days:
        return daily_demand
    return daily_demand * (days_since_restart + 1) / ramp_days


def _total_lost_sales(*, daily_demand: float, n_days: int, capacity_by_day: list[float]) -> float:
    """Demand capacity could not cover, summed over ``n_days``, days lost outright."""
    return sum(max(daily_demand - capacity_by_day[day], 0.0) for day in range(n_days))


def lost_sales_bounds(
    *, daily_demand: float, downtime_days: int, ramp_days: int, n_days: int
) -> tuple[float, float, float]:
    """Total lost sales for the two bounding profiles and the actual ramp.

    Returns ``(lower, actual, upper)``: ``lower`` is the step-at-restart
    total, ``upper`` is the step-at-(restart + ramp) total, and
    ``actual`` is the linear ramp's own total, which case 12 asks to
    fall strictly between them whenever ``ramp_days >= 1``.
    """
    lower_capacity = [
        step_at_restart_capacity(day, downtime_days=downtime_days, daily_demand=daily_demand)
        for day in range(n_days)
    ]
    actual_capacity = [
        linear_ramp_capacity(
            day, downtime_days=downtime_days, ramp_days=ramp_days, daily_demand=daily_demand
        )
        for day in range(n_days)
    ]
    upper_capacity = [
        step_at_restart_plus_ramp_capacity(
            day, downtime_days=downtime_days, ramp_days=ramp_days, daily_demand=daily_demand
        )
        for day in range(n_days)
    ]

    lower = _total_lost_sales(
        daily_demand=daily_demand, n_days=n_days, capacity_by_day=lower_capacity
    )
    actual = _total_lost_sales(
        daily_demand=daily_demand, n_days=n_days, capacity_by_day=actual_capacity
    )
    upper = _total_lost_sales(
        daily_demand=daily_demand, n_days=n_days, capacity_by_day=upper_capacity
    )
    return lower, actual, upper
