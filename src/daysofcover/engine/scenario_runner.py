"""Bounded deterministic single-plant scenario comparison.

This intentionally narrow first integration exercises the existing daily-step
engine. It is not a network-wide forecast: one SKU, one BOM component and
one plant are modelled, with explicitly supplied initial inventory and demand.
No replenishment, stochastic demand, distribution or financial estimates.
"""

from __future__ import annotations

from pydantic import Field, model_validator

from daysofcover.engine.allocation import CustomerOrder
from daysofcover.engine.daily_step import SkuProductionSpec, advance_one_day
from daysofcover.engine.disruption_state import DisruptionState
from daysofcover.engine.production import ProductionQueue
from daysofcover.engine.shipments import NetworkShipments
from daysofcover.engine.state import NetworkState
from daysofcover.models.network import Network, StrictModel
from daysofcover.models.results import DailyOutcome, RunOutcome, ScenarioComparison
from daysofcover.models.scenario import Disruption, Scenario


class BoundedScenarioInput(StrictModel):
    plant_node_id: str
    sku_id: str
    component_part_id: str
    initial_component_units: float = Field(ge=0, allow_inf_nan=False)
    initial_finished_units: float = Field(default=0, ge=0, allow_inf_nan=False)
    daily_demand_units: float = Field(ge=0, allow_inf_nan=False)
    horizon_days: int = Field(ge=1, le=90)
    production_capacity_per_week: float = Field(ge=0, allow_inf_nan=False)
    disruption_start_day: int = Field(ge=0)
    disruption_duration_days: float = Field(gt=0, allow_inf_nan=False)
    disruption_severity_fraction: float = Field(gt=0, le=1, allow_inf_nan=False)
    seed: int = Field(default=42, ge=0)

    @model_validator(mode="after")
    def validate_start(self) -> BoundedScenarioInput:
        if self.disruption_start_day >= self.horizon_days:
            raise ValueError("disruption must start within the simulation horizon")
        return self


def compare_bounded_scenario(network: Network, config: BoundedScenarioInput) -> ScenarioComparison:
    """Compare paired runs with identical initial conditions and daily demand."""
    nodes = {node.id: node for node in network.nodes}
    skus = {sku.id: sku for sku in network.skus}
    parts = {part.id: part for part in network.parts}
    if config.plant_node_id not in nodes:
        raise ValueError("unknown plant node")
    if nodes[config.plant_node_id].type != "plant":
        raise ValueError("selected node must be a plant")
    if config.sku_id not in skus or config.component_part_id not in parts:
        raise ValueError("unknown SKU or component")
    sku = skus[config.sku_id]
    if len(sku.bom) != 1 or sku.bom[0].part_id != config.component_part_id:
        raise ValueError("first runner supports only a single-component SKU")

    scenario = Scenario(
        id="bounded-disruption",
        name="Bounded plant disruption",
        seed=config.seed,
        disruptions=[
            Disruption(
                element_id=config.plant_node_id,
                start_day=config.disruption_start_day,
                severity_fraction=config.disruption_severity_fraction,
                duration_days=config.disruption_duration_days,
            )
        ],
    )
    disruption = DisruptionState.from_scenario(scenario, network=network)

    def run(disrupted: bool) -> RunOutcome:
        state = NetworkState.from_network(network)
        plant_idx = state.node_index(config.plant_node_id)
        component_idx = state.part_index(config.component_part_id)
        state.on_hand[plant_idx, component_idx] = config.initial_component_units
        sku_idx = state.sku_index(config.sku_id)
        state.finished_on_hand[plant_idx, sku_idx] = config.initial_finished_units
        shipments = NetworkShipments.from_network(network)
        queue = ProductionQueue()
        daily: list[DailyOutcome] = []
        previous_backlog = 0.0
        for day in range(config.horizon_days):
            spec = SkuProductionSpec(
                finished_sku_id=config.sku_id,
                bom=sku.bom,
                capacity_per_week=config.production_capacity_per_week,
                batch_size=sku.batch_size,
                production_lead_time_days=sku.production_lead_time_days,
                orders=[
                    CustomerOrder(
                        customer_id="bounded-demand",
                        order_day=day,
                        quantity=config.daily_demand_units,
                        priority=0,
                    )
                ],
                production_queue=queue,
                margin_fraction=sku.margin_fraction,
            )
            report = advance_one_day(
                state=state,
                shipments=shipments,
                plant_node_id=config.plant_node_id,
                component_part_id=config.component_part_id,
                inbound_lane_id=None,
                sku_specs=[spec],
                current_day=day,
                disruption_state=disruption if disrupted else None,
            )
            fulfilled = report.sku_reports[0].demand_met
            backlog = float(state.finished_backlog[plant_idx, sku_idx])
            expected_backlog = previous_backlog + config.daily_demand_units - fulfilled
            if abs(backlog - expected_backlog) > 1e-7 * max(1.0, expected_backlog):
                raise RuntimeError("daily fulfilment and backlog accounting diverged")
            previous_backlog = backlog
            daily.append(
                DailyOutcome(
                    day=day,
                    demand_units=config.daily_demand_units,
                    fulfilled_units=fulfilled,
                    backlog_units=backlog,
                )
            )
        demand = sum(item.demand_units for item in daily)
        fulfilled = sum(item.fulfilled_units for item in daily)
        return RunOutcome(
            total_demand_units=demand,
            total_fulfilled_units=fulfilled,
            service_fraction=fulfilled / demand if demand else 1.0,
            daily=daily,
        )

    baseline = run(False)
    disrupted = run(True)
    return ScenarioComparison(
        dataset="User-supplied network",
        synthetic=False,
        element_id=config.plant_node_id,
        horizon_days=config.horizon_days,
        seed=config.seed,
        baseline=baseline,
        disrupted=disrupted,
        fulfillment_delta_units=(disrupted.total_fulfilled_units - baseline.total_fulfilled_units),
        assumptions=[
            "Initial component and finished-goods inventory are supplied explicitly.",
            "Demand is constant and deterministic in both runs.",
            "No component replenishment, distribution or inbound shipments.",
            "Both runs use the same plant, SKU, BOM and production configuration.",
        ],
        limitations=[
            "Single plant, single SKU and single BOM component only.",
            "Unmet orders accumulate as aggregate backlog and are not re-served automatically.",
            "Service fraction measures same-day fulfilment, not eventual delivery.",
            "No monetary-loss, time-to-survive or full-network impact estimate.",
        ],
    )
