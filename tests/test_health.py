"""Tests de health/ready endpoints."""


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    data = r.get_json()
    assert data["status"] == "ok"
    assert "version" in data


def test_ready(client):
    r = client.get("/api/ready")
    # Sin DB configurada (en tests) puede devolver 200 con db="no_configurada" o degraded
    assert r.status_code in (200, 503)
    data = r.get_json()
    assert "version" in data
    assert "db" in data
