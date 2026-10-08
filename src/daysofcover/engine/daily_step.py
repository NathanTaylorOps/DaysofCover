"""Advance the multi-node supply-network state by one operating day.

This module composes shipment arrivals, production, shared-component
allocation, customer fulfilment and periodic component replenishment.

Replenishment uses the ending inventory position (on-hand plus outstanding
shipments) to avoid ordering stock already in transit. Orders are subject
to each lane's minimum order quantity and remaining weekly capacity.
When multiple suppliers are configured, the replenishment quantity follows
the configured sourcing split or a contingent switch informed by disruption
state. Each supplier lane is constrained independently.

Optional distribution-tree routing moves completed products through the
configured distribution network before customer fulfilment. Without that
routing, the engine retains the direct plant-fulfilment behaviour for
backwards compatibility. Missing customer routes fall back to the plant.

Backlog is maintained in aggregate by node and SKU, not as a persistent
per-customer order ledger. Within-day allocation rules can prioritise
orders, but future-day fulfilment cannot recover the original customer
ordering sequence from aggregate backlog. This is a modelling limitation,
not an individual-order scheduling system.

The simulation state, shipment records, disruption model and allocation
policies are implemented in their respective modules; this function
coordinates them without replacing their validation contracts.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from daysofcover.engine.allocation import (
    CustomerOrder,
    allocate_by_backlog_proportion,
    allocate_by_margin_priority,
    allocate_finished_goods_to_orders,
    supplier_split_ratios,
)
from daysofcover.engine.disruption_state import DisruptionState
from daysofcover.engine.distribution import DistributionTree, push_finished_goods
from daysofcover.engine.production import (
    ProductionQueue,
    consume_components,
    feasible_production_units,
)
from daysofcover.engine.shipments import NetworkShipments, cap_order_quantity
from daysofcover.engine.state import NetworkState
from daysofcover.models.network import BOMLine, SupplySource

_UNLIMITED = float("inf")


@dataclass(frozen=True)
class SkuProductionSpec:
    """One SKU's production inputs for a shared-plant daily step.

    ``production_queue`` is mutated in place across days -- it is the
    same object the caller keeps between calls. ``margin_fraction`` is
    only read when ``allocation_rule="margin_priority"``; it is simplest
    to carry directly on the spec (matching
    :attr:`daysofcover.models.network.SKU.margin_fraction`) rather than
    as a separate parallel mapping. ``orders`` is this SKU's customer
    orders due *today* -- a fresh list each call, the same way a real
    day's orders would differ from the last.
    """

    finished_sku_id: str
    bom: list[BOMLine]
    capacity_per_week: float
    batch_size: float
    production_lead_time_days: float
    orders: list[CustomerOrder]
    production_queue: ProductionQueue
    margin_fraction: float = 0.0


@dataclass(frozen=True)
class OrderFulfillment:
    """One customer order's outcome on one day, alongside the order itself."""

    order: CustomerOrder
    fulfilled: float


@dataclass(frozen=True)
class SkuDayReport:
    """What happened for one SKU, at one plant, on one day."""

    finished_sku_id: str
    finished_goods_completed: float
    demand_realized: float
    demand_met: float
    production_started: float
    order_fulfillment: tuple[OrderFulfillment, ...]


@dataclass(frozen=True)
class DailyStepReport:
    """What happened at one plant, across every SKU it produces, on one day."""

    components_received: float
    component_ordered: float
    sku_reports: tuple[SkuDayReport, ...]


def advance_one_day(
    *,
    state: NetworkState,
    shipments: NetworkShipments,
    plant_node_id: str,
    component_part_id: str,
    inbound_lane_id: str | None,
    sku_specs: list[SkuProductionSpec],
    current_day: int,
    allocation_rule: str = "backlog_proportion",
    order_up_to: float | None = None,
    review_period_days: int | None = None,
    rng: np.random.Generator | None = None,
    component_suppliers: list[SupplySource] | None = None,
    lane_by_supplier: dict[str, str] | None = None,
    primary_down_since_day: int | None = None,
    disruption_state: DisruptionState | None = None,
    distribution: DistributionTree | None = None,
) -> DailyStepReport:
    """Advance one plant, across every SKU in ``sku_specs``, by one day.

    ``allocation_rule`` is ``"backlog_proportion"`` (the default) or
    ``"margin_priority"`` -- the build plan's own "with margin priority
    as an option" -- and selects which of session 16's two SKU-facing
    allocation functions splits ``component_part_id`` when more than one
    spec's BOM references it.

    ``order_up_to`` and ``review_period_days`` together turn on the
    plant's own periodic-review reordering of ``component_part_id``,
    described in the module docstring; leaving either as ``None`` (the
    default) leaves reordering off entirely, exactly as every earlier
    session called this function.

    ``component_suppliers`` (``component_part_id``'s own
    :attr:`daysofcover.models.network.Part.suppliers` list) is ``None``
    by default, which keeps reordering on the single ``inbound_lane_id``
    exactly as sessions 19 and 20 wrote it. Passing it turns on the
    dual-source split described in the module docstring instead, and
    requires ``lane_by_supplier`` (each supplier's node id mapped to the
    lane it ships ``component_part_id`` on into this plant); in that
    case ``inbound_lane_id`` is ignored entirely, for both receiving and
    ordering. ``primary_down_since_day`` is passed straight through to
    :func:`daysofcover.engine.allocation.supplier_split_ratios`.

    When reordering is on and today is a review day, ``rng`` is required
    if any lane's own share of the desired order (after that lane's own
    MOQ and remaining weekly capacity cap it) comes out positive -- it
    is that lane's own lognormal lead-time draw, the same as any other
    call to :meth:`~daysofcover.engine.shipments.NetworkShipments.ship`.

    ``disruption_state`` is ``None`` by default, which leaves every
    earlier session's call exactly as it was -- see the module
    docstring for what turning it on changes: held-back receiving for a
    fully closed lane, severity-scaled capacity for a partial one, a
    fully-down plant skipping its own reorder decision, and
    severity-scaled production capacity for every SKU at this plant.

    ``distribution`` is ``None`` by default, which fulfils every order
    at the plant directly, exactly as every earlier session did. Given
    a real :class:`daysofcover.engine.distribution.DistributionTree`,
    today's production is pushed down it before any order is filled,
    and each order is served at its own customer's node when the tree
    knows one, the plant otherwise -- see the module docstring. When a
    push needs to place a shipment, ``rng`` is required the same way
    the reorder decision above requires it.

    See the module docstring for order of operations.
    """
    plant = state.node_index(plant_node_id)
    component_idx = state.part_index(component_part_id)

    # component_suppliers on means every lane in lane_by_supplier, and
    # inbound_lane_id is ignored entirely -- see the module docstring.
    receive_lane_ids: list[str] = (
        list(lane_by_supplier.values())
        if component_suppliers is not None and lane_by_supplier is not None
        else ([inbound_lane_id] if inbound_lane_id is not None else [])
    )
    components_received = 0.0
    for lane_id in receive_lane_ids:
        # a fully closed lane holds whatever has already arrived rather
        # than releasing it -- see disruption_state.py's module
        # docstring for why this is a binary check, not proportional.
        if disruption_state is not None and disruption_state.is_fully_down(
            element_id=lane_id, day=current_day
        ):
            continue
        components_received += shipments.receive(
            lane_id=lane_id, part_id=component_part_id, current_day=current_day
        )
    if receive_lane_ids:
        state.on_hand[plant, component_idx] += components_received

    # 1. every SKU's due production completes; then, if a distribution
    #    tree was given, today's newly-landed inventory is pushed one
    #    hop further downstream at every node on the tree (see
    #    distribution.py's module docstring for why this is push, not
    #    pull, and why it happens before fulfillment, not after); then
    #    today's customer orders are allocated against whatever is
    #    actually on the shelf where that customer sits -- the plant
    #    itself when distribution is None (every earlier session's
    #    behaviour, unchanged) or that customer's own node when it
    #    isn't and that node exists. Orders are served by ascending
    #    priority, then FIFO by order date, exactly as before; backlog
    #    is now tracked per (node, sku), not always at the plant --
    #    still an aggregate per node, not per customer: see the module
    #    docstring for what that still can't do.
    finished_goods_completed_by_sku: dict[str, float] = {}
    for spec in sku_specs:
        sku_idx = state.sku_index(spec.finished_sku_id)
        finished_goods_completed = spec.production_queue.complete(current_day=current_day)
        state.finished_on_hand[plant, sku_idx] += finished_goods_completed
        finished_goods_completed_by_sku[spec.finished_sku_id] = finished_goods_completed

    if distribution is not None:
        for spec in sku_specs:
            push_finished_goods(
                state=state,
                shipments=shipments,
                tree=distribution,
                sku_id=spec.finished_sku_id,
                current_day=current_day,
                rng=rng,
                disruption_state=disruption_state,
            )

    def _fulfillment_node_id(customer_id: str) -> str:
        if distribution is not None and customer_id in distribution.path_by_customer:
            return customer_id
        return plant_node_id

    demand_met_by_sku: dict[str, float] = {}
    order_fulfillment_by_sku: dict[str, tuple[OrderFulfillment, ...]] = {}
    for spec in sku_specs:
        sku_idx = state.sku_index(spec.finished_sku_id)
        orders_by_node: dict[str, list[CustomerOrder]] = {}
        for order in spec.orders:
            orders_by_node.setdefault(_fulfillment_node_id(order.customer_id), []).append(order)

        demand_met_total = 0.0
        order_fulfillment_all: list[OrderFulfillment] = []
        for node_id, node_orders in orders_by_node.items():
            node_idx = state.node_index(node_id)
            available_finished = float(state.finished_on_hand[node_idx, sku_idx])
            fulfilled = allocate_finished_goods_to_orders(
                available_quantity=available_finished, orders=node_orders
            )
            node_demand_met = sum(fulfilled)
            node_unmet = sum(order.quantity for order in node_orders) - node_demand_met
            state.finished_on_hand[node_idx, sku_idx] -= node_demand_met
            state.finished_backlog[node_idx, sku_idx] += node_unmet

            demand_met_total += node_demand_met
            order_fulfillment_all.extend(
                OrderFulfillment(order=order, fulfilled=quantity)
                for order, quantity in zip(node_orders, fulfilled, strict=True)
            )

        demand_met_by_sku[spec.finished_sku_id] = demand_met_total
        order_fulfillment_by_sku[spec.finished_sku_id] = tuple(order_fulfillment_all)

    # a fully or partially down plant produces at a scaled-down capacity
    # for every SKU, following the same linear-ramp shape ramp.py
    # already validated against case 12 -- see the module docstring.
    # 1.0 (no disruption_state, or none active for this node today) is
    # every earlier session's behaviour, unchanged.
    plant_capacity_fraction = 1.0
    if disruption_state is not None:
        plant_capacity_fraction = 1.0 - disruption_state.severity_at(
            element_id=plant_node_id, day=current_day
        )

    # 2. how much of the shared component each SKU would consume today
    #    if supply were unlimited, capped only by its own (disruption-
    #    scaled) capacity and batch size -- reuses feasible_production_
    #    units rather than re-deriving the same batch-rounding logic here.
    component_line_by_sku: dict[str, BOMLine] = {}
    requested_component_by_sku: dict[str, float] = {}
    for spec in sku_specs:
        component_line = next(
            (line for line in spec.bom if line.part_id == component_part_id), None
        )
        if component_line is None:
            continue
        component_line_by_sku[spec.finished_sku_id] = component_line
        unconstrained_units = feasible_production_units(
            capacity_per_week=spec.capacity_per_week * plant_capacity_fraction,
            on_hand_by_part={line.part_id: _UNLIMITED for line in spec.bom},
            bom=spec.bom,
            batch_size=spec.batch_size,
        )
        requested_component_by_sku[spec.finished_sku_id] = (
            unconstrained_units * component_line.quantity
        )

    allocated_component: dict[str, float] = {}
    if requested_component_by_sku:
        available_component = float(state.on_hand[plant, component_idx])
        if allocation_rule == "margin_priority":
            allocated_component = allocate_by_margin_priority(
                available_quantity=available_component,
                requested_by_sku=requested_component_by_sku,
                margin_by_sku={spec.finished_sku_id: spec.margin_fraction for spec in sku_specs},
            )
        else:
            backlog_by_sku = {
                spec.finished_sku_id: float(
                    state.finished_backlog[plant, state.sku_index(spec.finished_sku_id)]
                )
                for spec in sku_specs
            }
            allocated_component = allocate_by_backlog_proportion(
                available_quantity=available_component,
                requested_by_sku=requested_component_by_sku,
                backlog_by_sku=backlog_by_sku,
            )

    # 3. each SKU starts whatever its allocated share of the shared
    #    component, plus every other BOM line's real on-hand, actually
    #    supports -- a SKU whose BOM never touches component_part_id
    #    is unaffected by the allocation above and reads its own
    #    components' real on-hand directly.
    sku_reports = []
    for spec in sku_specs:
        if spec.finished_sku_id in component_line_by_sku:
            on_hand_by_part = {
                line.part_id: (
                    allocated_component[spec.finished_sku_id]
                    if line.part_id == component_part_id
                    else float(state.on_hand[plant, state.part_index(line.part_id)])
                )
                for line in spec.bom
            }
        else:
            on_hand_by_part = {
                line.part_id: float(state.on_hand[plant, state.part_index(line.part_id)])
                for line in spec.bom
            }

        feasible = feasible_production_units(
            capacity_per_week=spec.capacity_per_week * plant_capacity_fraction,
            on_hand_by_part=on_hand_by_part,
            bom=spec.bom,
            batch_size=spec.batch_size,
        )
        if feasible > 0:
            updated = consume_components(
                on_hand_by_part=on_hand_by_part, bom=spec.bom, units_produced=feasible
            )
            for line in spec.bom:
                idx = state.part_index(line.part_id)
                state.on_hand[plant, idx] = updated[line.part_id]
            spec.production_queue.start(
                quantity=feasible,
                start_day=current_day,
                lead_time_days=spec.production_lead_time_days,
            )

        sku_reports.append(
            SkuDayReport(
                finished_sku_id=spec.finished_sku_id,
                finished_goods_completed=finished_goods_completed_by_sku[spec.finished_sku_id],
                demand_realized=sum(order.quantity for order in spec.orders),
                demand_met=demand_met_by_sku[spec.finished_sku_id],
                production_started=feasible,
                order_fulfillment=order_fulfillment_by_sku[spec.finished_sku_id],
            )
        )

    # 4. the plant's own periodic-review order-up-to decision for
    #    component_part_id, made last so it sees today's true ending
    #    inventory position -- on-hand plus whatever is already on
    #    order (read from the real shipment records, never a separate
    #    counter -- see state.py's module docstring), so a shipment
    #    already in the pipeline is never ordered again. Off entirely
    #    when order_up_to or review_period_days is None, today is not a
    #    review day, or plant_node_id itself is fully down (the
    #    real-engine analog of case 4's order-pausing mechanic).
    #    component_suppliers is None (the default): the single-lane
    #    reorder from sessions 19 and 20, unchanged -- the desired
    #    quantity capped against inbound_lane_id's own moq and
    #    disruption-scaled remaining weekly capacity, a desired order
    #    that can't clear the moq even after capacity capping it
    #    deferred to zero rather than placed as a partial, sub-moq
    #    shipment. component_suppliers given: the same desired quantity
    #    is split across every supplier by supplier_split_ratios, then
    #    each supplier's own share is independently capped against that
    #    supplier's own (disruption-scaled) lane -- one supplier's tight
    #    lane never holds back another's.
    component_ordered = 0.0
    is_review_day = (
        order_up_to is not None
        and review_period_days is not None
        and current_day % review_period_days == 0
        and not (
            disruption_state is not None
            and disruption_state.is_fully_down(element_id=plant_node_id, day=current_day)
        )
    )

    def _lane_capacity_remaining(lane_id: str) -> float:
        """A lane's own remaining weekly capacity, scaled by its current severity."""
        capacity = shipments.lanes[lane_id].capacity_remaining(current_day=current_day)
        if disruption_state is None:
            return capacity
        return capacity * (1.0 - disruption_state.severity_at(element_id=lane_id, day=current_day))

    if is_review_day and component_suppliers is not None:
        assert order_up_to is not None  # implied by is_review_day
        if lane_by_supplier is None:
            raise ValueError("lane_by_supplier is required when component_suppliers is given")
        position = float(state.on_hand[plant, component_idx]) + shipments.outstanding_at_node(
            node_id=plant_node_id, part_id=component_part_id
        )
        desired_quantity = max(0.0, order_up_to - position)
        ratios = supplier_split_ratios(
            suppliers=component_suppliers,
            primary_down_since_day=primary_down_since_day,
            current_day=current_day,
        )
        for supplier in component_suppliers:
            ratio = ratios.get(supplier.node_id, 0.0)
            if ratio <= 0:
                continue
            lane_id = lane_by_supplier[supplier.node_id]
            lane_shipments = shipments.lanes[lane_id]
            supplier_ordered = cap_order_quantity(
                desired_quantity=desired_quantity * ratio,
                moq=lane_shipments.lane.moq,
                capacity_remaining=_lane_capacity_remaining(lane_id),
            )
            if supplier_ordered > 0:
                if rng is None:
                    raise ValueError("rng is required when a review day's order-up-to is positive")
                shipments.ship(
                    lane_id=lane_id,
                    part_id=component_part_id,
                    quantity=supplier_ordered,
                    order_day=current_day,
                    rng=rng,
                )
                component_ordered += supplier_ordered
    elif is_review_day and inbound_lane_id is not None:
        assert order_up_to is not None  # implied by is_review_day
        position = float(state.on_hand[plant, component_idx]) + shipments.outstanding_at_node(
            node_id=plant_node_id, part_id=component_part_id
        )
        desired_quantity = max(0.0, order_up_to - position)
        lane_shipments = shipments.lanes[inbound_lane_id]
        component_ordered = cap_order_quantity(
            desired_quantity=desired_quantity,
            moq=lane_shipments.lane.moq,
            capacity_remaining=_lane_capacity_remaining(inbound_lane_id),
        )
        if component_ordered > 0:
            if rng is None:
                raise ValueError("rng is required when a review day's order-up-to is positive")
            shipments.ship(
                lane_id=inbound_lane_id,
                part_id=component_part_id,
                quantity=component_ordered,
                order_day=current_day,
                rng=rng,
            )

    return DailyStepReport(
        components_received=components_received,
        component_ordered=component_ordered,
        sku_reports=tuple(sku_reports),
    )
