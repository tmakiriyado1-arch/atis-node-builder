"""Regression checks for application route wiring."""
from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_entity_and_node_routes_are_registered():
    paths = {route.path for route in app.routes}

    assert "/entities/resolve" in paths
    assert "/entities/create" in paths
    assert "/nodes" in paths
    assert "/nodes/{node_id}" in paths
    assert "/nodes/{node_id}/relationships" in paths


def test_frontend_api_routes_are_registered():
    paths = {route.path for route in app.routes}

    assert "/api/entities" in paths
    assert "/api/runs" in paths
    assert "/api/runs/{run_id}" in paths
    assert "/api/runs/{run_id}/result" in paths


def test_openapi_describes_frontend_api():
    schema = client.get("/openapi.json").json()
    paths = schema.get("paths", {})

    assert "/api/entities" in paths
    assert "/api/runs" in paths
    assert "/api/runs/{run_id}" in paths
    assert "/api/runs/{run_id}/result" in paths
