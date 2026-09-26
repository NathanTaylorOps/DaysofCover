"""Backlog-driven shipment lag behind production recovery, validation case 13.

The Renesas fire in 2021 is the shape this case is named for: the fab
itself came back online in roughly a month, well ahead of most
forecasts, but the chips customers actually received kept lagging for
much longer, because production recovering is not the same thing as
the backlog of unfilled orders clearing. This module isolates that
one mechanism on its own -- a single queue running at high utilisation
-- deliberately leaving out any production ramp (case 12 already
covers that shape) so the two effects are not conflated.

Production capacity here is a step: zero for ``downtime_days``, then
back to its full rate the instant downtime ends -- "production
recovery" happens on exactly that day. Demand keeps arriving at
``daily_demand`` throughout, unmet demand becomes backlog (not lost
sales, unlike :mod:`daysofcover.engine.ramp`'s case), and once
capacity returns, shipments run flat out at the full rate until the
backlog is gone, only then dropping back to match demand. "Shipment
recovery" is the day that backlog finally clears.

The mechanism is ordinary queueing math: with normal-operations
capacity fixed at ``daily_demand / capacity_utilization``, the queue
only drains at ``capacity - daily_demand`` a day once it is running,
however large ``downtime_days`` was. At high utilisation that
draining rate is small relative to the backlog a short outage can
create, so the closed form below,

    lag_days = downtime_days * capacity_utilization / (1 - capacity_utilization)

grows sharply as utilisation approaches 1 -- the same lever that made
Renesas-style recoveries look so much longer downstream than upstream.
The day-by-day simulation is discrete, so it settles the backlog to
exactly zero one day sooner than this continuous closed form; the
test checks the two agree to within that single day, not exactly.
"""

from __future__ import annotations


def simulate_shipment_recovery(
    *,
    daily_demand: float,
    downtime_days: int,
    capacity_utilization: float,
    n_days: int,
) -> tuple[int, int]:
    """Day-by-day backlog under a step production recovery.

    Returns ``(production_recovery_day, shipment_recovery_day)``:
    the first is always ``downtime_days`` (when capacity returns),
    the second is the first day at or after that on which the backlog
    is fully cleared and shipments once again equal ``daily_demand``.
    Raises :class:`ValueError` if ``n_days`` ends before that happens.
    """
    capacity_full = daily_demand / capacity_utilization
    backlog = 0.0
    shipment_recovery_day: int | None = None

    for day in range(n_days):
        capacity_today = 0.0 if day < downtime_days else capacity_full
        backlog += daily_demand
        shipped_today = min(capacity_today, backlog)
        backlog -= shipped_today
        if day >= downtime_days and backlog <= 1e-9 and shipment_recovery_day is None:
            shipment_recovery_day = day

    if shipment_recovery_day is None:
        raise ValueError(f"backlog had not cleared within n_days={n_days}; raise n_days")

    return downtime_days, shipment_recovery_day


def shipment_recovery_lag_closed_form(
    *, downtime_days: float, capacity_utilization: float
) -> float:
    """Continuous-time days between production and shipment recovery.

    See the module docstring for the derivation: the backlog built up
    over ``downtime_days`` at rate ``daily_demand`` drains at
    ``capacity - daily_demand`` once capacity returns, and the
    ``daily_demand`` terms cancel out of the ratio, so the lag depends
    only on ``downtime_days`` and ``capacity_utilization``, not on the
    demand rate itself.
    """
    return downtime_days * capacity_utilization / (1 - capacity_utilization)
