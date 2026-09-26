"""One day of the world: composing state, shipments, production and allocation.

Sessions 12 to 15 built the pieces and composed them for one plant
producing one SKU from one component supplied over one lane. This
session takes the first item off that composition's own deferred list --
"multiple SKUs sharing a scarce component" -- and wires session 16's
:func:`daysofcover.engine.allocation.allocate_by_backlog_proportion` (or,
optionally, :func:`~daysofcover.engine.allocation.allocate_by_margin_priority`)
into the daily step itself.

Order of operations is unchanged from session 15's single-SKU version,
now applied per SKU: shipments arrive before anything else, so today's
arrivals count as available components; each SKU's due production
completes into finished goods before demand is realised, so a batch
finishing today can be sold the same day; demand then consumes finished
goods on hand and backlogs whatever it cannot. Only once every SKU's
demand has been served does the day decide how much of today's *new*
production each SKU gets to start -- and that decision, when more than
one SKU shares ``component_part_id``, now goes through the allocation
rule rather than each SKU simply grabbing what it can find on the shelf
in an arbitrary order.

The allocation only ever governs ``component_part_id``, the one shared
part this session generalises. Every other line in a SKU's BOM is still
read directly off the plant's real on-hand, unconstrained by any other
SKU's claim on it -- exactly session 15's behaviour, just not yet
extended to a second shared part. A SKU whose BOM does not reference
``component_part_id`` at all sits outside the allocation entirely and
produces however its own components allow.

Each SKU's "request" for its share of the scarce component is what it
would consume today if supply were unlimited -- capped only by its own
capacity and batch size, via :func:`daysofcover.engine.production.
feasible_production_units` called with an unlimited on-hand for every
part, so the same batch-rounding and capacity-capping logic is not
duplicated here.

Deliberately out of scope, not forgotten: multiple customers competing
for one SKU's scarce finished goods (session 16's ``allocate_finished_
goods_to_orders``, not yet wired in -- today's demand is still a single
number per SKU, not a list of customer orders), and reordering
components to replenish the plant, are both still ahead.
"""

from __future__ import annotations

from dataclasses import dataclass

from daysofcover.engine.allocation import (
    allocate_by_backlog_proportion,
    allocate_by_margin_priority,
)
from daysofcover.engine.production import (
    ProductionQueue,
    consume_components,
    feasible_production_units,
)
from daysofcover.engine.shipments import NetworkShipments
from daysofcover.engine.state import NetworkState
from daysofcover.models.network import BOMLine

_UNLIMITED = float("inf")


@dataclass(frozen=True)
class SkuProductionSpec:
    """One SKU's production inputs for a shared-plant daily step.

    ``production_queue`` is mutated in place across days -- it is the
    same object the caller keeps between calls, exactly as session 15's
    single ``production_queue`` argument was. ``margin_fraction`` is
    only read when ``allocation_rule="margin_priority"``; it is simplest
    to carry directly on the spec (matching
    :attr:`daysofcover.models.network.SKU.margin_fraction`) rather than
    as a separate parallel mapping.
    """

    finished_sku_id: str
    bom: list[BOMLine]
    capacity_per_week: float
    batch_size: float
    production_lead_time_days: float
    daily_demand: float
    production_queue: ProductionQueue
    margin_fraction: float = 0.0


@dataclass(frozen=True)
class SkuDayReport:
    """What happened for one SKU, at one plant, on one day."""

    finished_sku_id: str
    finished_goods_completed: float
    demand_realized: float
    demand_met: float
    production_started: float


@dataclass(frozen=True)
class DailyStepReport:
    """What happened at one plant, across every SKU it produces, on one day."""

    components_received: float
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
) -> DailyStepReport:
    """Advance one plant, across every SKU in ``sku_specs``, by one day.

    ``allocation_rule`` is ``"backlog_proportion"`` (the default) or
    ``"margin_priority"`` -- the build plan's own "with margin priority
    as an option" -- and selects which of session 16's two SKU-facing
    allocation functions splits ``component_part_id`` when more than one
    spec's BOM references it. See the module docstring for order of
    operations.
    """
    plant = state.node_index(plant_node_id)
    component_idx = state.part_index(component_part_id)

    components_received = 0.0
    if inbound_lane_id is not None:
        components_received = shipments.receive(
            lane_id=inbound_lane_id, part_id=component_part_id, current_day=current_day
        )
        state.on_hand[plant, component_idx] += components_received

    # 1. every SKU's due production completes and today's demand is
    #    realised and (partly) backlogged, before any new production
    #    is decided.
    finished_goods_completed_by_sku: dict[str, float] = {}
    demand_met_by_sku: dict[str, float] = {}
    for spec in sku_specs:
        sku_idx = state.sku_index(spec.finished_sku_id)
        finished_goods_completed = spec.production_queue.complete(current_day=current_day)
        state.finished_on_hand[plant, sku_idx] += finished_goods_completed

        available_finished = float(state.finished_on_hand[plant, sku_idx])
        demand_met = min(available_finished, spec.daily_demand)
        unmet = spec.daily_demand - demand_met
        state.finished_on_hand[plant, sku_idx] -= demand_met
        state.finished_backlog[plant, sku_idx] += unmet

        finished_goods_completed_by_sku[spec.finished_sku_id] = finished_goods_completed
        demand_met_by_sku[spec.finished_sku_id] = demand_met

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
                demand_realized=spec.daily_demand,
                demand_met=demand_met_by_sku[spec.finished_sku_id],
                production_started=feasible,
            )
        )

    return DailyStepReport(components_received=components_received, sku_reports=tuple(sku_reports))
