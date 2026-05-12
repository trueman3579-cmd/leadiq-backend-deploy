from fastapi.testclient import TestClient

from backend.main import app


def test_health_route():
    client = TestClient(app)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
