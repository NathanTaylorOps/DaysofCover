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


@pytest.mark.parametrize(
    ("initial_components", "initial_finished", "daily_demand", "severity"),
    [
        (0.0, 0.0, 0.0, 1.0),
        (0.0, 0.0, 5.0, 1.0),
        (0.0, 20.0, 5.0, 1.0),
        (100.0, 0.0, 5.0, 0.5),
        (100.0, 10.0, 7.0, 0.25),
    ],
)
def test_scenario_comparison_daily_ledgers_reconcile(
    initial_components: float,
    initial_finished: float,
    daily_demand: float,
    severity: float,
) -> None:
    """Both paired runs report consistent daily and aggregate fulfilment."""
    result = compare_bounded_scenario(
        example_network(),
        config(
            initial_component_units=initial_components,
            initial_finished_units=initial_finished,
            daily_demand_units=daily_demand,
            horizon_days=9,
            disruption_start_day=2,
            disruption_duration_days=4.0,
            disruption_severity_fraction=severity,
        ),
    )
    for run in (result.baseline, result.disrupted):
        assert len(run.daily) == 9
        assert [day.day for day in run.daily] == list(range(9))
        assert run.total_demand_units == pytest.approx(sum(day.demand_units for day in run.daily))
        assert run.total_fulfilled_units == pytest.approx(
            sum(day.fulfilled_units for day in run.daily)
        )
        cumulative_demand = 0.0
        cumulative_fulfilled = 0.0
        for day in run.daily:
            cumulative_demand += day.demand_units
            cumulative_fulfilled += day.fulfilled_units
            assert 0.0 <= day.fulfilled_units <= cumulative_demand - (
                cumulative_fulfilled - day.fulfilled_units
            ) + 1e-7
            assert day.backlog_units == pytest.approx(cumulative_demand - cumulative_fulfilled)
            assert day.backlog_units >= -1e-7
        expected_service = (
            run.total_fulfilled_units / run.total_demand_units
            if run.total_demand_units
            else 1.0
        )
        assert run.service_fraction == pytest.approx(expected_service)
        assert 0.0 <= run.service_fraction <= 1.0

    assert result.baseline.total_demand_units == result.disrupted.total_demand_units
    assert result.fulfillment_delta_units == pytest.approx(
        result.disrupted.total_fulfilled_units - result.baseline.total_fulfilled_units
    )
    assert result == compare_bounded_scenario(
        example_network(),
        config(
            initial_component_units=initial_components,
            initial_finished_units=initial_finished,
            daily_demand_units=daily_demand,
            horizon_days=9,
            disruption_start_day=2,
            disruption_duration_days=4.0,
            disruption_severity_fraction=severity,
        ),
    )
