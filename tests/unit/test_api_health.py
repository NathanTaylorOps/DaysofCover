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
