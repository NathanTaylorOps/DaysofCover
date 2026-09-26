"""One day of the world: composing state, shipments, production and allocation.

Session 17 wired in the SKU-sharing-a-component allocation rule; session
18 wired in the customer-competing-for-finished-goods allocation rule.
This session takes the last item off that pair's original deferred
list: "reordering components to replenish the plant". Until now, the
plant's on-hand component stock only ever moved because a caller called
:meth:`daysofcover.engine.shipments.NetworkShipments.ship` directly --
every test so far has played that role itself; the plant never decided
to place an order. This session gives it that decision, in the simplest
form the build plan's own words support: "ordering reviewed weekly" --
a periodic-review, order-up-to policy, the same shape as session 12's
spike (:func:`daysofcover.engine.single_node.simulate_periodic_order_up_to`),
now placing a real shipment on a real lane instead of pushing a number
into a bare NumPy pipeline.

The order-up-to decision is made after everything else that day --
shipments have already arrived, every SKU's production for the day has
already started -- so it sees the day's true ending inventory position:
on-hand plus what's already on order (:attr:`daysofcover.engine.state.
NetworkState.on_order`, sized in session 12 but unused until now), never
double-ordering for a shipment already in the pipeline. On a non-review
day, or when ``order_up_to``/``review_period_days`` are left ``None``
(the default), nothing changes and every earlier session's calls still
work exactly as they always have.

Backlog is still tracked only in aggregate per (node, sku), not per
customer -- an order that goes unfulfilled today adds to the SKU's one
backlog number, and there is no record of *whose* order that was, so a
later day's surplus stock cannot be preferentially repaid to the
customer that has waited longest. That would need its own per-customer
backlog ledger, which is not this session's job.

Session 20 caps that order-up-to quantity against the inbound lane's
own ``moq`` and ``capacity_per_week`` (:func:`daysofcover.engine.
shipments.cap_order_quantity`), rather than always placing the full
desired order -- a real supplier will not ship less than its minimum
order quantity, and no lane ships more than its own weekly capacity
regardless of how badly the plant wants it. When the capped quantity
comes back as zero (an MOQ the desired order can't clear, or a week
already fully used), no shipment is placed at all and ``on_order`` is
left untouched -- the plant simply tries again on the next review day.

Session 21 wires in the last of session 16's three allocation
functions still sitting unused: :func:`daysofcover.engine.allocation.
supplier_split_ratios`. A dual-sourced part's reorder now splits across
every one of its suppliers' own lanes according to that function's
ratios -- normally the part's fixed ``split_ratio``\\ s, or, once the
primary has been down for at least its own ``detect_delay_days``, a
contingent full switch to the backup or backups. This is the single-
lane reorder from sessions 19 and 20 generalised to N suppliers, not
replaced by it: leaving the new ``component_suppliers`` parameter
``None`` (the default) keeps ordering on the single ``inbound_lane_id``
exactly as every earlier session wrote it. When it is given, each
supplier's own share is independently capped by that supplier's own
lane's MOQ and remaining weekly capacity -- one supplier's lane being
tight this week never holds back another's -- and ``inbound_lane_id``
plays no part in either receiving or ordering; every lane in ``lane_by
_supplier`` is read instead.

Deliberately out of scope, not forgotten: the per-customer backlog
ledger the paragraph above describes is still ahead, and so is
*detecting* a primary supplier as down in the first place -- that is a
disruption-modelling question (hazard groups, downtime semantics),
still ahead per the build plan's own milestone 3. This session only
wires in what happens once a caller already knows ``primary_down_since
_day``, exactly as :func:`supplier_split_ratios` itself only answers
that question given whatever the caller has already decided.
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
        components_received += shipments.receive(
            lane_id=lane_id, part_id=component_part_id, current_day=current_day
        )
    if receive_lane_ids:
        state.on_hand[plant, component_idx] += components_received
        state.on_order[plant, component_idx] = max(
            0.0, state.on_order[plant, component_idx] - components_received
        )

    # 1. every SKU's due production completes and today's customer
    #    orders are allocated against what's on the shelf -- served by
    #    ascending priority, then FIFO by order date -- before any new
    #    production is decided. Backlog stays an aggregate per (node,
    #    sku): see the module docstring for what that still can't do.
    finished_goods_completed_by_sku: dict[str, float] = {}
    demand_met_by_sku: dict[str, float] = {}
    order_fulfillment_by_sku: dict[str, tuple[OrderFulfillment, ...]] = {}
    for spec in sku_specs:
        sku_idx = state.sku_index(spec.finished_sku_id)
        finished_goods_completed = spec.production_queue.complete(current_day=current_day)
        state.finished_on_hand[plant, sku_idx] += finished_goods_completed

        available_finished = float(state.finished_on_hand[plant, sku_idx])
        fulfilled = allocate_finished_goods_to_orders(
            available_quantity=available_finished, orders=spec.orders
        )
        demand_realized = sum(order.quantity for order in spec.orders)
        demand_met = sum(fulfilled)
        unmet = demand_realized - demand_met
        state.finished_on_hand[plant, sku_idx] -= demand_met
        state.finished_backlog[plant, sku_idx] += unmet

        finished_goods_completed_by_sku[spec.finished_sku_id] = finished_goods_completed
        demand_met_by_sku[spec.finished_sku_id] = demand_met
        order_fulfillment_by_sku[spec.finished_sku_id] = tuple(
            OrderFulfillment(order=order, fulfilled=quantity)
            for order, quantity in zip(spec.orders, fulfilled, strict=True)
        )

    # 2. how much of the shared component each SKU would consume today
    #    if supply were unlimited, capped only by its own capacity and
    #    batch size -- reuses feasible_production_units rather than
    #    re-deriving the same batch-rounding logic here.
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
            capacity_per_week=spec.capacity_per_week,
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
            capacity_per_week=spec.capacity_per_week,
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
    #    order, so a shipment already in the pipeline is never ordered
    #    again. Off entirely when order_up_to or review_period_days is
    #    None, or today is not a review day. component_suppliers is
    #    None (the default): the single-lane reorder from sessions 19
    #    and 20, unchanged -- the desired quantity capped against
    #    inbound_lane_id's own moq and remaining weekly capacity, a
    #    desired order that can't clear the moq even after capacity
    #    capping it deferred to zero rather than placed as a partial,
    #    sub-moq shipment. component_suppliers given: the same desired
    #    quantity is split across every supplier by
    #    supplier_split_ratios, then each supplier's own share is
    #    independently capped against that supplier's own lane -- one
    #    supplier's tight lane never holds back another's.
    component_ordered = 0.0
    is_review_day = (
        order_up_to is not None
        and review_period_days is not None
        and current_day % review_period_days == 0
    )
    if is_review_day and component_suppliers is not None:
        assert order_up_to is not None  # implied by is_review_day
        if lane_by_supplier is None:
            raise ValueError("lane_by_supplier is required when component_suppliers is given")
        position = float(state.on_hand[plant, component_idx] + state.on_order[plant, component_idx])
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
                capacity_remaining=lane_shipments.capacity_remaining(current_day=current_day),
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
                state.on_order[plant, component_idx] += supplier_ordered
                component_ordered += supplier_ordered
    elif is_review_day and inbound_lane_id is not None:
        assert order_up_to is not None  # implied by is_review_day
        position = float(state.on_hand[plant, component_idx] + state.on_order[plant, component_idx])
        desired_quantity = max(0.0, order_up_to - position)
        lane_shipments = shipments.lanes[inbound_lane_id]
        component_ordered = cap_order_quantity(
            desired_quantity=desired_quantity,
            moq=lane_shipments.lane.moq,
            capacity_remaining=lane_shipments.capacity_remaining(current_day=current_day),
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
            state.on_order[plant, component_idx] += component_ordered

    return DailyStepReport(
        components_received=components_received,
        component_ordered=component_ordered,
        sku_reports=tuple(sku_reports),
    )
