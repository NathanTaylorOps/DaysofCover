"""Stage 1, session 8: validation case 4.

The first test in this suite whose reference is a single noisy sample
rather than a closed form or an exact evaluation -- see
:mod:`daysofcover.engine.disruption` for why its tolerance is wider and
justified by a pilot rather than a published percentage.
"""

from __future__ import annotations

import pytest

from daysofcover.engine.disruption import simulate_order_pausing_base_stock


@pytest.mark.validation
def test_case_4_eoq_base_stock_with_order_pausing_disruptions() -> None:
    """Case 4: EOQ and newsvendor, with and without disruptions.

    Reference: stockpyl's ``DisruptionProcess`` tutorial worked example
    (deterministic demand 2000/period, holding cost 0.25, stockout cost 3,
    base-stock 8000, disruption_probability 0.04, recovery_probability
    0.25, 10,000 periods, zero lead time), published total cost per
    period 2831.9. Tolerance: stated (15%, from a pilot -- see the module
    docstring for the noise budget that justifies it).
    """
    reference_cost = 2831.9

    simulated_cost = simulate_order_pausing_base_stock(
        daily_demand=2000.0,
        holding_cost=0.25,
        stockout_cost=3.0,
        order_up_to=8000.0,
        disruption_probability=0.04,
        recovery_probability=0.25,
        n_reps=200,
        n_periods=10_000,
        seed=3000,
    )

    relative_diff = abs(simulated_cost - reference_cost) / reference_cost
    assert relative_diff <= 0.15, (
        f"simulated cost {simulated_cost:.1f} vs stockpyl's published sample "
        f"{reference_cost:.1f} (relative diff {relative_diff:.4%}, stated budget 15%)"
    )
