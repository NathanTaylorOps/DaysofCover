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


def test_bounded_request_size_limit() -> None:
    import json

    valid = valid_request()
    assert client.post("/api/simulation/bounded", json=valid).status_code == 200

    oversized = json.dumps(valid).encode() + b" " * (256 * 1024)
    response = client.post(
        "/api/simulation/bounded",
        content=oversized,
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 413
    assert "256 KiB" in response.json()["detail"]

    response = client.post(
        "/api/simulation/bounded",
        content=b"{}",
        headers={"content-type": "application/json", "content-length": "invalid"},
    )
    assert response.status_code in (400, 422)


def test_request_size_limit_is_endpoint_specific() -> None:
    assert client.post("/api/example/simulation").status_code == 200


def test_demo_request_round_trip_matches_demo_result() -> None:
    request = client.get("/api/example/simulation/request")
    assert request.status_code == 200
    demo = client.post("/api/example/simulation")
    supplied = client.post("/api/simulation/bounded", json=request.json())
    assert demo.status_code == supplied.status_code == 200
    demo_body = demo.json()
    supplied_body = supplied.json()
    assert demo_body["synthetic"] is True
    assert supplied_body["synthetic"] is False
    assert demo_body["baseline"] == supplied_body["baseline"]
    assert demo_body["disrupted"] == supplied_body["disrupted"]
    assert demo_body["fulfillment_delta_units"] == supplied_body["fulfillment_delta_units"]


def test_bounded_endpoint_rejects_extreme_finite_inputs() -> None:
    for field in (
        "initial_component_units",
        "initial_finished_units",
        "daily_demand_units",
        "production_capacity_per_week",
    ):
        payload = valid_request()
        config = payload["config"]
        assert isinstance(config, dict)
        config[field] = 1e308
        response = client.post("/api/simulation/bounded", json=payload)
        assert response.status_code == 422, (field, response.text)


def test_health_is_not_shadowed_by_static_mount() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_bounded_endpoint_requires_json_media_type() -> None:
    import json

    payload = json.dumps(valid_request())
    for content_type in ("text/plain", "application/x-www-form-urlencoded"):
        response = client.post(
            "/api/simulation/bounded",
            content=payload,
            headers={"content-type": content_type},
        )
        assert response.status_code == 415
        assert response.json()["detail"] == "Content-Type must be application/json"

    response = client.post(
        "/api/simulation/bounded",
        content=payload,
        headers={"content-type": "application/json; charset=utf-8"},
    )
    assert response.status_code == 200
