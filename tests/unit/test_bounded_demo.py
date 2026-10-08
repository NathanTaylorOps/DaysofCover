"""Executable example and bounded simulation invariants."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from daysofcover.api.main import app
from daysofcover.engine.scenario_runner import BoundedScenarioInput, compare_bounded_scenario
from daysofcover.models.network import Network

client = TestClient(app)


def demo() -> tuple[Network, BoundedScenarioInput]:
    response = client.get("/api/example/simulation/request")
    assert response.status_code == 200
    payload = response.json()
    return (
        Network.model_validate_json(__import__("json").dumps(payload["network"])),
        BoundedScenarioInput.model_validate(payload["config"]),
    )


def test_bundled_example_runs_over_http_and_is_reproducible() -> None:
    first = client.post("/api/example/simulation")
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["synthetic"] is True
    assert len(body["baseline"]["daily"]) == 7
    assert body["baseline"]["total_fulfilled_units"] > body["disrupted"]["total_fulfilled_units"]
    assert client.post("/api/example/simulation").json() == body
    request = client.get("/api/example/simulation/request").json()
    supplied = client.post("/api/simulation/bounded", json=request)
    assert supplied.status_code == 200, supplied.text
    assert supplied.json()["baseline"] == body["baseline"]


@pytest.mark.parametrize(
    "changes",
    [
        {"daily_demand_units": 0.0},
        {"production_capacity_per_week": 0.0},
        {"disruption_start_day": 13, "disruption_duration_days": 1.0},
        {"disruption_severity_fraction": 0.5},
        {"disruption_duration_days": 1.0},
        {"initial_finished_units": 100.0},
    ],
)
def test_daily_invariants(changes: dict[str, float | int]) -> None:
    network, config = demo()
    result = compare_bounded_scenario(network, config.model_copy(update=changes))
    for run in (result.baseline, result.disrupted):
        assert len(run.daily) == config.horizon_days
        assert run.total_demand_units == pytest.approx(sum(d.demand_units for d in run.daily))
        assert run.total_fulfilled_units == pytest.approx(sum(d.fulfilled_units for d in run.daily))
        assert 0 <= run.service_fraction <= 1
        assert all(0 <= d.fulfilled_units <= d.demand_units for d in run.daily)
        assert all(d.backlog_units >= 0 for d in run.daily)
        assert run.service_fraction == pytest.approx(
            run.total_fulfilled_units / run.total_demand_units if run.total_demand_units else 1.0
        )


def test_zero_capacity_and_sufficient_finished_stock_equal_runs() -> None:
    network, config = demo()
    zero = compare_bounded_scenario(
        network, config.model_copy(update={"production_capacity_per_week": 0.0})
    )
    assert zero.baseline == zero.disrupted
    stocked = compare_bounded_scenario(
        network, config.model_copy(update={"initial_finished_units": 1000.0})
    )
    assert stocked.baseline.total_fulfilled_units == stocked.disrupted.total_fulfilled_units


def test_nonfinite_inputs_rejected() -> None:
    _, config = demo()
    with pytest.raises(ValidationError):
        BoundedScenarioInput.model_validate(
            {**config.model_dump(), "daily_demand_units": float("inf")}
        )
