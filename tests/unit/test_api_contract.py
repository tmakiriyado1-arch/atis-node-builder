"""Regression checks for application route wiring."""
from app.main import app


def test_entity_and_node_routes_are_registered():
    paths = {route.path for route in app.routes}

    assert "/entities/resolve" in paths
    assert "/entities/create" in paths
    assert "/nodes" in paths
    assert "/nodes/{node_id}" in paths
    assert "/nodes/{node_id}/relationships" in paths
