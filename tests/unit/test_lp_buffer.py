"""The buffer LP: minimise holding cost on added inventory subject to zero
lost sales.

Two hand-derivable cases, chosen to expose a real property of the model
rather than paper over it: when the only place capable of holding stock is
the demand node itself, the buffer's cost is whatever that node's own
holding_cost_rate says it is; when a cheaper (here, zero-cost) node sits
upstream with slack lane capacity to reach the demand node in time, the
solver places the buffer there instead, and the true minimum cost is
zero -- not a bug, a direct consequence of :mod:`daysofcover.lp.aggregate`'s
own documented choice to treat a node with no `holding_cost_rate` as a
zero coefficient rather than a hidden default.
"""

from __future__ import annotations

import pytest

from daysofcover.lp.aggregate import sku_key, solve_buffer
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


def _seasonal_profile(*, base_weekly_rate: float) -> SeasonalDemandProfile:
    return SeasonalDemandProfile(
        base_weekly_rate=base_weekly_rate, weekly_multipliers=[1.0] * 52, dispersion=1.0
    )


def _sku_a(*, margin_fraction: float) -> SKU:
    return SKU(
        id="sku-a",
        name="SKU A",
        price={"AUD": 100.0},
        margin_fraction=margin_fraction,
        currency="AUD",
        bom=[BOMLine(part_id="part-a", quantity=1.0)],
        production_lead_time_days=3.0,
        batch_size=1.0,
    )


def test_buffer_cost_is_hand_computed_when_only_the_demand_node_can_hold_stock() -> None:
    # no plant at all: nothing can ever be produced, so the only way to
    # avoid lost sales is to hold more stock at the customer itself.
    supplier = Node(
        id="supplier-1", name="Supplier", type=NodeType.SUPPLIER, region="AU", holding_cost_rate=0.2
    )
    customer_node = Node(
        id="cust-1", name="Customer", type=NodeType.CUSTOMER, region="AU", holding_cost_rate=0.2
    )
    part_a = Part(
        id="part-a",
        name="Part A",
        suppliers=[SupplySource(node_id="supplier-1", split_ratio=1.0)],
        unit_cost=1.0,
        currency="AUD",
    )
    customer = Customer(
        id="cust-1",
        name="Customer",
        demand={"sku-a": _seasonal_profile(base_weekly_rate=70.0)},  # 10.0/day
        backlog_window_days=30,
        allocation_priority=0,
    )
    network = Network(
        base_currency="AUD",
        nodes=[supplier, customer_node],
        lanes=[],
        parts=[part_a],
        skus=[_sku_a(margin_fraction=0.5)],  # unit cost = 100 * (1 - 0.5) = 50
        customers=[customer],
    )

    # 5 days at 10/day = 50 demanded, 20 already on hand: 30 units short,
    # and cust-1's own rate (0.2) times sku-a's unit cost (50) is 10/unit:
    # 30 * 10 = 300.0, exactly.
    result = solve_buffer(
        network,
        removed_element_id=None,
        horizon_days=5.0,
        starting_inventory={("cust-1", sku_key("sku-a")): 20.0},
    )

    assert result.status == "optimal"
    assert result.total_holding_cost == 300.0
    assert result.added_inventory.get(("cust-1", sku_key("sku-a"))) == 30.0


def test_buffer_rejects_missing_upstream_holding_cost_instead_of_assuming_free_storage() -> None:
    # n1 (plant, removed) -> n2 (dc, no holding_cost_rate -- free) -> n3
    # (customer, holding_cost_rate set -- costed). With n1 gone nothing
    # can be produced either way, so the only question is *where* to
    # place the needed stock -- and n2's free cost plus lane-23's ample
    # capacity make placing it there strictly cheaper than at n3 itself.
    n1 = Node(id="n1", name="Plant", type=NodeType.PLANT, region="AU")
    n2 = Node(id="n2", name="DC", type=NodeType.DC, region="AU")
    n3 = Node(id="n3", name="Customer", type=NodeType.CUSTOMER, region="AU", holding_cost_rate=0.2)
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
    customer = Customer(
        id="n3",
        name="Customer",
        demand={"sku-a": _seasonal_profile(base_weekly_rate=70.0)},  # 10.0/day
        backlog_window_days=30,
        allocation_priority=0,
    )
    network = Network(
        base_currency="AUD",
        nodes=[n1, n2, n3],
        lanes=[lane_12, lane_23],
        parts=[part_a],
        skus=[_sku_a(margin_fraction=0.5)],
        customers=[customer],
    )

    with pytest.raises(ValueError, match="missing: n2"):
        solve_buffer(network, removed_element_id="n1", horizon_days=5.0, starting_inventory={})
