"""Cross-check against ``stockpyl``: an established, independently-written
inventory library, not just this project's own analytical formulas.

Session 22, the fourth of the five remaining Engine-milestone items.
Validation case 3 (:func:`daysofcover.engine.single_node.
simulate_periodic_s_S`) already has an internal reference --
Zheng-Federgruen's own exact cost formula, hand-derived in that module's
docstring math. This test compares the *same* simulation against
``stockpyl``'s own implementation of that exact formula
(``stockpyl.ss.s_s_cost_discrete``) instead, so a bug shared between our
formula and our simulation (both written by the same person, in the same
session) would not silently pass both checks at once -- an independent
library's number is a genuinely different reference.

Marked ``validation`` (the marker already registered in
``pyproject.toml`` for exactly this purpose) rather than left to run by
default: it needs ``stockpyl`` installed, and it runs a long simulation
for the statistical comparison to tighten enough to be meaningful, so it
belongs in the full CI workflow, not the fast local loop.
"""

from __future__ import annotations

import pytest

from daysofcover.engine.single_node import simulate_periodic_s_S

stockpyl_ss = pytest.importorskip("stockpyl.ss")

pytestmark = pytest.mark.validation

# Zheng-Federgruen parameters shared between the simulation and the exact
# reference -- zero lead time, matching stockpyl's own s_s_cost_discrete
# (it takes no lead-time parameter at all).
_REORDER_POINT = 10.0
_ORDER_UP_TO = 30.0
_HOLDING_COST = 1.0
_STOCKOUT_COST = 9.0
_FIXED_COST = 20.0
_DEMAND_MEAN = 5.0

# A long enough horizon, with a generous warm-up, for the simulation's
# per-period average cost to converge close to the analytic steady-state
# value -- this is a statistical comparison (simulation vs. exact), not
# an exact-equality one, so the tolerance below is a percentage of the
# reference cost, not a numerical-precision epsilon.
_N_DAYS = 200_000
_WARMUP_DAYS = 2_000
_SEED = 20260926
_RELATIVE_TOLERANCE = 0.03


def test_periodic_s_S_average_cost_matches_stockpyl_within_tolerance() -> None:
    exact_cost = stockpyl_ss.s_s_cost_discrete(
        reorder_point=_REORDER_POINT,
        order_up_to_level=_ORDER_UP_TO,
        holding_cost=_HOLDING_COST,
        stockout_cost=_STOCKOUT_COST,
        fixed_cost=_FIXED_COST,
        use_poisson=True,
        demand_mean=_DEMAND_MEAN,
    )

    simulated_cost = simulate_periodic_s_S(
        reorder_point=_REORDER_POINT,
        order_up_to=_ORDER_UP_TO,
        holding_cost=_HOLDING_COST,
        stockout_cost=_STOCKOUT_COST,
        fixed_cost=_FIXED_COST,
        demand_mean=_DEMAND_MEAN,
        n_days=_N_DAYS,
        warmup_days=_WARMUP_DAYS,
        seed=_SEED,
    )

    assert simulated_cost == pytest.approx(exact_cost, rel=_RELATIVE_TOLERANCE)
