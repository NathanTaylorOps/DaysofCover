"""HTTP contract tests for the bounded scenario endpoint."""

from fastapi.testclient import TestClient

from daysofcover.api.main import app

client = TestClient(app)


def valid_request() -> dict[str, object]:
    return {
        "network": {
            "base_currency": "AUD",
            "nodes": [{"id": "plant", "name": "Plant", "type": "plant", "region": "AU"}],
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
        },
        "config": {
            "plant_node_id": "plant",
            "sku_id": "sku",
            "component_part_id": "part",
            "initial_component_units": 200.0,
            "initial_finished_units": 0.0,
            "daily_demand_units": 5.0,
            "horizon_days": 7,
            "production_capacity_per_week": 70.0,
            "disruption_start_day": 0,
            "disruption_duration_days": 7.0,
            "disruption_severity_fraction": 1.0,
            "seed": 42,
        },
    }


def test_simulation_rejects_invalid_request() -> None:
    payload = valid_request()
    config = payload["config"]
    assert isinstance(config, dict)
    config["horizon_days"] = 91
    assert client.post("/api/simulation/bounded", json=payload).status_code == 422

    payload = valid_request()
    config = payload["config"]
    assert isinstance(config, dict)
    config["plant_node_id"] = "missing"
    assert client.post("/api/simulation/bounded", json=payload).status_code == 422

    payload = valid_request()
    payload["unexpected_field"] = 1
    assert client.post("/api/simulation/bounded", json=payload).status_code == 422


def test_simulation_contract_and_determinism() -> None:
    payload = valid_request()
    first = client.post("/api/simulation/bounded", json=payload)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["synthetic"] is False
    assert body["horizon_days"] == 7
    assert len(body["baseline"]["daily"]) == 7
    assert body["baseline"]["total_demand_units"] == 35.0
    assert body["baseline"]["total_fulfilled_units"] > body["disrupted"]["total_fulfilled_units"]
    assert client.post("/api/simulation/bounded", json=payload).json() == body
