"""Order-pausing disruptions on a base-stock node, validation case 4.

The first disruption mechanic in the engine: a two-state Markov process
that pauses ordering while "down," matching stockpyl's ``DisruptionProcess``
(its default ``disruption_type='OP'``, Order-Pausing -- the disrupted stage
cannot place orders, but nothing already in transit or on the shelf is
affected). This is deliberately the simplest of stockpyl's four disruption
types (``'OP'``, ``'SP'``, ``'TP'``, ``'RP'``); the other three need a
lane and something in transit to pause, which is why they wait for the
multi-node engine and ADR-001's shared-shock hazard groups, not this
single-node validation case.

Reference (stockpyl's own tutorial worked example): deterministic demand
2000/period, holding cost 0.25, stockout cost 3, base-stock 8000,
disruption_probability 0.04, recovery_probability 0.25, 10,000 periods,
zero lead time -- published result, total cost per period 2831.9.

Tolerance for this case is "stated" in the build plan, not a fixed
published percentage, because it has to be: stockpyl's 2831.9 is a single
10,000-period sample of a genuinely noisy process (a pilot run here found
a per-replication standard deviation of roughly 250 against a mean of
roughly 2750 -- about a 9% coefficient of variation), not a closed form or
a citable exact evaluation. Pooling many replications gets *this* engine's
estimate of the true mean to low noise; the single published number stays
irreducibly noisy, so the tolerance has to cover that, not just floating
point wobble. 15% (roughly one and a half standard deviations of stockpyl's
single sample) is stated here as the number the pilot justifies.
"""

from __future__ import annotations

import numpy as np


def _simulate_one_replication(
    *,
    daily_demand: float,
    holding_cost: float,
    stockout_cost: float,
    order_up_to: float,
    disruption_probability: float,
    recovery_probability: float,
    n_periods: int,
    seed: int,
) -> float:
    """One replication's average cost per period.

    Zero lead time, so "order up to S" and "arrives" are the same instant:
    each period, if not disrupted, inventory jumps to ``order_up_to``
    before that period's demand; if disrupted, it carries over unchanged
    (the order that would have refilled it never gets placed). Demand
    then depletes it, and holding/stockout cost is assessed on the
    result, same accounting as case 3's (s, S) model.
    """
    rng = np.random.default_rng(seed)
    disrupted = False
    inventory = order_up_to
    total_cost = 0.0

    for _ in range(n_periods):
        if disrupted:
            if rng.random() < recovery_probability:
                disrupted = False
        elif rng.random() < disruption_probability:
            disrupted = True

        if not disrupted:
            inventory = order_up_to

        inventory -= daily_demand
        total_cost += holding_cost * max(inventory, 0.0) + stockout_cost * max(-inventory, 0.0)

    return total_cost / n_periods


def simulate_order_pausing_base_stock(
    *,
    daily_demand: float,
    holding_cost: float,
    stockout_cost: float,
    order_up_to: float,
    disruption_probability: float,
    recovery_probability: float,
    n_reps: int,
    n_periods: int,
    seed: int,
) -> float:
    """Average cost per period, pooled across ``n_reps`` replications.

    Each replication starts undisrupted with a full base-stock level, on
    the same convention as stockpyl's tutorial example. Pooling many
    replications is what makes this engine's own estimate low-noise; see
    the module docstring for why the *comparison* still needs a generous,
    stated tolerance.
    """
    costs = [
        _simulate_one_replication(
            daily_demand=daily_demand,
            holding_cost=holding_cost,
            stockout_cost=stockout_cost,
            order_up_to=order_up_to,
            disruption_probability=disruption_probability,
            recovery_probability=recovery_probability,
            n_periods=n_periods,
            seed=seed + rep,
        )
        for rep in range(n_reps)
    ]
    return float(np.mean(costs))
