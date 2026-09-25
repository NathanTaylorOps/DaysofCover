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
