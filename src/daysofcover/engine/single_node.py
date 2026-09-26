"""Stage 1 spike: a single-node daily-step engine, confirming ADR-008.

The build plan calls for a one-session spike -- daily-step loop, one node,
base-stock, validation cases 1 to 3 -- before committing to "own loop over
NumPy state arrays" instead of wrapping SimPy for the real multi-node
engine (state per (node, part): on-hand, on-order, backlog, per-shipment
in-transit records; BOM production; allocation and split rules; a
replication runner with entity-indexed common random numbers). This module
is that spike: three single-node policy simulators, narrow on purpose, that
this session's tests check against three published references. Later
Stage 1 sessions generalise this loop to many nodes and parts; they do not
change its shape, because the point of the spike was to confirm the shape
is right first.

Every simulator is a plain Python/NumPy loop stepping one day at a time --
no event-scheduling framework, no SimPy processes -- because the full
engine's state (on-hand, on-order, backlog, per-shipment in-transit
records) is naturally a set of NumPy arrays indexed by day, and a
process-oriented DES framework would add a layer between that state and
the loop that touches it, for no benefit at this scale (a 40-node,
25-part network, one core, a 200 ms target).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.stats import poisson


@dataclass(frozen=True)
class SingleNodeResult:
    """The two numbers every case in this module is validated against."""

    fill_rate: float
    ending_on_hand: float


def simulate_continuous_base_stock(
    *,
    daily_demand: float,
    lead_time_days: int,
    order_up_to: float,
    n_days: int,
) -> SingleNodeResult:
    """Continuous-review base-stock, deterministic demand and lead time.

    Validation case 1: with constant demand and a deterministic lead time,
    steady-state on-hand inventory is exactly ``order_up_to -
    daily_demand * lead_time_days`` once the pipeline has filled (after
    ``lead_time_days``), and the fill rate is exactly 1.0 whenever
    ``order_up_to >= daily_demand * lead_time_days`` -- there is no
    variability for a stockout to come from. The reference is "exact":
    this is a smoke test on the loop's arithmetic, not a statistical
    comparison.

    Each day orders exactly that day's demand (order-up-to under
    continuous review collapses to "replace what left"), which arrives
    ``lead_time_days`` later.
    """
    on_hand = order_up_to
    pipeline = np.zeros(n_days + lead_time_days + 1)
    total_demand = 0.0
    total_filled = 0.0

    for day in range(n_days):
        on_hand += pipeline[day]
        pipeline[day + lead_time_days] += daily_demand
        filled = min(on_hand, daily_demand)
        on_hand -= daily_demand
        total_demand += daily_demand
        total_filled += filled

    return SingleNodeResult(fill_rate=total_filled / total_demand, ending_on_hand=on_hand)


def poisson_loss(lam: float, k: int) -> float:
    """The Poisson loss function E[(X - k)+] for X ~ Poisson(lam).

    Standard identity: for integer k >= 0,
    E[(X-k)+] = lam * P(X >= k) - k * P(X > k). For k < 0 the threshold is
    never binding, so E[(X-k)+] = E[X-k] = lam - k. Used by
    :func:`periodic_base_stock_fill_rate_formula` below, and by validation
    case 2's test to compute that formula's two loss terms.
    """
    if k < 0:
        return lam - k
    return float(lam * poisson.sf(k - 1, lam) - k * poisson.sf(k, lam))


def periodic_base_stock_fill_rate_formula(
    *,
    lam_per_day: float,
    review_period_days: int,
    lead_time_days: int,
    order_up_to: int,
) -> float:
    """The analytical fill rate for periodic-review (R, S) under Poisson demand.

    Validation case 2's reference: fill rate = 1 - [E(D_{R+L} - S)+ -
    E(D_L - S)+] / E(D_R), with D_x the (Poisson) demand over x days. This
    is the closed-form comparator for
    :func:`simulate_periodic_order_up_to`; it does not itself simulate
    anything.
    """
    lam_r = lam_per_day * review_period_days
    loss_r_plus_l = poisson_loss(lam_per_day * (review_period_days + lead_time_days), order_up_to)
    loss_l = poisson_loss(lam_per_day * lead_time_days, order_up_to)
    return 1 - (loss_r_plus_l - loss_l) / lam_r


def simulate_periodic_order_up_to(
    *,
    lam_per_day: float,
    review_period_days: int,
    lead_time_days: int,
    order_up_to: int,
    n_reps: int,
    n_days: int,
    warmup_days: int,
    seed: int,
) -> float:
    """Periodic-review (R, S), Poisson demand, full backordering.

    Validation case 2: reviewed every ``review_period_days``, inventory
    position (on-hand plus what is already on order) is ordered up to
    ``order_up_to``; unmet demand backorders rather than being lost, and
    is filled once stock arrives. Returns the fill rate -- the fraction of
    demand satisfied from on-hand at the moment it occurs -- pooled across
    ``n_reps`` independent replications and the post-warm-up days of each,
    to compare against :func:`periodic_base_stock_fill_rate_formula`.

    Vectorised across replications (one NumPy array per state), not across
    days -- days are inherently sequential (each day's on-hand depends on
    the last), which is exactly the state-carried-day-to-day shape the
    real multi-node engine needs.
    """
    rng = np.random.default_rng(seed)
    on_hand = np.zeros(n_reps)
    pipeline = np.zeros((n_reps, n_days + lead_time_days + 1))
    total_demand = 0.0
    total_filled = 0.0

    for day in range(n_days):
        on_hand += pipeline[:, day]
        if day % review_period_days == 0:
            outstanding = pipeline[:, day + 1 : day + 1 + lead_time_days].sum(axis=1)
            position = on_hand + outstanding
            pipeline[:, day + lead_time_days] += order_up_to - position
        demand = rng.poisson(lam_per_day, size=n_reps).astype(float)
        filled = np.minimum(np.maximum(on_hand, 0.0), demand)
        on_hand -= demand
        if day >= warmup_days:
            total_demand += float(demand.sum())
            total_filled += float(filled.sum())

    return total_filled / total_demand


def simulate_periodic_s_S(
    *,
    reorder_point: float,
    order_up_to: float,
    holding_cost: float,
    stockout_cost: float,
    fixed_cost: float,
    demand_mean: float,
    n_days: int,
    warmup_days: int,
    seed: int,
) -> float:
    """Zero-lead-time periodic (s, S), Poisson demand, full backordering.

    Validation case 3: reviewed every day; if inventory position is at or
    below ``reorder_point``, order up to ``order_up_to`` (arrives
    instantly -- this matches stockpyl's ``ss.s_s_cost_discrete``, which
    takes no lead time parameter, i.e. the Zheng-Federgruen (1991) model
    it implements is the zero-lead-time case). Cost per period is holding
    cost on positive ending inventory plus stockout cost on backordered
    demand plus the fixed cost on periods an order is placed. Returns the
    average cost per period over the post-warm-up days, to compare
    against stockpyl's exact evaluation.
    """
    rng = np.random.default_rng(seed)
    position = order_up_to
    total_cost = 0.0
    n_counted = 0

    for day in range(n_days):
        ordered = position <= reorder_point
        if ordered:
            position = order_up_to
        demand = float(rng.poisson(demand_mean))
        position -= demand
        cost = (
            holding_cost * max(position, 0.0)
            + stockout_cost * max(-position, 0.0)
            + (fixed_cost if ordered else 0.0)
        )
        if day >= warmup_days:
            total_cost += cost
            n_counted += 1

    return total_cost / n_counted
