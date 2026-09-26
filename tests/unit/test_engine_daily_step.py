"""Stage 1, session 15: the first end-to-end daily-step loop.

Not a validation case: this is the first test that runs the state
chassis, per-lane shipments and BOM-driven production together over
several days, rather than checking each in isolation. Every number below
is traced by hand and reproduced exactly here -- see
:mod:`daysofcover.engine.daily_step` for the order of operations and what
is deliberately still out of scope (backlog is never repaid from later
surplus stock in this module).
"""

from __future__ import annotations

import numpy as np

from daysofcover.engine.daily_step import advance_one_day
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
    reports = []
    for day in range(7):
        report = advance_one_day(
            state=state,
            shipments=shipments,
            production_queue=production_queue,
            plant_node_id="plant-1",
            component_part_id="part-a",
            finished_sku_id="sku-a",
            inbound_lane_id="lane-1",
            bom=bom,
            capacity_per_week=7_000.0,
            batch_size=1.0,
            production_lead_time_days=3.0,
            daily_demand=10.0,
            current_day=day,
        )
        reports.append(report)

    plant = state.node_index("plant-1")
    component_idx = state.part_index("part-a")
    sku_idx = state.sku_index("sku-a")

    # day 2: the 50-unit shipment arrives and all of it starts production
    assert reports[2].components_received == 50.0
    assert reports[2].production_started == 50.0
    assert reports[2].demand_met == 0.0

    # day 5: that batch (3-day lead time from day 2) completes and meets
    # that day's demand
    assert reports[5].finished_goods_completed == 50.0
    assert reports[5].demand_met == 10.0

    # every component that arrived went into that single batch
    assert state.on_hand[plant, component_idx] == 0.0
    assert production_queue.outstanding() == 0.0

    # demand was unmet on days 0, 1, 2, 3 and 4 (50.0), then met on days 5 and 6
    assert state.finished_backlog[plant, sku_idx] == 50.0
    # 50 units produced, 10 sold on day 5 and 10 on day 6, 30 left on the shelf
    assert state.finished_on_hand[plant, sku_idx] == 30.0
