"""Validation case 9: "DES >= LP in general" -- on any network the LP is
an optimistic bound on sales lost plus sales delayed; the gap on this
network is reported as a finding rather than asserted exactly (the build
plan's own tolerance for this case is "asserted", not "exact", unlike
cases 7 and 8).

Deliberately the opposite setup from case 8: ordinary, *undisrupted*
operation (``removed_element_id=None`` on both sides), a cold start (no
starting inventory at all -- this network's plant has never ordered
anything until day 0's own review), and a real periodic-review
order-up-to policy (``order_up_to``/``review_period_days``, left ``None``
in every earlier LP-layer test) actually reordering the component. The
inbound lane's capacity (50/week, about 7.1/day) sits below the
customer's own demand rate (10/day), so even the LP's perfect-foresight,
lead-time-free view predicts *some* loss -- but the LP has no notion of
lead time at all, so it never sees the real ~5-day pipeline-fill lag (2
days component transit, 3 days production) before the very first unit
can even leave the plant. That lag is where the gap comes from: nothing
external is disrupted, nothing is engineered to be unfair to the DES --
this is the ordinary machinery of Days of Cover, run in the ordinary way,
turned on the LP's own founding assumption that flow can happen exactly
when and where it's needed.
"""

from __future__ import annotations

import numpy as np

from daysofcover.engine.allocation import CustomerOrder
from daysofcover.engine.daily_step import SkuProductionSpec, advance_one_day
from daysofcover.engine.distribution import build_distribution_tree
from daysofcover.engine.production import ProductionQueue
from daysofcover.engine.shipments import NetworkShipments
from daysofcover.engine.state import NetworkState
from daysofcover.lp.aggregate import solve_impact, starting_inventory_from_state
from daysofcover.lp.gap_report import format_gap_finding
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

HORIZON_DAYS = 14


def _seasonal_profile(*, base_weekly_rate: float) -> SeasonalDemandProfile:
    return SeasonalDemandProfile(
        base_weekly_rate=base_weekly_rate, weekly_multipliers=[1.0] * 52, dispersion=1.0
    )


def _network() -> Network:
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
        capacity_per_week=50.0,  # ~7.1/day -- below the customer's own 10/day demand
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
        capacity_per_week=1000.0,  # ample -- the inbound lane is the real constraint
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


def test_des_lost_sales_exceed_the_lp_bound_under_ordinary_operation() -> None:
    network = _network()
    state = NetworkState.from_network(network)
    shipments = NetworkShipments.from_network(network)
    tree = build_distribution_tree(network, plant_node_id="plant-1")
    rng = np.random.default_rng(seed=1)

    # a genuine cold start: nothing pre-staged, nothing pre-ordered --
    # the plant's first order is whatever day 0's own review decides.
    starting_inventory = starting_inventory_from_state(state=state, shipments=shipments)
    assert starting_inventory == {}

    production_queue = ProductionQueue()  # persists across days -- a real in-flight queue
    for day in range(HORIZON_DAYS):
        spec = SkuProductionSpec(
            finished_sku_id="sku-a",
            bom=[BOMLine(part_id="part-a", quantity=1.0)],
            capacity_per_week=7_000.0,  # not the constraint under test
            batch_size=1.0,
            production_lead_time_days=3.0,
            orders=[CustomerOrder(customer_id="cust-1", order_day=day, quantity=10.0, priority=0)],
            production_queue=production_queue,
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
            order_up_to=100.0,
            review_period_days=7,
        )

    cust_idx = state.node_index("cust-1")
    sku_idx = state.sku_index("sku-a")
    des_lost_units = float(state.finished_backlog[cust_idx, sku_idx])
    assert des_lost_units == 80.0  # 14 days at 10/day = 140 demanded; 80 never repaid

    impact = solve_impact(
        network,
        removed_element_id=None,
        horizon_days=float(HORIZON_DAYS),
        starting_inventory=starting_inventory,
    )
    assert impact.status == "optimal"
    lp_lost_units = impact.lost_sales_by_customer_sku[("cust-1", "sku-a")]
    assert lp_lost_units == 40.0  # the inbound lane's own capacity shortfall, nothing else

    # case 9's own tolerance is "asserted", not "exact" -- this is the
    # inequality the build plan calls the LP an optimistic bound on.
    assert des_lost_units > lp_lost_units

    margin_per_unit = 100.0 * 0.4  # sku-a's own price * margin_fraction
    des_cost = margin_per_unit * des_lost_units
    finding = format_gap_finding(des_cost=des_cost, lp_cost=impact.total_impact)
    assert finding == (
        "the simulation's cost exceeds the LP bound by 100%; "
        "that is the price of myopic replenishment"
    )
