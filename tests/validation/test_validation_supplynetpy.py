"""Cross-check against ``SupplyNetPy``: an independent, discrete-event
supply chain simulator, architecturally different from this project's
own daily-step engine.

Session 22, the fifth of the five remaining Engine-milestone items.
``SupplyNetPy`` is SimPy-based and continuous-time (exponential
interarrivals, replenishment triggered the instant inventory position
crosses a threshold), whereas :mod:`daysofcover.engine.single_node` and
the daily-step engine both step in fixed one-day increments -- exactly
the discrete-vs-continuous-time distinction ADR-008 chose *for* this
project and *against* a SimPy-style engine. That difference means this
test cannot compare day-by-day numbers the way the internal validation
cases do; it can only compare a steady-state statistic that inventory
theory predicts for *both* architectures alike.

The statistic chosen is service level (fill rate) for a zero-lead-time
(s, S) policy under Poisson-rate demand: with continuous review and no
lead time, a system replenishes the instant it would otherwise stock
out, so classical inventory theory says the fill rate should be
essentially 1.0 regardless of which simulator computes it -- a
transportation delay is the only thing that could make it fall short.
This is a much looser assertion than the exact-value comparisons cases
1 to 6, 11 to 13 make (see VALIDATION.md), by design: it is checking
that an independently-written, differently-architected simulator agrees
with the same textbook result this project's own engine was validated
against, not reproducing a specific number.

Marked ``validation`` for the same reason as the ``stockpyl`` harness:
it needs ``SupplyNetPy`` installed and runs a long simulation, so it
belongs in the full CI workflow, not the fast local loop.
"""

from __future__ import annotations

import random

import pytest

scm = pytest.importorskip("SupplyNetPy.Components")

pytestmark = pytest.mark.validation

_REORDER_POINT = 10.0
_ORDER_UP_TO = 30.0
_DEMAND_RATE_PER_DAY = 5.0
_SIM_DAYS = 20_000
_SEED = 20260926


def _build_zero_lead_time_ss_network() -> dict[str, object]:
    nodes = [
        {"ID": "S1", "name": "Supplier", "node_type": "infinite_supplier"},
        {
            "ID": "D1",
            "name": "Distributor",
            "node_type": "distributor",
            "capacity": 10_000,
            "initial_level": _ORDER_UP_TO,
            "inventory_holding_cost": 1.0,
            "replenishment_policy": scm.SSReplenishment,
            "policy_param": {"s": _REORDER_POINT, "S": _ORDER_UP_TO},
            "product_buy_price": 1.0,
            "product_sell_price": 1.0,
        },
    ]
    links = [
        {"ID": "L1", "source": "S1", "sink": "D1", "cost": 0.0, "lead_time": lambda: 0.0},
    ]
    demands = [
        {
            "ID": "d1",
            "name": "Demand",
            # A Poisson process at _DEMAND_RATE_PER_DAY per day, one unit per
            # arrival: exponential(rate) interarrival times, discretised to
            # whole days, is exactly the Poisson(rate) demand-per-day process
            # validation case 2 and 3 already use -- the alignment this test
            # relies on, not an approximation of it.
            "order_arrival_model": lambda: random.expovariate(_DEMAND_RATE_PER_DAY),
            "order_quantity_model": lambda: 1,
            "demand_node": "D1",
        },
    ]
    return scm.create_sc_net(nodes, links, demands)  # type: ignore[no-any-return]


def _as_count(value: object) -> float:
    """Normalise a ``get_statistics()`` field to a plain count.

    Some fields (``backorder``, and -- confirmed by this test's own first
    real run -- ``demand_received``/``demand_fulfilled`` too) come back as
    a ``[count, quantity]`` pair rather than a bare number. This scenario's
    order quantity is always 1, so count and quantity coincide; take
    whichever form was actually returned.
    """
    if isinstance(value, (list, tuple)):
        return float(value[0])
    return float(value)  # type: ignore[arg-type]


def test_zero_lead_time_ss_policy_reaches_near_perfect_service_level() -> None:
    random.seed(_SEED)
    net = _build_zero_lead_time_ss_network()
    net = scm.simulate_sc_net(net, sim_time=_SIM_DAYS)

    stats = net["nodes"]["D1"].stats.get_statistics()
    demand_received = _as_count(stats["demand_received"])
    demand_fulfilled = _as_count(stats["demand_fulfilled"])

    assert demand_received > 0  # the simulation actually generated demand
    fill_rate = demand_fulfilled / demand_received

    # Zero lead time, continuous review: theory says this should be
    # essentially perfect. 0.99 leaves headroom for the simulation's own
    # startup transient and any within-day rounding in how SupplyNetPy
    # itself resolves a same-instant replenishment against a same-instant
    # demand arrival, without being loose enough to pass a broken policy.
    assert fill_rate > 0.99
