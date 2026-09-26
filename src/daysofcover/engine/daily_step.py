"""One day of the world: composing state, shipments and production.

Sessions 12 to 14 built three pieces in isolation -- the (node, part) and
(node, sku) state chassis, per-lane in-transit shipments, and BOM-driven
production -- each tested against its own inputs, none of them run
together over time. This module is where they are first composed into an
actual daily step, for one plant producing one SKU from one component
supplied over one lane.

Order of operations follows the build plan's daily step exactly:
shipments arrive before production is checked, so today's arrivals count
as available components; production due today completes into finished
goods before demand is realised, so a batch finishing today can be sold
the same day; demand then consumes finished goods on hand and backlogs
whatever it cannot; only then does a new production batch start, against
whatever components remain once today's demand has been served.

Deliberately out of scope, not forgotten: today's demand is a single
number handed in by the caller, not yet drawn from a customer's seasonal
profile; finished-goods backlog is only ever added to here, never repaid
from a later day's surplus stock -- that repayment is a customer
allocation rule (FIFO by order date, with a priority override) the build
plan states separately, and it is not this module's job. Multiple SKUs
sharing a scarce component, multiple customers competing for scarce
finished goods, and reordering components to replenish the plant are all
still ahead.
"""

from __future__ import annotations

from dataclasses import dataclass

from daysofcover.engine.production import (
    ProductionQueue,
    consume_components,
    feasible_production_units,
)
from daysofcover.engine.shipments import NetworkShipments
from daysofcover.engine.state import NetworkState
from daysofcover.models.network import BOMLine


@dataclass(frozen=True)
class DailyStepReport:
    """What happened at one plant, for one SKU, on one day."""

    components_received: float
    finished_goods_completed: float
    demand_realized: float
    demand_met: float
    production_started: float


def advance_one_day(
    *,
    state: NetworkState,
    shipments: NetworkShipments,
    production_queue: ProductionQueue,
    plant_node_id: str,
    component_part_id: str,
    finished_sku_id: str,
    inbound_lane_id: str | None,
    bom: list[BOMLine],
    capacity_per_week: float,
    batch_size: float,
    production_lead_time_days: float,
    daily_demand: float,
    current_day: int,
) -> DailyStepReport:
    """Advance one plant, one SKU, by one day. See the module docstring for order of operations."""
    plant = state.node_index(plant_node_id)
    component_idx = state.part_index(component_part_id)
    sku_idx = state.sku_index(finished_sku_id)

    components_received = 0.0
    if inbound_lane_id is not None:
        components_received = shipments.receive(
            lane_id=inbound_lane_id, part_id=component_part_id, current_day=current_day
        )
        state.on_hand[plant, component_idx] += components_received

    finished_goods_completed = production_queue.complete(current_day=current_day)
    state.finished_on_hand[plant, sku_idx] += finished_goods_completed

    available_finished = float(state.finished_on_hand[plant, sku_idx])
    demand_met = min(available_finished, daily_demand)
    unmet = daily_demand - demand_met
    state.finished_on_hand[plant, sku_idx] -= demand_met
    state.finished_backlog[plant, sku_idx] += unmet

    on_hand_by_part = {component_part_id: float(state.on_hand[plant, component_idx])}
    feasible = feasible_production_units(
        capacity_per_week=capacity_per_week,
        on_hand_by_part=on_hand_by_part,
        bom=bom,
        batch_size=batch_size,
    )
    if feasible > 0:
        updated = consume_components(
            on_hand_by_part=on_hand_by_part, bom=bom, units_produced=feasible
        )
        state.on_hand[plant, component_idx] = updated[component_part_id]
        production_queue.start(
            quantity=feasible, start_day=current_day, lead_time_days=production_lead_time_days
        )

    return DailyStepReport(
        components_received=components_received,
        finished_goods_completed=finished_goods_completed,
        demand_realized=daily_demand,
        demand_met=demand_met,
        production_started=feasible,
    )
