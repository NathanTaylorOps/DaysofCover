"""Validation cases 7 and 8: the aggregate cover and impact LPs against a
hand-computed answer, and against the real multi-node DES engine.

Case 7 ("serial three-node chain, one node removed") needs nothing but
arithmetic: remove the first node of a three-node chain and the last
node's cover collapses to its own on-hand over its own demand rate,
since nothing else can ever reach it again. Case 8 ("DES equals LP")
runs the real engine (:mod:`daysofcover.engine.daily_step`) day by day
under conditions chosen so nothing in the DES's own mechanics -- lead
times, production timing, backlog accounting -- can introduce a gap
against the LP's aggregate, volume-only view: deterministic demand and
lead times, one path per part (no branching-split ambiguity), and,
critically, the *only* finished goods ever available during the
disrupted window are exactly what :func:`daysofcover.lp.aggregate.
starting_inventory_from_state` reads off the DES state at the moment
the disruption starts (on-hand at the customer, plus one shipment
already in transit toward it) -- nothing new is ever produced or
pushed during the window, because the disrupted element is the
customer's own inbound component lane, so the plant never gets more
part-a to turn into more sku-a. That is what makes an *exact* match
possible without reconciling in-flight timing case by case.

Buffer, the weekly time-indexed bisection variant, the AND/OR
structural screen and case 9's DES-vs-LP gap reporting are later Stage
2 work -- see :mod:`daysofcover.lp.aggregate`'s own module docstring.
"""

from __future__ import annotations

import numpy as np
import pytest

from daysofcover.engine.allocation import CustomerOrder
from daysofcover.engine.daily_step import SkuProductionSpec, advance_one_day
from daysofcover.engine.disruption_state import DisruptionState
from daysofcover.engine.distribution import build_distribution_tree
from daysofcover.engine.production import ProductionQueue
from daysofcover.engine.shipments import NetworkShipments
from daysofcover.engine.state import NetworkState
from daysofcover.lp.aggregate import (
    sku_key,
    solve_cover,
    solve_impact,
    starting_inventory_from_state,
)
from daysofcover.models.network import (
    SKU,
    BOMLine,
    Customer,
    Lane,
    LaneMode,
    Network,
    Node,
    NodeType,
    Part,
    SeasonalDemandProfile,
    SupplySource,
)
from daysofcover.models.scenario import Disruption, Scenario


def _seasonal_profile(*, base_weekly_rate: float) -> SeasonalDemandProfile:
    return SeasonalDemandProfile(
        base_weekly_rate=base_weekly_rate, weekly_multipliers=[1.0] * 52, dispersion=1.0
    )


def _case_7_network() -> Network:
    """n1 (removed) -> n2 (empty pass-through) -> n3 (customer, holds its own stock)."""
    n1 = Node(id="n1", name="Plant", type=NodeType.PLANT, region="AU")
    n2 = Node(id="n2", name="DC", type=NodeType.DC, region="AU")
    n3 = Node(id="n3", name="Customer", type=NodeType.CUSTOMER, region="AU")
    lane_12 = Lane(
        id="lane-12",
        origin_id="n1",
        destination_id="n2",
        mode=LaneMode.ROAD,
        lead_time_days_median=1.0,
        lead_time_days_sigma=0.0,
        capacity_per_week=1000.0,
        unit_cost=1.0,
        currency="AUD",
    )
    lane_23 = Lane(
        id="lane-23",
        origin_id="n2",
        destination_id="n3",
        mode=LaneMode.ROAD,
        lead_time_days_median=1.0,
        lead_time_days_sigma=0.0,
        capacity_per_week=1000.0,
        unit_cost=1.0,
        currency="AUD",
    )
    part_a = Part(
        id="part-a",
        name="Part A",
        suppliers=[SupplySource(node_id="n1", split_ratio=1.0)],
        unit_cost=1.0,
        currency="AUD",
    )
    sku_a = SKU(
        id="sku-a",
        name="SKU A",
        price={"AUD": 100.0},
        margin_fraction=0.5,
        currency="AUD",
        bom=[BOMLine(part_id="part-a", quantity=1.0)],
        production_lead_time_days=3.0,
        batch_size=1.0,
    )
    customer = Customer(
        id="n3",
        name="Customer",
        demand={"sku-a": _seasonal_profile(base_weekly_rate=70.0)},  # 10.0/day
        backlog_window_days=30,
        allocation_priority=0,
    )
    return Network(
        base_currency="AUD",
        nodes=[n1, n2, n3],
        lanes=[lane_12, lane_23],
        parts=[part_a],
        skus=[sku_a],
        customers=[customer],
    )


def test_cover_equals_hand_computed_runway_case_7() -> None:
    network = _case_7_network()
    # n3's own 50 units, at 10/day demand: cover = 50 / 10 = 5.0 days,
    # exactly -- nothing n2 or the removed n1 does can change that,
    # since n1's removal leaves n2 with nothing to forward at all.
    starting_inventory = {("n3", sku_key("sku-a")): 50.0}

    result = solve_cover(network, removed_element_id="n1", starting_inventory=starting_inventory)

    assert result.status == "optimal"
    assert result.cover_days == 5.0


def test_impact_beyond_the_cover_horizon_is_the_hand_computed_shortfall_case_7() -> None:
    network = _case_7_network()
    starting_inventory = {("n3", sku_key("sku-a")): 50.0}

    # at T=10 days, demand is 100 units, only 50 are ever available:
    # 50 units lost, at a margin of 100.0 * 0.5 = 50.0 each.
    result = solve_impact(
        network,
        removed_element_id="n1",
        horizon_days=10.0,
        starting_inventory=starting_inventory,
    )

    assert result.status == "optimal"
    assert result.lost_sales_by_customer_sku[("n3", "sku-a")] == 50.0
    assert result.total_impact == 50.0 * 50.0


def _case_8_network() -> Network:
    """supplier-1 -> plant-1 -> cust-1, the inbound component lane disrupted."""
    supplier = Node(id="supplier-1", name="Supplier", type=NodeType.SUPPLIER, region="AU")
    plant = Node(id="plant-1", name="Plant", type=NodeType.PLANT, region="AU")
    customer_node = Node(id="cust-1", name="Customer", type=NodeType.CUSTOMER, region="AU")
    lane_in = Lane(
        id="lane-in",
        origin_id="supplier-1",
        destination_id="plant-1",
        mode=LaneMode.OCEAN,
        lead_time_days_median=2.0,
        lead_time_days_sigma=0.0,
        capacity_per_week=1000.0,
        unit_cost=1.0,
        currency="AUD",
    )
    lane_dist = Lane(
        id="lane-dist",
        origin_id="plant-1",
        destination_id="cust-1",
        mode=LaneMode.ROAD,
        lead_time_days_median=1.0,
        lead_time_days_sigma=0.0,
        capacity_per_week=1000.0,
        unit_cost=1.0,
        currency="AUD",
    )
    part_a = Part(
        id="part-a",
        name="Part A",
        suppliers=[SupplySource(node_id="supplier-1", split_ratio=1.0)],
        unit_cost=1.0,
        currency="AUD",
    )
    sku_a = SKU(
        id="sku-a",
        name="SKU A",
        price={"AUD": 100.0},
        margin_fraction=0.4,
        currency="AUD",
        bom=[BOMLine(part_id="part-a", quantity=1.0)],
        production_lead_time_days=3.0,
        batch_size=1.0,
    )
    customer = Customer(
        id="cust-1",
        name="Customer",
        demand={"sku-a": _seasonal_profile(base_weekly_rate=70.0)},  # 10.0/day
        backlog_window_days=30,
        allocation_priority=0,
    )
    return Network(
        base_currency="AUD",
        nodes=[supplier, plant, customer_node],
        lanes=[lane_in, lane_dist],
        parts=[part_a],
        skus=[sku_a],
        customers=[customer],
    )


def _run_case_8_des(
    *, horizon_days: int
) -> tuple[NetworkState, dict[tuple[str, tuple[str, str]], float]]:
    """Set up the case 8 network, snapshot r at disruption start, then run the DES.

    Returns the final state (for reading cumulative backlog) and the
    ``starting_inventory`` snapshot the LP solves are compared against.
    """
    network = _case_8_network()
    state = NetworkState.from_network(network)
    shipments = NetworkShipments.from_network(network)
    tree = build_distribution_tree(network, plant_node_id="plant-1")
    rng = np.random.default_rng(seed=1)

    cust = state.node_index("cust-1")
    sku_idx = state.sku_index("sku-a")
    # 20 units already on cust-1's own shelf...
    state.finished_on_hand[cust, sku_idx] = 20.0
    # ...plus one shipment already in transit, dispatched "yesterday"
    # (order_day=-1) on a 1-day deterministic lane, landing day 0 --
    # exactly the "including in-transit" half of the LP's r.
    shipments.ship(lane_id="lane-dist", part_id="sku-a", quantity=10.0, order_day=-1, rng=rng)

    # snapshot r *before* running a single day -- this is the moment
    # the disruption starts, per the build plan's own words.
    starting_inventory = starting_inventory_from_state(state=state, shipments=shipments)

    disruption = Disruption(
        element_id="lane-in",
        start_day=0,
        severity_fraction=1.0,
        duration_days=horizon_days,
        ramp_days=0,  # a clean step, matching the LP's binary loss factor
    )
    scenario = Scenario(id="s1", name="Component cutoff", disruptions=[disruption], seed=1)
    disruption_state = DisruptionState.from_scenario(scenario, network=network)

    for day in range(horizon_days):
        spec = SkuProductionSpec(
            finished_sku_id="sku-a",
            bom=[BOMLine(part_id="part-a", quantity=1.0)],
            capacity_per_week=7_000.0,
            batch_size=1.0,
            production_lead_time_days=3.0,
            orders=[CustomerOrder(customer_id="cust-1", order_day=day, quantity=10.0, priority=0)],
            production_queue=ProductionQueue(),
        )
        advance_one_day(
            state=state,
            shipments=shipments,
            plant_node_id="plant-1",
            component_part_id="part-a",
            inbound_lane_id="lane-in",
            sku_specs=[spec],
            current_day=day,
            rng=rng,
            distribution=tree,
            disruption_state=disruption_state,
        )

    return state, starting_inventory


def test_des_agrees_with_lp_cover_under_case_8_conditions() -> None:
    network = _case_8_network()
    _state, starting_inventory = _run_case_8_des(horizon_days=1)

    # 20 on cust-1's own shelf + the 10 already in transit = 30 units,
    # at 10/day: cover = 3.0 days exactly.
    result = solve_cover(
        network, removed_element_id="lane-in", starting_inventory=starting_inventory
    )
    assert result.status == "optimal"
    assert result.cover_days == 3.0


def test_des_sales_lost_equals_lp_impact_lost_sales_case_8() -> None:
    horizon_days = 5
    state, starting_inventory = _run_case_8_des(horizon_days=horizon_days)
    network = _case_8_network()

    cust = state.node_index("cust-1")
    sku_idx = state.sku_index("sku-a")
    # 5 days at 10/day = 50 demanded; only 30 units were ever available
    # (nothing new arrives -- the component lane is cut, so the plant
    # never produces more): 20 units go unmet, landing entirely in
    # cust-1's own backlog since nothing ever repays it during the window.
    des_lost_sales = float(state.finished_backlog[cust, sku_idx])
    assert des_lost_sales == 20.0

    impact = solve_impact(
        network,
        removed_element_id="lane-in",
        horizon_days=float(horizon_days),
        starting_inventory=starting_inventory,
    )
    assert impact.status == "optimal"
    assert impact.lost_sales_by_customer_sku[("cust-1", "sku-a")] == des_lost_sales


@pytest.mark.parametrize("horizon", [-1.0, float("nan"), float("inf"), -float("inf")])
@pytest.mark.parametrize("solver_name", ["impact", "buffer"])
def test_fixed_horizon_lp_rejects_invalid_horizons(horizon: float, solver_name: str) -> None:
    """Reject invalid horizons before constructing a solver problem."""
    from daysofcover.lp.aggregate import solve_buffer

    solver = solve_impact if solver_name == "impact" else solve_buffer
    with pytest.raises(ValueError, match="horizon_days must be a finite, non-negative number"):
        solver(
            _case_7_network(),
            removed_element_id="n1",
            horizon_days=horizon,
            starting_inventory={("n3", sku_key("sku-a")): 50.0},
        )


def test_fixed_horizon_impact_does_not_teleport_stock_across_a_slow_lane() -> None:
    network = _case_8_network()
    # The plant has finished goods, but the only route to the customer
    # takes one day. Half a day of demand is five units.
    inventory = {("plant-1", sku_key("sku-a")): 10.0}
    short = solve_impact(
        network,
        removed_element_id="lane-in",
        horizon_days=0.5,
        starting_inventory=inventory,
    )
    assert short.status == "optimal"
    assert short.lost_sales_by_customer_sku[("cust-1", "sku-a")] == 5.0

    # A two-day horizon permits the pre-positioned plant stock to arrive.
    longer = solve_impact(
        network,
        removed_element_id="lane-in",
        horizon_days=2.0,
        starting_inventory=inventory,
    )
    assert longer.status == "optimal"
    assert longer.lost_sales_by_customer_sku[("cust-1", "sku-a")] == 10.0
