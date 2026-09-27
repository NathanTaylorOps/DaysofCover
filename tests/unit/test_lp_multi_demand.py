"""Regression tests for a real bug found while exercising ``daysofcover
cover`` against the full Moreton Marine network (33 nodes, 6 customers,
6 SKUs): the folded demand row in :func:`daysofcover.lp.aggregate._build`
used to be an equality, which forced lost sales negative -- infeasible --
whenever available supply (stock plus net inflow) exceeded demand at the
horizon being asked about. Cases 7 and 8 never caught this because both
are single-customer, single-SKU networks whose optimal point happens to
sit exactly on the boundary where an equality and an inequality agree.
These two cases are built specifically to sit off that boundary.
"""

from __future__ import annotations

from daysofcover.lp.aggregate import sku_key, solve_cover, solve_impact
from daysofcover.models.network import (
    SKU,
    BOMLine,
    Customer,
    Network,
    Node,
    NodeType,
    Part,
    SeasonalDemandProfile,
    SupplySource,
)


def _seasonal_profile(*, base_weekly_rate: float) -> SeasonalDemandProfile:
    return SeasonalDemandProfile(
        base_weekly_rate=base_weekly_rate, weekly_multipliers=[1.0] * 52, dispersion=1.0
    )


def _sku_a() -> SKU:
    return SKU(
        id="sku-a",
        name="SKU A",
        price={"AUD": 100.0},
        margin_fraction=0.5,
        currency="AUD",
        bom=[BOMLine(part_id="part-a", quantity=1.0)],
        production_lead_time_days=3.0,
        batch_size=1.0,
    )


def _single_customer_network(*, customer_id: str, holding_stock: float) -> Network:
    """One customer, no plant -- the same no-production shape as the buffer tests."""
    supplier = Node(id="supplier-1", name="Supplier", type=NodeType.SUPPLIER, region="AU")
    customer_node = Node(id=customer_id, name="Customer", type=NodeType.CUSTOMER, region="AU")
    part_a = Part(
        id="part-a",
        name="Part A",
        suppliers=[SupplySource(node_id="supplier-1", split_ratio=1.0)],
        unit_cost=1.0,
        currency="AUD",
    )
    customer = Customer(
        id=customer_id,
        name="Customer",
        demand={"sku-a": _seasonal_profile(base_weekly_rate=70.0)},  # 10.0/day
        backlog_window_days=30,
        allocation_priority=0,
    )
    return Network(
        base_currency="AUD",
        nodes=[supplier, customer_node],
        lanes=[],
        parts=[part_a],
        skus=[_sku_a()],
        customers=[customer],
    )


def test_impact_lp_reports_zero_lost_sales_when_stock_exceeds_demand_at_the_given_horizon() -> None:
    # 50 units on hand, 10/day demand, but the horizon asked about is
    # only 2 days (20 units demanded): a genuine surplus, not a shortage.
    # The old equality forced l = 20 - 50 = -30, infeasible; the correct
    # answer is simply zero lost sales, with 30 units left over unused.
    network = _single_customer_network(customer_id="cust-1", holding_stock=50.0)

    result = solve_impact(
        network,
        removed_element_id=None,
        horizon_days=2.0,
        starting_inventory={("cust-1", sku_key("sku-a")): 50.0},
    )

    assert result.status == "optimal"
    assert result.total_impact == 0.0
    assert result.lost_sales_by_customer_sku[("cust-1", "sku-a")] == 0.0


def test_cover_lp_finds_the_tighter_of_two_independent_customers_own_runways() -> None:
    # Two independent customers (no shared lanes, no shared production),
    # each pinning T to its own r/d ratio: cust-a's own stock lasts 5.0
    # days, cust-b's lasts only 3.0. The old equality required both
    # ratios to be numerically equal -- impossible here -- so it reported
    # infeasible; the correct answer is the tighter one, 3.0, since that
    # is genuinely the first point at which *something* runs out.
    supplier = Node(id="supplier-1", name="Supplier", type=NodeType.SUPPLIER, region="AU")
    cust_a = Node(id="cust-a", name="Customer A", type=NodeType.CUSTOMER, region="AU")
    cust_b = Node(id="cust-b", name="Customer B", type=NodeType.CUSTOMER, region="AU")
    part_a = Part(
        id="part-a",
        name="Part A",
        suppliers=[SupplySource(node_id="supplier-1", split_ratio=1.0)],
        unit_cost=1.0,
        currency="AUD",
    )
    demand_profile = _seasonal_profile(base_weekly_rate=70.0)  # 10.0/day, both customers
    customer_a = Customer(
        id="cust-a",
        name="Customer A",
        demand={"sku-a": demand_profile},
        backlog_window_days=30,
        allocation_priority=0,
    )
    customer_b = Customer(
        id="cust-b",
        name="Customer B",
        demand={"sku-a": demand_profile},
        backlog_window_days=30,
        allocation_priority=0,
    )
    network = Network(
        base_currency="AUD",
        nodes=[supplier, cust_a, cust_b],
        lanes=[],
        parts=[part_a],
        skus=[_sku_a()],
        customers=[customer_a, customer_b],
    )
    starting_inventory = {
        ("cust-a", sku_key("sku-a")): 50.0,  # 50 / 10 = 5.0 days
        ("cust-b", sku_key("sku-a")): 30.0,  # 30 / 10 = 3.0 days
    }

    result = solve_cover(network, removed_element_id=None, starting_inventory=starting_inventory)

    assert result.status == "optimal"
    assert result.cover_days == 3.0
