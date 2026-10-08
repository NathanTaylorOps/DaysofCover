"""Session 23: routing finished goods from a plant to customers over real lanes.

Not a validation case: there is no external reference here, only that
the tree resolution and the daily push do what
:mod:`daysofcover.engine.distribution`'s module docstring says they do.
See :mod:`daysofcover.engine.disruption_state`'s own test file for the
sibling pattern this one follows.
"""

from __future__ import annotations

import numpy as np
import pytest

from daysofcover.engine.disruption_state import DisruptionState
from daysofcover.engine.distribution import build_distribution_tree, push_finished_goods
from daysofcover.engine.shipments import NetworkShipments
from daysofcover.engine.state import NetworkState
from daysofcover.models.network import (
    SKU,
    BOMLine,
    Lane,
    LaneMode,
    Network,
    Node,
    NodeType,
    Part,
    SupplySource,
)
from daysofcover.models.scenario import Disruption, Scenario


def _fan_out_network(
    *, dc_cust_a_capacity: float = 1000.0, dc_cust_b_capacity: float = 1000.0
) -> Network:
    """plant-1 --lane-dc--> dc-1 --lane-a/lane-b--> cust-a / cust-b, one part, no SKUs.

    No SKUs or parts are wired to production here -- these tests drive
    ``finished_on_hand``/``finished_backlog`` directly, since the
    distribution module only ever reads and writes those two arrays
    plus the real lanes; it does not care how the goods got produced.
    """
    plant = Node(id="plant-1", name="Plant", type=NodeType.PLANT, region="AU")
    dc = Node(id="dc-1", name="DC", type=NodeType.DC, region="AU")
    cust_a = Node(id="cust-a", name="Customer A", type=NodeType.CUSTOMER, region="AU")
    cust_b = Node(id="cust-b", name="Customer B", type=NodeType.CUSTOMER, region="AU")
    lane_dc = Lane(
        id="lane-dc",
        origin_id="plant-1",
        destination_id="dc-1",
        mode=LaneMode.ROAD,
        lead_time_days_median=1.0,
        lead_time_days_sigma=0.0,
        capacity_per_week=1000.0,
        unit_cost=1.0,
        currency="AUD",
    )
    lane_a = Lane(
        id="lane-a",
        origin_id="dc-1",
        destination_id="cust-a",
        mode=LaneMode.ROAD,
        lead_time_days_median=1.0,
        lead_time_days_sigma=0.0,
        capacity_per_week=dc_cust_a_capacity,
        unit_cost=1.0,
        currency="AUD",
    )
    lane_b = Lane(
        id="lane-b",
        origin_id="dc-1",
        destination_id="cust-b",
        mode=LaneMode.ROAD,
        lead_time_days_median=1.0,
        lead_time_days_sigma=0.0,
        capacity_per_week=dc_cust_b_capacity,
        unit_cost=1.0,
        currency="AUD",
    )
    # a part/supplier is required by schema even though these tests
    # never touch component flow -- kept minimal, unreferenced by any BOM.
    part_a = Part(
        id="part-a",
        name="Part A",
        suppliers=[SupplySource(node_id="plant-1", split_ratio=1.0)],
        unit_cost=1.0,
        currency="AUD",
    )
    return Network(
        base_currency="AUD",
        nodes=[plant, dc, cust_a, cust_b],
        lanes=[lane_dc, lane_a, lane_b],
        parts=[part_a],
        skus=[],
    )


def test_build_distribution_tree_resolves_both_customer_paths() -> None:
    tree = build_distribution_tree(_fan_out_network(), plant_node_id="plant-1")

    assert tree.path_by_customer["cust-a"] == ("lane-dc", "lane-a")
    assert tree.path_by_customer["cust-b"] == ("lane-dc", "lane-b")
    assert tree.outbound_lanes_by_node["plant-1"] == ("lane-dc",)
    assert set(tree.outbound_lanes_by_node["dc-1"]) == {"lane-a", "lane-b"}
    assert tree.inbound_lane_by_node["dc-1"] == "lane-dc"
    assert tree.inbound_lane_by_node["cust-a"] == "lane-a"
    assert tree.nodes_in_push_order[0] == "plant-1"
    assert set(tree.nodes_in_push_order) == {"plant-1", "dc-1", "cust-a", "cust-b"}
    assert set(tree.customers_downstream_of_lane["lane-dc"]) == {"cust-a", "cust-b"}
    assert tree.customers_downstream_of_lane["lane-a"] == ("cust-a",)


def test_build_distribution_tree_with_no_customer_nodes_is_empty() -> None:
    plant = Node(id="plant-1", name="Plant", type=NodeType.PLANT, region="AU")
    part_a = Part(
        id="part-a",
        name="Part A",
        suppliers=[SupplySource(node_id="plant-1", split_ratio=1.0)],
        unit_cost=1.0,
        currency="AUD",
    )
    network = Network(base_currency="AUD", nodes=[plant], lanes=[], parts=[part_a], skus=[])

    tree = build_distribution_tree(network, plant_node_id="plant-1")

    assert tree.path_by_customer == {}
    assert tree.outbound_lanes_by_node == {}
    assert tree.nodes_in_push_order == ("plant-1",)


def test_build_distribution_tree_rejects_a_second_path_to_the_same_node() -> None:
    plant = Node(id="plant-1", name="Plant", type=NodeType.PLANT, region="AU")
    dc = Node(id="dc-1", name="DC", type=NodeType.DC, region="AU")
    cust = Node(id="cust-a", name="Customer A", type=NodeType.CUSTOMER, region="AU")
    lane_1 = Lane(
        id="lane-1",
        origin_id="plant-1",
        destination_id="dc-1",
        mode=LaneMode.ROAD,
        lead_time_days_median=1.0,
        lead_time_days_sigma=0.0,
        capacity_per_week=100.0,
        unit_cost=1.0,
        currency="AUD",
    )
    # a second, direct lane straight to the same dc -- an ambiguous
    # second path to dc-1, which this module's tree assumption rejects.
    lane_2 = Lane(
        id="lane-2",
        origin_id="plant-1",
        destination_id="dc-1",
        mode=LaneMode.AIR,
        lead_time_days_median=1.0,
        lead_time_days_sigma=0.0,
        capacity_per_week=100.0,
        unit_cost=5.0,
        currency="AUD",
    )
    lane_3 = Lane(
        id="lane-3",
        origin_id="dc-1",
        destination_id="cust-a",
        mode=LaneMode.ROAD,
        lead_time_days_median=1.0,
        lead_time_days_sigma=0.0,
        capacity_per_week=100.0,
        unit_cost=1.0,
        currency="AUD",
    )
    part_a = Part(
        id="part-a",
        name="Part A",
        suppliers=[SupplySource(node_id="plant-1", split_ratio=1.0)],
        unit_cost=1.0,
        currency="AUD",
    )
    network = Network(
        base_currency="AUD",
        nodes=[plant, dc, cust],
        lanes=[lane_1, lane_2, lane_3],
        parts=[part_a],
        skus=[],
    )

    with pytest.raises(ValueError, match="more than one path"):
        build_distribution_tree(network, plant_node_id="plant-1")


def test_push_moves_plant_stock_to_the_dc_then_on_to_each_customer() -> None:
    plant = Node(id="plant-1", name="Plant", type=NodeType.PLANT, region="AU")
    dc = Node(id="dc-1", name="DC", type=NodeType.DC, region="AU")
    cust_a = Node(id="cust-a", name="Customer A", type=NodeType.CUSTOMER, region="AU")
    cust_b = Node(id="cust-b", name="Customer B", type=NodeType.CUSTOMER, region="AU")
    lane_dc = Lane(
        id="lane-dc",
        origin_id="plant-1",
        destination_id="dc-1",
        mode=LaneMode.ROAD,
        lead_time_days_median=1.0,
        lead_time_days_sigma=0.0,
        capacity_per_week=1000.0,
        unit_cost=1.0,
        currency="AUD",
    )
    lane_a = Lane(
        id="lane-a",
        origin_id="dc-1",
        destination_id="cust-a",
        mode=LaneMode.ROAD,
        lead_time_days_median=1.0,
        lead_time_days_sigma=0.0,
        capacity_per_week=1000.0,
        unit_cost=1.0,
        currency="AUD",
    )
    lane_b = Lane(
        id="lane-b",
        origin_id="dc-1",
        destination_id="cust-b",
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
        suppliers=[SupplySource(node_id="plant-1", split_ratio=1.0)],
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
    network = Network(
        base_currency="AUD",
        nodes=[plant, dc, cust_a, cust_b],
        lanes=[lane_dc, lane_a, lane_b],
        parts=[part_a],
        skus=[sku_a],
    )
    tree = build_distribution_tree(network, plant_node_id="plant-1")
    state = NetworkState.from_network(network)
    shipments = NetworkShipments.from_network(network)
    rng = np.random.default_rng(seed=1)

    plant_idx = state.node_index("plant-1")
    dc_idx = state.node_index("dc-1")
    cust_a_idx = state.node_index("cust-a")
    cust_b_idx = state.node_index("cust-b")
    sku_idx = state.sku_index("sku-a")

    state.finished_on_hand[plant_idx, sku_idx] = 100.0
    # cust-a has twice cust-b's outstanding backlog: split should be 2:1
    state.finished_backlog[cust_a_idx, sku_idx] = 20.0
    state.finished_backlog[cust_b_idx, sku_idx] = 10.0

    # day 0: plant ships to the dc (1-day lead time, deterministic sigma=0)
    shipped_day0 = push_finished_goods(
        state=state, shipments=shipments, tree=tree, sku_id="sku-a", current_day=0, rng=rng
    )
    assert shipped_day0 == 100.0
    assert state.finished_on_hand[plant_idx, sku_idx] == 0.0
    assert state.finished_on_hand[dc_idx, sku_idx] == 0.0  # still in transit to the dc

    # day 1: the dc receives the 100 units, then immediately splits and
    # ships onward 2:1 by backlog proportion, both customer lanes clear
    shipped_day1 = push_finished_goods(
        state=state, shipments=shipments, tree=tree, sku_id="sku-a", current_day=1, rng=rng
    )
    assert shipped_day1 == pytest.approx(100.0)
    assert state.finished_on_hand[dc_idx, sku_idx] == pytest.approx(0.0)
    assert state.finished_on_hand[cust_a_idx, sku_idx] == 0.0  # still in transit
    assert state.finished_on_hand[cust_b_idx, sku_idx] == 0.0

    # day 2: both customer legs land
    shipped_day2 = push_finished_goods(
        state=state, shipments=shipments, tree=tree, sku_id="sku-a", current_day=2, rng=rng
    )
    assert shipped_day2 == pytest.approx(0.0)
    assert state.finished_on_hand[cust_a_idx, sku_idx] == pytest.approx(200.0 / 3.0)
    assert state.finished_on_hand[cust_b_idx, sku_idx] == pytest.approx(100.0 / 3.0)


def test_push_caps_each_branch_by_its_own_lane_capacity_only() -> None:
    plant = Node(id="plant-1", name="Plant", type=NodeType.PLANT, region="AU")
    dc = Node(id="dc-1", name="DC", type=NodeType.DC, region="AU")
    cust_a = Node(id="cust-a", name="Customer A", type=NodeType.CUSTOMER, region="AU")
    cust_b = Node(id="cust-b", name="Customer B", type=NodeType.CUSTOMER, region="AU")
    lane_dc = Lane(
        id="lane-dc",
        origin_id="plant-1",
        destination_id="dc-1",
        mode=LaneMode.ROAD,
        lead_time_days_median=1.0,
        lead_time_days_sigma=0.0,
        capacity_per_week=1000.0,
        unit_cost=1.0,
        currency="AUD",
    )
    # cust-b's own lane can only move 10 units/week -- far below its
    # even 50/50 share; cust-a's lane is untouched by that tightness.
    lane_a = Lane(
        id="lane-a",
        origin_id="dc-1",
        destination_id="cust-a",
        mode=LaneMode.ROAD,
        lead_time_days_median=1.0,
        lead_time_days_sigma=0.0,
        capacity_per_week=1000.0,
        unit_cost=1.0,
        currency="AUD",
    )
    lane_b = Lane(
        id="lane-b",
        origin_id="dc-1",
        destination_id="cust-b",
        mode=LaneMode.ROAD,
        lead_time_days_median=1.0,
        lead_time_days_sigma=0.0,
        capacity_per_week=10.0,
        unit_cost=1.0,
        currency="AUD",
    )
    part_a = Part(
        id="part-a",
        name="Part A",
        suppliers=[SupplySource(node_id="plant-1", split_ratio=1.0)],
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
    network = Network(
        base_currency="AUD",
        nodes=[plant, dc, cust_a, cust_b],
        lanes=[lane_dc, lane_a, lane_b],
        parts=[part_a],
        skus=[sku_a],
    )
    tree = build_distribution_tree(network, plant_node_id="plant-1")
    state = NetworkState.from_network(network)
    shipments = NetworkShipments.from_network(network)
    rng = np.random.default_rng(seed=1)

    dc_idx = state.node_index("dc-1")
    sku_idx = state.sku_index("sku-a")
    state.finished_on_hand[dc_idx, sku_idx] = 100.0
    # equal backlog: an even 50/50 desired split
    state.finished_backlog[state.node_index("cust-a"), sku_idx] = 10.0
    state.finished_backlog[state.node_index("cust-b"), sku_idx] = 10.0

    push_finished_goods(
        state=state, shipments=shipments, tree=tree, sku_id="sku-a", current_day=0, rng=rng
    )

    # cust-a's desired 50 ships in full; cust-b's desired 50 is capped
    # at its lane's 10-unit weekly capacity -- 40 units are left behind
    # at the dc, not redistributed to cust-a this same call.
    assert shipments.lanes["lane-a"].outstanding(part_id="sku-a") == 50.0
    assert shipments.lanes["lane-b"].outstanding(part_id="sku-a") == 10.0
    assert state.finished_on_hand[dc_idx, sku_idx] == 40.0


def test_push_requires_rng_when_a_shipment_is_positive() -> None:
    plant = Node(id="plant-1", name="Plant", type=NodeType.PLANT, region="AU")
    cust = Node(id="cust-a", name="Customer A", type=NodeType.CUSTOMER, region="AU")
    lane = Lane(
        id="lane-a",
        origin_id="plant-1",
        destination_id="cust-a",
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
        suppliers=[SupplySource(node_id="plant-1", split_ratio=1.0)],
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
    network = Network(
        base_currency="AUD",
        nodes=[plant, cust],
        lanes=[lane],
        parts=[part_a],
        skus=[sku_a],
    )
    tree = build_distribution_tree(network, plant_node_id="plant-1")
    state = NetworkState.from_network(network)
    shipments = NetworkShipments.from_network(network)
    state.finished_on_hand[state.node_index("plant-1"), state.sku_index("sku-a")] = 10.0

    with pytest.raises(ValueError, match="rng is required"):
        push_finished_goods(
            state=state, shipments=shipments, tree=tree, sku_id="sku-a", current_day=0, rng=None
        )


def test_fully_down_distribution_lane_holds_cargo_instead_of_releasing_it() -> None:
    plant = Node(id="plant-1", name="Plant", type=NodeType.PLANT, region="AU")
    cust = Node(id="cust-a", name="Customer A", type=NodeType.CUSTOMER, region="AU")
    lane = Lane(
        id="lane-a",
        origin_id="plant-1",
        destination_id="cust-a",
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
        suppliers=[SupplySource(node_id="plant-1", split_ratio=1.0)],
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
    network = Network(
        base_currency="AUD",
        nodes=[plant, cust],
        lanes=[lane],
        parts=[part_a],
        skus=[sku_a],
    )
    tree = build_distribution_tree(network, plant_node_id="plant-1")
    state = NetworkState.from_network(network)
    shipments = NetworkShipments.from_network(network)
    rng = np.random.default_rng(seed=1)

    plant_idx = state.node_index("plant-1")
    cust_idx = state.node_index("cust-a")
    sku_idx = state.sku_index("sku-a")
    state.finished_on_hand[plant_idx, sku_idx] = 50.0

    disruption = Disruption(
        element_id="lane-a", start_day=0, severity_fraction=1.0, duration_days=10
    )
    disruption_state = DisruptionState.from_scenario(
        Scenario(id="s1", name="Closure", disruptions=[disruption], seed=1), network=network
    )

    shipped = push_finished_goods(
        state=state,
        shipments=shipments,
        tree=tree,
        sku_id="sku-a",
        current_day=0,
        rng=rng,
        disruption_state=disruption_state,
    )
    assert shipped == 0.0
    assert state.finished_on_hand[plant_idx, sku_idx] == 50.0
    assert state.finished_on_hand[cust_idx, sku_idx] == 0.0


def test_multiday_distribution_conserves_stock_across_nodes_and_transit() -> None:
    """A fixed finished-goods supply is never created or lost during multi-hop transit."""
    network = _fan_out_network(dc_cust_b_capacity=10.0)
    sku_id = "sku-a"
    sku = SKU(
        id=sku_id,
        name="SKU A",
        price={"AUD": 100.0},
        margin_fraction=0.4,
        currency="AUD",
        bom=[BOMLine(part_id="part-a", quantity=1.0)],
        production_lead_time_days=1.0,
        batch_size=1.0,
    )
    network = network.model_copy(update={"skus": [sku]})
    state = NetworkState.from_network(network)
    shipments = NetworkShipments.from_network(network)
    rng = np.random.default_rng(seed=7)
    tree = build_distribution_tree(network, plant_node_id="plant-1")
    state.finished_on_hand[state.node_index("plant-1"), 0] = 90.0
    state.finished_backlog[state.node_index("cust-a"), 0] = 60.0
    state.finished_backlog[state.node_index("cust-b"), 0] = 30.0

    for day in range(12):
        push_finished_goods(
            state=state,
            shipments=shipments,
            tree=tree,
            sku_id=sku_id,
            current_day=day,
            rng=rng,
        )
        on_hand = float(state.finished_on_hand.sum())
        in_transit = sum(
            lane.outstanding(part_id=sku_id) for lane in shipments.lanes.values()
        )
        assert on_hand + in_transit == pytest.approx(90.0)
        assert np.all(state.finished_on_hand >= -1e-8)
        if day == 0:
            assert in_transit == pytest.approx(90.0)
        if day == 1:
            assert state.finished_on_hand[state.node_index("cust-a"), 0] == 0.0
        if day >= 2:
            assert state.finished_on_hand[state.node_index("cust-a"), 0] > 0.0
