"""Contract tests for baseline-versus-disruption result data."""

import pytest
from pydantic import ValidationError

from daysofcover.models.results import DailyOutcome, RunOutcome, ScenarioComparison


def test_scenario_comparison_serializes_for_api_consumers() -> None:
    daily = DailyOutcome(day=0, demand_units=10.0, fulfilled_units=8.0, backlog_units=2.0)
    baseline = RunOutcome(
        total_demand_units=10.0,
        total_fulfilled_units=10.0,
        service_fraction=1.0,
        daily=[DailyOutcome(day=0, demand_units=10.0, fulfilled_units=10.0, backlog_units=0.0)],
    )
    disrupted = RunOutcome(
        total_demand_units=10.0,
        total_fulfilled_units=8.0,
        service_fraction=0.8,
        daily=[daily],
    )
    result = ScenarioComparison(
        dataset="Moreton Marine Systems",
        synthetic=True,
        element_id="supplier-1",
        horizon_days=1,
        seed=42,
        baseline=baseline,
        disrupted=disrupted,
        fulfillment_delta_units=-2.0,
        assumptions=["Initial inventory supplied explicitly."],
        limitations=["Not a financial-loss forecast."],
    )
    assert ScenarioComparison.model_validate_json(result.model_dump_json()) == result
    assert result.disrupted.daily[0].backlog_units == 2.0


def test_scenario_comparison_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        DailyOutcome(
            day=0,
            demand_units=1.0,
            fulfilled_units=1.0,
            backlog_units=0.0,
            invented_metric=12,
        )
