"""HTTP contract tests for the bounded synthetic scenario endpoint."""

from fastapi.testclient import TestClient

from daysofcover.api.main import EXAMPLE_NETWORK, app
from daysofcover.io.loaders import load_network


client = TestClient(app)


def valid_request() -> dict[str, object]:
    network = load_network(EXAMPLE_NETWORK)
    plant = next(
        node for node in network.nodes if node.type == "plant"
    )
    sku = next(sku for sku in network.skus if len(sku.bom) == 1)
    return {
        "plant_node_id": plant.id,
        "sku_id": sku.id,
        "component_part_id": sku.bom[0].part_id,
        "initial_component_units": 200.0,
        "initial_finished_units": 0.0,
        "daily_demand_units": 5.0,
        "horizon_days": 7,
        "production_capacity_per_week": 70.0,
        "disruption_start_day": 0,
        "disruption_duration_days": 7.0,
        "disruption_severity_fraction": 1.0,
        "seed": 42,
    }


def test_simulation_rejects_invalid_request() -> None:
    payload = valid_request()
    payload["horizon_days"] = 91
    response = client.post("/api/example/simulation", json=payload)
    assert response.status_code == 422

    payload = valid_request()
    payload["plant_node_id"] = "missing"
    response = client.post("/api/example/simulation", json=payload)
    assert response.status_code == 422

    payload = valid_request()
    payload["unexpected_field"] = 1
    response = client.post("/api/example/simulation", json=payload)
    assert response.status_code == 422


def test_simulation_contract_and_determinism() -> None:
    payload = valid_request()
    first = client.post("/api/example/simulation", json=payload)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["synthetic"] is True
    assert body["dataset"] == "Moreton Marine Systems"
    assert body["horizon_days"] == 7
    assert len(body["baseline"]["daily"]) == 7
    assert body["baseline"]["total_demand_units"] == 35.0
    assert body["baseline"]["total_fulfilled_units"] >= body["disrupted"]["total_fulfilled_units"]
    assert client.post("/api/example/simulation", json=payload).json() == body
