"""Stage 1 spike validation: cases 1 to 3 (build plan, "Validation cases").

Confirms ADR-008 (own daily-step loop over NumPy state arrays, not SimPy)
before the multi-node engine is built on top of the same shape. Case 1 is
exact (deterministic, no tolerance to spend); cases 2 and 3 are
statistical cross-checks against a published closed form and a published
worked example respectively, so they carry the ``validation`` marker and
run in the full workflow rather than on every push.
"""

from __future__ import annotations

import pytest

from daysofcover.engine.single_node import (
    periodic_base_stock_fill_rate_formula,
    simulate_continuous_base_stock,
    simulate_periodic_order_up_to,
    simulate_periodic_s_S,
)


def test_case_1_continuous_base_stock_deterministic() -> None:
    """Case 1: single node, constant demand, deterministic lead time.

    Reference: analytical steady-state inventory and fill rate. Tolerance:
    exact. With daily demand 10, lead time 5 days and order-up-to 60, the
    pipeline holds 50 units once full, so on-hand settles at exactly 10
    and every order is filled on the day it is placed.
    """
    result = simulate_continuous_base_stock(
        daily_demand=10.0, lead_time_days=5, order_up_to=60.0, n_days=30
    )
    assert result.fill_rate == 1.0
    assert result.ending_on_hand == 10.0


@pytest.mark.validation
def test_case_2_periodic_base_stock_poisson() -> None:
    """Case 2: periodic-review base-stock (R, S), Poisson demand.

    Reference: fill rate = 1 - [E(D_{R+L} - S)+ - E(D_L - S)+] / E(D_R).
    Tolerance: 2% over 2,000 replications.
    """
    lam, review_period_days, lead_time_days, order_up_to = 5.0, 7, 3, 50

    formula = periodic_base_stock_fill_rate_formula(
        lam_per_day=lam,
        review_period_days=review_period_days,
        lead_time_days=lead_time_days,
        order_up_to=order_up_to,
    )
    simulated = simulate_periodic_order_up_to(
        lam_per_day=lam,
        review_period_days=review_period_days,
        lead_time_days=lead_time_days,
        order_up_to=order_up_to,
        n_reps=2000,
        n_days=200,
        warmup_days=40,
        seed=12345,
    )

    assert abs(simulated - formula) <= 0.02, (
        f"simulated fill rate {simulated:.4f} vs formula {formula:.4f} "
        f"(diff {abs(simulated - formula):.4f}, budget 0.02)"
    )


@pytest.mark.validation
def test_case_3_periodic_s_S_discrete_demand() -> None:
    """Case 3: (s, S) with discrete demand.

    Reference: stockpyl's exact discrete (s, S) evaluation (Zheng and
    Federgruen, 1991), named instance: s=4, S=10, holding_cost=1,
    stockout_cost=4, fixed_cost=5, Poisson demand mean 6 -- stockpyl's own
    documented example for ``ss.s_s_cost_discrete``, expected cost
    8.034111561471642 per period. Tolerance: 2%.

    stockpyl itself is not a runtime or test dependency here: the
    reference value is stockpyl's own published worked example for this
    named instance, cited rather than recomputed, so this test has no
    dependency on stockpyl being installable in every environment that
    runs it.
    """
    reference_cost = 8.034111561471642

    simulated_cost = simulate_periodic_s_S(
        reorder_point=4.0,
        order_up_to=10.0,
        holding_cost=1.0,
        stockout_cost=4.0,
        fixed_cost=5.0,
        demand_mean=6.0,
        n_days=200_000,
        warmup_days=1000,
        seed=777,
    )

    relative_diff = abs(simulated_cost - reference_cost) / reference_cost
    assert relative_diff <= 0.02, (
        f"simulated cost {simulated_cost:.4f} vs reference {reference_cost:.4f} "
        f"(relative diff {relative_diff:.4%}, budget 2%)"
    )
