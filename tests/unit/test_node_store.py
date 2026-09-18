"""Tests for safe node updates."""
from app.models import SourceProvenance
from app.services.node_builder import NodeBuilder
from app.services.node_store import NodeStore


def test_node_update_preserves_existing_provenance(registry, resolver):
    entity = registry.create_entity("Test Entity")
    builder = NodeBuilder(resolver)
    store = NodeStore(registry)
    original = builder.build("NODE-1", entity.canonical_name, {}, "source-1")
    updated = builder.build("NODE-1", entity.canonical_name, {"summary": "updated"}, "source-2")

    store.save(original)
    saved = store.save(updated)

    assert {item.source_id for item in saved.provenance} == {"source-1", "source-2"}