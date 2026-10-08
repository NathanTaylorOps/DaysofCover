"""The Stage 0 API skeleton answers /health as JSON, per the build plan's
Stage 0 done-when criteria.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from daysofcover import __version__
from daysofcover.api.main import app

client = TestClient(app)


def test_health_returns_ok_json() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
    assert isinstance(body["web_static_present"], bool)
    # rss_mb is None on Windows (no `resource` module there); the Docker
    # image is always Linux, so it is always a real number in production.
    assert body["rss_mb"] is None or (isinstance(body["rss_mb"], float) and body["rss_mb"] > 0)


def test_example_elements_lists_disruption_targets() -> None:
    response = client.get("/api/example/elements")
    assert response.status_code == 200
    body = response.json()
    assert body["dataset"] == "Moreton Marine Systems (synthetic)"
    assert len(body["nodes"]) == 33
    assert len(body["lanes"]) == 33


def test_structural_impact_reports_model_scope() -> None:
    elements = client.get("/api/example/elements").json()
    element_id = elements["nodes"][0]["id"]
    response = client.get(f"/api/example/structural-impact/{element_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["analysis_type"] == "structural_dependency_screen"
    assert 0.0 <= body["convergence_fraction"] <= 1.0
    assert "not an inventory" in body["interpretation"]


def test_structural_impact_rejects_unknown_element() -> None:
    response = client.get("/api/example/structural-impact/not-a-real-element")
    assert response.status_code == 404
