"""Stage 1, sessions 15 and 17: the daily-step loop, then multiple SKUs
sharing a scarce component.

Not a validation case: session 15's single test is still the hand-traced
baseline (every number reproduced exactly, now through the multi-SKU
``sku_specs`` API rather than the single-SKU arguments it started with).
This session's new tests check the allocation rule itself is actually
wired in -- two SKUs competing for one component split by backlog share
or by margin, and a third SKU whose BOM never touches the shared
component staying untouched by either.
"""

from __future__ import annotations

import numpy as np

from daysofcover.engine.daily_step import SkuProductionSpec, advance_one_day
from daysofcover.engine.production import ProductionQueue
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


def _network() -> Network:
    supplier = Node(id="supplier-1", name="Supplier One", type=NodeType.SUPPLIER, region="AU")
    plant = Node(id="plant-1", name="Plant One", type=NodeType.PLANT, region="AU")
    lane = Lane(
        id="lane-1",
        origin_id="supplier-1",
        destination_id="plant-1",
        mode=LaneMode.OCEAN,
        lead_time_days_median=2.0,
        lead_time_days_sigma=0.0,  # deterministic: always arrives on day 2
        capacity_per_week=1000.0,
        unit_cost=1.0,
        currency="AUD",
        allow_crossing=False,
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
    return Network(
        base_currency="AUD",
        nodes=[supplier, plant],
        lanes=[lane],
        parts=[part_a],
        skus=[sku_a],
    )


def test_one_plant_one_sku_traced_over_seven_days() -> None:
    network = _network()
    state = NetworkState.from_network(network)
    shipments = NetworkShipments.from_network(network)
    production_queue = ProductionQueue()
    rng = np.random.default_rng(seed=1)
    shipments.ship(lane_id="lane-1", part_id="part-a", quantity=50.0, order_day=0, rng=rng)

    bom = [BOMLine(part_id="part-a", quantity=1.0)]
    spec = SkuProductionSpec(
        finished_sku_id="sku-a",
        bom=bom,
        capacity_per_week=7_000.0,
        batch_size=1.0,
        production_lead_time_days=3.0,
        daily_demand=10.0,
        production_queue=production_queue,
    )

    reports = []
    for day in range(7):
        report = advance_one_day(
            state=state,
            shipments=shipments,
            plant_node_id="plant-1",
            component_part_id="part-a",
            inbound_lane_id="lane-1",
            sku_specs=[spec],
            current_day=day,
        )
        reports.append(report)

    plant = state.node_index("plant-1")
    component_idx = state.part_index("part-a")
    sku_idx = state.sku_index("sku-a")

    # day 2: the 50-unit shipment arrives and all of it starts production
    assert reports[2].components_received == 50.0
    assert reports[2].sku_reports[0].production_started == 50.0
    assert reports[2].sku_reports[0].demand_met == 0.0

    # day 5: that batch (3-day lead time from day 2) completes and meets
    # that day's demand
    assert reports[5].sku_reports[0].finished_goods_completed == 50.0
    assert reports[5].sku_reports[0].demand_met == 10.0

    # every component that arrived went into that single batch
    assert state.on_hand[plant, component_idx] == 0.0
    assert production_queue.outstanding() == 0.0

    # demand was unmet on days 0, 1, 2, 3 and 4 (50.0), then met on days 5 and 6
    assert state.finished_backlog[plant, sku_idx] == 50.0
    # 50 units produced, 10 sold on day 5 and 10 on day 6, 30 left on the shelf
    assert state.finished_on_hand[plant, sku_idx] == 30.0


def _two_sku_network() -> Network:
    supplier = Node(id="supplier-1", name="Supplier One", type=NodeType.SUPPLIER, region="AU")
    plant = Node(id="plant-1", name="Plant One", type=NodeType.PLANT, region="AU")
    part_a = Part(
        id="part-a",
        name="Part A",
        suppliers=[SupplySource(node_id="supplier-1", split_ratio=1.0)],
        unit_cost=1.0,
        currency="AUD",
    )
    part_b = Part(
        id="part-b",
        name="Part B",
        suppliers=[SupplySource(node_id="supplier-1", split_ratio=1.0)],
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
    sku_b = SKU(
        id="sku-b",
        name="SKU B",
        price={"AUD": 80.0},
        margin_fraction=0.2,
        currency="AUD",
        bom=[BOMLine(part_id="part-a", quantity=1.0)],
        production_lead_time_days=3.0,
        batch_size=1.0,
    )
    sku_c = SKU(
        id="sku-c",
        name="SKU C",
        price={"AUD": 60.0},
        margin_fraction=0.3,
        currency="AUD",
        bom=[BOMLine(part_id="part-b", quantity=1.0)],
        production_lead_time_days=3.0,
        batch_size=1.0,
    )
    return Network(
        base_currency="AUD",
        nodes=[supplier, plant],
        lanes=[],
        parts=[part_a, part_b],
        skus=[sku_a, sku_b, sku_c],
    )


def _spec(sku_id: str, *, bom: list[BOMLine], margin_fraction: float = 0.0) -> SkuProductionSpec:
    return SkuProductionSpec(
        finished_sku_id=sku_id,
        bom=bom,
        capacity_per_week=7_000.0,  # deliberately far above on-hand: never the binding cap
        batch_size=1.0,
        production_lead_time_days=3.0,
        daily_demand=0.0,  # zero demand keeps backlog exactly at whatever the test sets
        production_queue=ProductionQueue(),
        margin_fraction=margin_fraction,
    )


def test_two_skus_share_a_scarce_component_split_by_backlog_proportion() -> None:
    network = _two_sku_network()
    state = NetworkState.from_network(network)
    shipments = NetworkShipments.from_network(network)
    plant = state.node_index("plant-1")
    state.on_hand[plant, state.part_index("part-a")] = 100.0
    state.finished_backlog[plant, state.sku_index("sku-a")] = 30.0
    state.finished_backlog[plant, state.sku_index("sku-b")] = 70.0

    bom = [BOMLine(part_id="part-a", quantity=1.0)]
    report = advance_one_day(
        state=state,
        shipments=shipments,
        plant_node_id="plant-1",
        component_part_id="part-a",
        inbound_lane_id=None,
        sku_specs=[_spec("sku-a", bom=bom), _spec("sku-b", bom=bom)],
        current_day=0,
    )

    by_sku = {r.finished_sku_id: r for r in report.sku_reports}
    # split 30/70, the same ratio as the backlogs
    assert by_sku["sku-a"].production_started == 30.0
    assert by_sku["sku-b"].production_started == 70.0
    # every unit of the shared component was claimed by one SKU or the other
    assert state.on_hand[plant, state.part_index("part-a")] == 0.0


def test_two_skus_share_a_scarce_component_with_margin_priority() -> None:
    network = _two_sku_network()
    state = NetworkState.from_network(network)
    shipments = NetworkShipments.from_network(network)
    plant = state.node_index("plant-1")
    state.on_hand[plant, state.part_index("part-a")] = 50.0

    bom = [BOMLine(part_id="part-a", quantity=1.0)]
    report = advance_one_day(
        state=state,
        shipments=shipments,
        plant_node_id="plant-1",
        component_part_id="part-a",
        inbound_lane_id=None,
        sku_specs=[
            _spec("sku-a", bom=bom, margin_fraction=0.5),
            _spec("sku-b", bom=bom, margin_fraction=0.2),
        ],
        current_day=0,
        allocation_rule="margin_priority",
    )

    by_sku = {r.finished_sku_id: r for r in report.sku_reports}
    # sku-a's higher margin gets it served in full first; nothing is left for sku-b
    assert by_sku["sku-a"].production_started == 50.0
    assert by_sku["sku-b"].production_started == 0.0


def test_a_sku_whose_bom_does_not_touch_the_shared_component_is_unaffected() -> None:
    network = _two_sku_network()
    state = NetworkState.from_network(network)
    shipments = NetworkShipments.from_network(network)
    plant = state.node_index("plant-1")
    state.on_hand[plant, state.part_index("part-a")] = 100.0
    state.on_hand[plant, state.part_index("part-b")] = 40.0

    bom_a = [BOMLine(part_id="part-a", quantity=1.0)]
    bom_c = [BOMLine(part_id="part-b", quantity=1.0)]
    report = advance_one_day(
        state=state,
        shipments=shipments,
        plant_node_id="plant-1",
        component_part_id="part-a",
        inbound_lane_id=None,
        sku_specs=[_spec("sku-a", bom=bom_a), _spec("sku-b", bom=bom_a), _spec("sku-c", bom=bom_c)],
        current_day=0,
    )

    by_sku = {r.finished_sku_id: r for r in report.sku_reports}
    # no backlog set for either sku-a or sku-b: falls back to an even split of part-a
    assert by_sku["sku-a"].production_started == 50.0
    assert by_sku["sku-b"].production_started == 50.0
    # sku-c never competed for part-a at all -- its own part-b on-hand is untouched
    assert by_sku["sku-c"].production_started == 40.0
    assert state.on_hand[plant, state.part_index("part-b")] == 0.0
