"""Stage 1, session 11: validation case 13.

The last of Stage 1's standalone qualitative cases: like case 12, this
is closed-form arithmetic rather than a statistical estimate, but
unlike case 12 the discrete day-by-day simulation and the continuous
closed form disagree by exactly one day at the boundary (see
:mod:`daysofcover.engine.shipment_lag`), so the numeric check allows
that single day rather than demanding an exact match.
"""

from __future__ import annotations

from daysofcover.engine.shipment_lag import (
    shipment_recovery_lag_closed_form,
    simulate_shipment_recovery,
)


def test_case_13_shipment_recovery_lags_production_recovery() -> None:
    """Case 13: Shipment lag.

    Reference: at 90% plant utilisation, a short production outage
    leaves a roughly three-week shipment-recovery lag behind
    production recovery (Renesas-shaped). Tolerance: asserted.
    """
    daily_demand = 900.0
    downtime_days = 2
    capacity_utilization = 0.9

    production_recovery_day, shipment_recovery_day = simulate_shipment_recovery(
        daily_demand=daily_demand,
        downtime_days=downtime_days,
        capacity_utilization=capacity_utilization,
        n_days=200,
    )

    assert production_recovery_day == downtime_days

    lag_days = shipment_recovery_day - production_recovery_day
    assert lag_days > 14, (
        f"a 2-day outage at 90% utilisation should leave shipments lagging "
        f"production by roughly three weeks, not {lag_days} days"
    )

    closed_form_lag = shipment_recovery_lag_closed_form(
        downtime_days=downtime_days, capacity_utilization=capacity_utilization
    )
    # A tiny epsilon on top of the one-day discretisation gap accounts for
    # ordinary floating-point rounding in the division above, not slack in
    # the claim itself.
    assert abs(lag_days - closed_form_lag) <= 1 + 1e-6, (
        f"simulated lag {lag_days} days should be within a day of the closed "
        f"form {closed_form_lag:.2f} days"
    )


def test_case_13_lag_grows_with_utilization_for_the_same_outage() -> None:
    """The Renesas shape: a leaner supply chain lags far more for the same outage.

    Holding the outage length fixed, running closer to full capacity
    (a smaller cushion above demand) must leave a longer shipment
    lag, not a shorter or equal one -- that dependence on utilisation,
    not the outage length itself, is the point of this validation
    case.
    """
    daily_demand = 900.0
    downtime_days = 2

    lags = []
    for capacity_utilization in (0.5, 0.75, 0.9):
        production_recovery_day, shipment_recovery_day = simulate_shipment_recovery(
            daily_demand=daily_demand,
            downtime_days=downtime_days,
            capacity_utilization=capacity_utilization,
            n_days=200,
        )
        lags.append(shipment_recovery_day - production_recovery_day)

    assert lags[0] < lags[1] < lags[2], (
        f"lag should strictly increase with utilisation for the same {downtime_days}-day "
        f"outage, got {lags} for utilisations (0.5, 0.75, 0.9)"
    )
