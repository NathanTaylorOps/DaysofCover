"""Regression coverage for bounded paired scenario execution."""

import pytest
from pydantic import ValidationError

from daysofcover.engine.scenario_runner import BoundedScenarioInput, compare_bounded_scenario
from daysofcover.models.network import Network, NodeType


def example_network() -> Network:
    return Network.model_validate(
        {
            "base_currency": "AUD",
            "nodes": [{"id": "plant", "name": "Plant", "type": NodeType.PLANT, "region": "AU"}],
            "lanes": [],
            "parts": [
                {
                    "id": "part",
                    "name": "Component",
                    "suppliers": [{"node_id": "plant", "split_ratio": 1.0}],
                    "unit_cost": 1.0,
                    "currency": "AUD",
                }
            ],
            "skus": [
                {
                    "id": "sku",
                    "name": "Product",
                    "price": {"AUD": 10.0},
                    "margin_fraction": 0.3,
                    "currency": "AUD",
                    "bom": [{"part_id": "part", "quantity": 1.0}],
                    "production_lead_time_days": 1.0,
                    "batch_size": 1.0,
                }
            ],
            "customers": [],
        }
    )


def config(**overrides: object) -> BoundedScenarioInput:
    values = dict(
        plant_node_id="plant",
        sku_id="sku",
        component_part_id="part",
        initial_component_units=200.0,
        daily_demand_units=5.0,
        horizon_days=7,
        production_capacity_per_week=70.0,
        disruption_start_day=0,
        disruption_duration_days=7.0,
        disruption_severity_fraction=1.0,
        seed=42,
    )
    values.update(overrides)
    return BoundedScenarioInput.model_validate(values)


def test_disruption_reduces_fulfilment_and_is_reproducible() -> None:
    network = example_network()
    result = compare_bounded_scenario(network, config())
    assert result.baseline.total_fulfilled_units > result.disrupted.total_fulfilled_units
    assert result.fulfillment_delta_units < 0
    assert result == compare_bounded_scenario(network, config())
    assert len(result.baseline.daily) == 7
    assert result.baseline.total_demand_units == result.disrupted.total_demand_units


def test_starting_finished_stock_buffers_disruption() -> None:
    network = example_network()
    empty = compare_bounded_scenario(network, config())
    stocked = compare_bounded_scenario(network, config(initial_finished_units=100.0))
    assert stocked.disrupted.total_fulfilled_units > empty.disrupted.total_fulfilled_units


def test_rejects_invalid_horizon_and_unknown_sku() -> None:
    with pytest.raises(ValidationError):
        config(horizon_days=91)
    with pytest.raises(ValueError, match="unknown SKU"):
        compare_bounded_scenario(example_network(), config(sku_id="missing"))


def test_surplus_components_are_conserved_across_multiple_days() -> None:
    """200 components must support repeated daily starts, not disappear on day zero."""
    result = compare_bounded_scenario(
        example_network(),
        config(
            initial_component_units=200.0,
            initial_finished_units=0.0,
            daily_demand_units=5.0,
            horizon_days=7,
            production_capacity_per_week=70.0,
            disruption_start_day=0,
            disruption_duration_days=7.0,
        ),
    )
    baseline_daily = [day.fulfilled_units for day in result.baseline.daily]
    assert baseline_daily == [0.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0]
    assert [day.fulfilled_units for day in result.disrupted.daily] == [0.0] * 7
    assert result.baseline.total_fulfilled_units == 30.0
    assert result.disrupted.total_fulfilled_units == 0.0
    assert result.fulfillment_delta_units == -30.0


def test_finished_inventory_masks_a_disruption_until_stock_depletes() -> None:
    result = compare_bounded_scenario(
        example_network(),
        config(
            initial_component_units=200.0,
            initial_finished_units=10.0,
            daily_demand_units=5.0,
            horizon_days=5,
            production_capacity_per_week=70.0,
            disruption_start_day=0,
            disruption_duration_days=5.0,
        ),
    )
    assert [day.fulfilled_units for day in result.baseline.daily] == [5.0] * 5
    assert [day.fulfilled_units for day in result.disrupted.daily] == [5.0, 5.0, 0.0, 0.0, 0.0]
    assert result.baseline.total_fulfilled_units == 25.0
    assert result.disrupted.total_fulfilled_units == 10.0


def test_component_depletion_limits_production_without_negative_inventory() -> None:
    result = compare_bounded_scenario(
        example_network(),
        config(
            initial_component_units=10.0,
            initial_finished_units=0.0,
            daily_demand_units=5.0,
            horizon_days=5,
            production_capacity_per_week=70.0,
            disruption_start_day=0,
            disruption_duration_days=5.0,
        ),
    )
    assert [day.fulfilled_units for day in result.baseline.daily] == [0.0, 5.0, 5.0, 0.0, 0.0]
    assert result.baseline.total_fulfilled_units == 10.0
    assert result.baseline.daily[-1].backlog_units == 15.0
