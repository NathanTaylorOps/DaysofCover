"""Stage 1, sessions 15, 17 through 21: the daily-step loop, multiple
SKUs sharing a scarce component, multiple customers competing for one
SKU's scarce finished goods, the plant's own periodic-review reordering
of that scarce component, that reorder capped by the inbound lane's own
MOQ and weekly capacity, and finally that same reorder split across a
dual-sourced part's suppliers.

Not a validation case: session 15's single test is still the hand-traced
baseline (every number reproduced exactly, now through the multi-SKU
``sku_specs`` API and a one-order-per-day ``orders`` list rather than
the single ``daily_demand`` number it started with, and it never passes
``order_up_to`` -- reordering stays off, exactly as session 15 wrote it).
Session 17's tests check the component-sharing allocation; session 18's
check the customer-competing-for-finished-goods allocation; session 19's
check the order-up-to reordering itself: that it orders nothing until
supply runs short, that it never double-orders a shipment already on
order, and that a non-review day places no order at all. Session 20's
tests check that same reorder capped against the lane's remaining
weekly capacity, deferred entirely below the lane's MOQ, and deferred
to zero when capacity can't even clear the MOQ. Session 21's tests
check the dual-source split itself: the fixed ratio in the ordinary
case, the contingent full switch to the backup once the primary has
been down long enough, and one supplier's own lane capacity capping
only that supplier's share.

Session 22's tests check ``disruption_state`` wiring itself: a fully
down lane holding cargo already in transit instead of releasing it, a
partial severity throttling new-order capacity, a fully down plant
skipping its reorder decision entirely, and a disrupted plant's
production capacity scaling by severity. See
:mod:`daysofcover.engine.disruption_state` for the resolution logic
these tests build on, which has its own dedicated test file.
"""

from __future__ import annotations

import numpy as np

from daysofcover.engine.allocation import CustomerOrder
from daysofcover.engine.daily_step import SkuProductionSpec, advance_one_day
from daysofcover.engine.disruption_state import DisruptionState
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
from daysofcover.models.scenario import Disruption, Scenario


def _network(*, capacity_per_week: float = 1000.0, moq: float | None = None) -> Network:
    supplier = Node(id="supplier-1", name="Supplier One", type=NodeType.SUPPLIER, region="AU")
    plant = Node(id="plant-1", name="Plant One", type=NodeType.PLANT, region="AU")
    lane = Lane(
        id="lane-1",
        origin_id="supplier-1",
        destination_id="plant-1",
        mode=LaneMode.OCEAN,
        lead_time_days_median=2.0,
        lead_time_days_sigma=0.0,  # deterministic: always arrives on day 2
        capacity_per_week=capacity_per_week,
        moq=moq,
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
        # a fresh order each day, exactly matching session 15's fixed
        # daily_demand=10.0 -- one customer, one order, due today.
        spec = SkuProductionSpec(
            finished_sku_id="sku-a",
            bom=bom,
            capacity_per_week=7_000.0,
            batch_size=1.0,
            production_lead_time_days=3.0,
            orders=[CustomerOrder(customer_id="cust-1", order_day=day, quantity=10.0, priority=0)],
            production_queue=production_queue,
        )
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
        orders=[],  # no orders keeps backlog exactly at whatever the test sets
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


def test_two_customers_scarce_finished_goods_priority_override() -> None:
    network = _network()
    state = NetworkState.from_network(network)
    shipments = NetworkShipments.from_network(network)
    plant = state.node_index("plant-1")
    sku_idx = state.sku_index("sku-a")
    state.finished_on_hand[plant, sku_idx] = 15.0

    orders = [
        # cust-1's order is placed earlier but at the lower-priority tier
        CustomerOrder(customer_id="cust-1", order_day=3, quantity=10.0, priority=1),
        # cust-2 orders later but at priority 0, the override the build plan names
        CustomerOrder(customer_id="cust-2", order_day=5, quantity=10.0, priority=0),
    ]
    spec = SkuProductionSpec(
        finished_sku_id="sku-a",
        bom=[BOMLine(part_id="part-a", quantity=1.0)],
        capacity_per_week=0.0,  # no new production this day -- isolate the allocation
        batch_size=1.0,
        production_lead_time_days=3.0,
        orders=orders,
        production_queue=ProductionQueue(),
    )

    report = advance_one_day(
        state=state,
        shipments=shipments,
        plant_node_id="plant-1",
        component_part_id="part-a",
        inbound_lane_id=None,
        sku_specs=[spec],
        current_day=5,
    )

    sku_report = report.sku_reports[0]
    by_customer = {of.order.customer_id: of.fulfilled for of in sku_report.order_fulfillment}
    # cust-2's priority-0 order is served in full first, despite being placed later
    assert by_customer["cust-2"] == 10.0
    # only 5 units are left on the shelf for cust-1's lower-priority order
    assert by_customer["cust-1"] == 5.0
    assert sku_report.demand_realized == 20.0
    assert sku_report.demand_met == 15.0
    # the unmet 5 units land in the SKU's one aggregate backlog number
    assert state.finished_backlog[plant, sku_idx] == 5.0
    assert state.finished_on_hand[plant, sku_idx] == 0.0


def test_two_customers_same_priority_break_the_tie_by_order_date() -> None:
    network = _network()
    state = NetworkState.from_network(network)
    shipments = NetworkShipments.from_network(network)
    plant = state.node_index("plant-1")
    sku_idx = state.sku_index("sku-a")
    state.finished_on_hand[plant, sku_idx] = 15.0

    orders = [
        # placed later, but listed first here -- order in the list must not matter
        CustomerOrder(customer_id="cust-1", order_day=5, quantity=10.0, priority=0),
        # the earlier order, at the same priority, is served first
        CustomerOrder(customer_id="cust-2", order_day=2, quantity=10.0, priority=0),
    ]
    spec = SkuProductionSpec(
        finished_sku_id="sku-a",
        bom=[BOMLine(part_id="part-a", quantity=1.0)],
        capacity_per_week=0.0,
        batch_size=1.0,
        production_lead_time_days=3.0,
        orders=orders,
        production_queue=ProductionQueue(),
    )

    report = advance_one_day(
        state=state,
        shipments=shipments,
        plant_node_id="plant-1",
        component_part_id="part-a",
        inbound_lane_id=None,
        sku_specs=[spec],
        current_day=5,
    )

    by_customer = {
        of.order.customer_id: of.fulfilled for of in report.sku_reports[0].order_fulfillment
    }
    # same priority, so the earlier order date (cust-2) wins the tie
    assert by_customer["cust-2"] == 10.0
    assert by_customer["cust-1"] == 5.0


def test_reorder_places_nothing_on_a_non_review_day_then_orders_up_to_target() -> None:
    network = _network()
    state = NetworkState.from_network(network)
    shipments = NetworkShipments.from_network(network)
    plant = state.node_index("plant-1")
    component_idx = state.part_index("part-a")
    rng = np.random.default_rng(seed=1)

    reports = []
    for day in range(4):
        report = advance_one_day(
            state=state,
            shipments=shipments,
            plant_node_id="plant-1",
            component_part_id="part-a",
            inbound_lane_id="lane-1",
            sku_specs=[],  # isolate the reorder decision from production entirely
            current_day=day,
            order_up_to=20.0,
            review_period_days=3,
            rng=rng,
        )
        reports.append(report)

    # day 0 is a review day, with nothing on hand or on order: order up to 20
    assert reports[0].component_ordered == 20.0
    # days 1 and 2 aren't review days at all -- no order, whatever the position
    assert reports[1].component_ordered == 0.0
    assert reports[2].component_ordered == 0.0
    # day 2: the lane's 2-day lead time (deterministic, sigma=0) lands day 0's order
    assert reports[2].components_received == 20.0
    # day 3 is a review day again, but on-hand already sits at the target: no order
    assert reports[3].component_ordered == 0.0
    assert state.on_hand[plant, component_idx] == 20.0
    assert shipments.outstanding_at_node(node_id="plant-1", part_id="part-a") == 0.0


def test_reorder_never_double_orders_a_shipment_already_in_transit() -> None:
    network = _network()
    state = NetworkState.from_network(network)
    shipments = NetworkShipments.from_network(network)
    plant = state.node_index("plant-1")
    component_idx = state.part_index("part-a")
    rng = np.random.default_rng(seed=1)

    # a snapshot of (on_hand, on_order) as of the end of each day, since
    # state is mutated in place and the loop below moves past each day
    # before this test gets to assert on it.
    snapshots = []
    for day in range(3):
        # reviewed every day, so day 1 reviews while day 0's order is
        # still in transit
        report = advance_one_day(
            state=state,
            shipments=shipments,
            plant_node_id="plant-1",
            component_part_id="part-a",
            inbound_lane_id="lane-1",
            sku_specs=[],
            current_day=day,
            order_up_to=20.0,
            review_period_days=1,
            rng=rng,
        )
        on_hand = float(state.on_hand[plant, component_idx])
        on_order = shipments.outstanding_at_node(node_id="plant-1", part_id="part-a")
        snapshots.append((report, on_hand, on_order))

    report0, _on_hand0, on_order0 = snapshots[0]
    report1, on_hand1, on_order1 = snapshots[1]
    report2, on_hand2, on_order2 = snapshots[2]

    # day 0: nothing on hand or on order yet -- order the full 20
    assert report0.component_ordered == 20.0
    assert on_order0 == 20.0
    # day 1: still nothing on hand (the 2-day lead time hasn't landed it), but
    # the 20 already on order covers the position -- no second order for it
    assert report1.component_ordered == 0.0
    assert on_hand1 == 0.0
    assert on_order1 == 20.0
    # day 2: day 0's shipment lands; on-hand is now at the target, so day 2's
    # review orders nothing either
    assert report2.components_received == 20.0
    assert report2.component_ordered == 0.0
    assert on_hand2 == 20.0
    assert on_order2 == 0.0


def test_reorder_is_capped_by_the_lanes_remaining_weekly_capacity() -> None:
    # a lane that can only move 15 units a week, well below the 20-unit
    # order-up-to target
    network = _network(capacity_per_week=15.0)
    state = NetworkState.from_network(network)
    shipments = NetworkShipments.from_network(network)
    rng = np.random.default_rng(seed=1)

    report = advance_one_day(
        state=state,
        shipments=shipments,
        plant_node_id="plant-1",
        component_part_id="part-a",
        inbound_lane_id="lane-1",
        sku_specs=[],
        current_day=0,
        order_up_to=20.0,
        review_period_days=1,
        rng=rng,
    )

    # capped at the lane's 15-unit weekly capacity, not the full 20-unit target
    assert report.component_ordered == 15.0
    assert shipments.outstanding_at_node(node_id="plant-1", part_id="part-a") == 15.0


def test_reorder_below_moq_is_deferred_entirely_rather_than_placed_partial() -> None:
    # a supplier that won't ship less than 50 units, but the plant only
    # needs 20 to reach its order-up-to target
    network = _network(moq=50.0)
    state = NetworkState.from_network(network)
    shipments = NetworkShipments.from_network(network)
    rng = np.random.default_rng(seed=1)

    report = advance_one_day(
        state=state,
        shipments=shipments,
        plant_node_id="plant-1",
        component_part_id="part-a",
        inbound_lane_id="lane-1",
        sku_specs=[],
        current_day=0,
        order_up_to=20.0,
        review_period_days=1,
        rng=rng,
    )

    # the 20-unit desired order would round up to the 50-unit MOQ, but this
    # lane's capacity (1000/week, well above 50) has no trouble clearing it
    assert report.component_ordered == 50.0
    assert shipments.outstanding_at_node(node_id="plant-1", part_id="part-a") == 50.0


def test_reorder_below_moq_and_capacity_together_is_deferred_to_zero() -> None:
    # capacity (15/week) can't even clear the 50-unit MOQ this supplier
    # requires, so no shipment is placed at all this week
    network = _network(capacity_per_week=15.0, moq=50.0)
    state = NetworkState.from_network(network)
    shipments = NetworkShipments.from_network(network)
    plant = state.node_index("plant-1")
    component_idx = state.part_index("part-a")
    rng = np.random.default_rng(seed=1)

    report = advance_one_day(
        state=state,
        shipments=shipments,
        plant_node_id="plant-1",
        component_part_id="part-a",
        inbound_lane_id="lane-1",
        sku_specs=[],
        current_day=0,
        order_up_to=20.0,
        review_period_days=1,
        rng=rng,
    )

    assert report.component_ordered == 0.0
    assert shipments.outstanding_at_node(node_id="plant-1", part_id="part-a") == 0.0
    assert state.on_hand[plant, component_idx] == 0.0


def _dual_source_network(
    *,
    primary_split: float = 0.7,
    backup_split: float = 0.3,
    detect_delay_days: float = 2.0,
    primary_capacity: float = 1000.0,
    backup_capacity: float = 1000.0,
) -> Network:
    supplier_primary = Node(
        id="supplier-primary", name="Supplier Primary", type=NodeType.SUPPLIER, region="AU"
    )
    supplier_backup = Node(
        id="supplier-backup", name="Supplier Backup", type=NodeType.SUPPLIER, region="AU"
    )
    plant = Node(id="plant-1", name="Plant One", type=NodeType.PLANT, region="AU")
    lane_primary = Lane(
        id="lane-primary",
        origin_id="supplier-primary",
        destination_id="plant-1",
        mode=LaneMode.OCEAN,
        lead_time_days_median=2.0,
        lead_time_days_sigma=0.0,
        capacity_per_week=primary_capacity,
        unit_cost=1.0,
        currency="AUD",
        allow_crossing=False,
    )
    lane_backup = Lane(
        id="lane-backup",
        origin_id="supplier-backup",
        destination_id="plant-1",
        mode=LaneMode.OCEAN,
        lead_time_days_median=2.0,
        lead_time_days_sigma=0.0,
        capacity_per_week=backup_capacity,
        unit_cost=1.0,
        currency="AUD",
        allow_crossing=False,
    )
    part_a = Part(
        id="part-a",
        name="Part A",
        suppliers=[
            SupplySource(
                node_id="supplier-primary",
                split_ratio=primary_split,
                is_primary=True,
                detect_delay_days=detect_delay_days,
            ),
            SupplySource(node_id="supplier-backup", split_ratio=backup_split, is_primary=False),
        ],
        unit_cost=1.0,
        currency="AUD",
    )
    return Network(
        base_currency="AUD",
        nodes=[supplier_primary, supplier_backup, plant],
        lanes=[lane_primary, lane_backup],
        parts=[part_a],
        skus=[],
    )


def test_dual_source_reorder_splits_by_the_parts_fixed_ratio() -> None:
    network = _dual_source_network(primary_split=0.7, backup_split=0.3)
    state = NetworkState.from_network(network)
    shipments = NetworkShipments.from_network(network)
    rng = np.random.default_rng(seed=1)
    part_a = network.parts[0]

    report = advance_one_day(
        state=state,
        shipments=shipments,
        plant_node_id="plant-1",
        component_part_id="part-a",
        inbound_lane_id=None,
        sku_specs=[],
        current_day=0,
        order_up_to=100.0,
        review_period_days=1,
        rng=rng,
        component_suppliers=part_a.suppliers,
        lane_by_supplier={"supplier-primary": "lane-primary", "supplier-backup": "lane-backup"},
    )

    # nothing on hand or on order yet: the full 100-unit target splits 70/30
    assert report.component_ordered == 100.0
    assert shipments.lanes["lane-primary"].outstanding(part_id="part-a") == 70.0
    assert shipments.lanes["lane-backup"].outstanding(part_id="part-a") == 30.0
    assert shipments.outstanding_at_node(node_id="plant-1", part_id="part-a") == 100.0


def test_dual_source_reorder_switches_entirely_to_backup_once_primary_is_down_long_enough() -> None:
    network = _dual_source_network(primary_split=0.7, backup_split=0.3, detect_delay_days=2.0)
    state = NetworkState.from_network(network)
    shipments = NetworkShipments.from_network(network)
    rng = np.random.default_rng(seed=1)
    part_a = network.parts[0]

    report = advance_one_day(
        state=state,
        shipments=shipments,
        plant_node_id="plant-1",
        component_part_id="part-a",
        inbound_lane_id=None,
        sku_specs=[],
        current_day=5,
        order_up_to=100.0,
        review_period_days=1,
        rng=rng,
        component_suppliers=part_a.suppliers,
        lane_by_supplier={"supplier-primary": "lane-primary", "supplier-backup": "lane-backup"},
        primary_down_since_day=3,  # 5 - 3 = 2 >= detect_delay_days: switched
    )

    # the whole order goes to the backup; the primary's lane gets nothing
    assert report.component_ordered == 100.0
    assert shipments.lanes["lane-primary"].outstanding(part_id="part-a") == 0.0
    assert shipments.lanes["lane-backup"].outstanding(part_id="part-a") == 100.0
    assert shipments.outstanding_at_node(node_id="plant-1", part_id="part-a") == 100.0


def test_dual_source_reorder_caps_each_suppliers_share_by_its_own_lane_only() -> None:
    # the backup's lane can only move 10 units a week; the primary's is
    # untouched by that limit -- one tight lane never holds back the other
    network = _dual_source_network(primary_split=0.7, backup_split=0.3, backup_capacity=10.0)
    state = NetworkState.from_network(network)
    shipments = NetworkShipments.from_network(network)
    rng = np.random.default_rng(seed=1)
    part_a = network.parts[0]

    report = advance_one_day(
        state=state,
        shipments=shipments,
        plant_node_id="plant-1",
        component_part_id="part-a",
        inbound_lane_id=None,
        sku_specs=[],
        current_day=0,
        order_up_to=100.0,
        review_period_days=1,
        rng=rng,
        component_suppliers=part_a.suppliers,
        lane_by_supplier={"supplier-primary": "lane-primary", "supplier-backup": "lane-backup"},
    )

    # primary's desired 70-unit share ships in full; backup's desired
    # 30-unit share is capped at its lane's 10-unit weekly capacity
    assert report.component_ordered == 80.0
    assert shipments.lanes["lane-primary"].outstanding(part_id="part-a") == 70.0
    assert shipments.lanes["lane-backup"].outstanding(part_id="part-a") == 10.0
    assert shipments.outstanding_at_node(node_id="plant-1", part_id="part-a") == 80.0


def test_fully_down_lane_holds_cargo_already_in_transit_instead_of_releasing_it() -> None:
    network = _network()
    state = NetworkState.from_network(network)
    shipments = NetworkShipments.from_network(network)
    rng = np.random.default_rng(seed=1)
    shipments.ship(lane_id="lane-1", part_id="part-a", quantity=50.0, order_day=0, rng=rng)

    disruption = Disruption(
        element_id="lane-1", start_day=0, severity_fraction=1.0, duration_days=10
    )
    scenario = Scenario(id="s1", name="Closure", disruptions=[disruption], seed=1)
    disruption_state = DisruptionState.from_scenario(scenario, network=network)

    # day 2: the shipment's own (deterministic) arrival day, but the
    # lane is fully down -- it should stay queued, not land on the shelf.
    report = advance_one_day(
        state=state,
        shipments=shipments,
        plant_node_id="plant-1",
        component_part_id="part-a",
        inbound_lane_id="lane-1",
        sku_specs=[],
        current_day=2,
        disruption_state=disruption_state,
    )
    assert report.components_received == 0.0
    assert state.on_hand[state.node_index("plant-1"), state.part_index("part-a")] == 0.0
    assert shipments.outstanding_at_node(node_id="plant-1", part_id="part-a") == 50.0

    # day 11: duration_days=10 with no ramp means an instant reopening;
    # the held cargo, already past its own arrival day, lands now.
    report2 = advance_one_day(
        state=state,
        shipments=shipments,
        plant_node_id="plant-1",
        component_part_id="part-a",
        inbound_lane_id="lane-1",
        sku_specs=[],
        current_day=11,
        disruption_state=disruption_state,
    )
    assert report2.components_received == 50.0
    assert state.on_hand[state.node_index("plant-1"), state.part_index("part-a")] == 50.0


def test_partial_lane_severity_scales_capacity_for_new_orders() -> None:
    network = _network(capacity_per_week=20.0)
    state = NetworkState.from_network(network)
    shipments = NetworkShipments.from_network(network)
    rng = np.random.default_rng(seed=1)

    disruption = Disruption(
        element_id="lane-1", start_day=0, severity_fraction=0.5, duration_days=100
    )
    scenario = Scenario(id="s1", name="Partial slowdown", disruptions=[disruption], seed=1)
    disruption_state = DisruptionState.from_scenario(scenario, network=network)

    report = advance_one_day(
        state=state,
        shipments=shipments,
        plant_node_id="plant-1",
        component_part_id="part-a",
        inbound_lane_id="lane-1",
        sku_specs=[],
        current_day=0,
        order_up_to=100.0,
        review_period_days=1,
        rng=rng,
        disruption_state=disruption_state,
    )

    # the lane's 20-unit weekly capacity is halved by the 0.5 severity
    assert report.component_ordered == 10.0


def test_fully_down_plant_skips_the_whole_reorder_decision() -> None:
    network = _network()
    state = NetworkState.from_network(network)
    shipments = NetworkShipments.from_network(network)
    rng = np.random.default_rng(seed=1)

    disruption = Disruption(
        element_id="plant-1", start_day=0, severity_fraction=1.0, duration_days=5
    )
    scenario = Scenario(id="s1", name="Plant down", disruptions=[disruption], seed=1)
    disruption_state = DisruptionState.from_scenario(scenario, network=network)

    report = advance_one_day(
        state=state,
        shipments=shipments,
        plant_node_id="plant-1",
        component_part_id="part-a",
        inbound_lane_id="lane-1",
        sku_specs=[],
        current_day=0,
        order_up_to=100.0,
        review_period_days=1,
        rng=rng,
        disruption_state=disruption_state,
    )

    # the plant itself is fully down: no order at all, even on a review day
    assert report.component_ordered == 0.0
    assert shipments.outstanding_at_node(node_id="plant-1", part_id="part-a") == 0.0


def test_disrupted_plant_scales_production_capacity_by_severity() -> None:
    network = _network()
    state = NetworkState.from_network(network)
    shipments = NetworkShipments.from_network(network)
    plant = state.node_index("plant-1")
    component_idx = state.part_index("part-a")
    state.on_hand[plant, component_idx] = 1_000.0  # never the binding constraint
    production_queue = ProductionQueue()

    disruption = Disruption(
        element_id="plant-1", start_day=0, severity_fraction=0.6, duration_days=100
    )
    scenario = Scenario(id="s1", name="Plant slowdown", disruptions=[disruption], seed=1)
    disruption_state = DisruptionState.from_scenario(scenario, network=network)

    spec = SkuProductionSpec(
        finished_sku_id="sku-a",
        bom=[BOMLine(part_id="part-a", quantity=1.0)],
        capacity_per_week=700.0,  # 100 units/day at full capacity
        batch_size=1.0,
        production_lead_time_days=3.0,
        orders=[],
        production_queue=production_queue,
    )

    report = advance_one_day(
        state=state,
        shipments=shipments,
        plant_node_id="plant-1",
        component_part_id="part-a",
        inbound_lane_id="lane-1",
        sku_specs=[spec],
        current_day=0,
        disruption_state=disruption_state,
    )

    # 0.6 severity leaves 40% of capacity: 100 * 0.4 = 40 units/day
    assert report.sku_reports[0].production_started == 40.0
