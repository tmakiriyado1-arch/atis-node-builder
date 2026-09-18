"""Tests for validated node construction and explicit relationships."""
import pytest

from app.models import NodeRelationship, SourceProvenance
from app.services.node_builder import NodeBuildError, NodeBuilder
from app.services.node_store import NodeStore, NodeStoreError


def test_build_node_requires_resolved_entity(registry, resolver, zera_entity):
    builder = NodeBuilder(resolver)
    node = builder.build(
        node_id="NODE-ZERA",
        entity_text=" zera ",
        fields={"summary": "Source-backed summary"},
        source_id="source-1",
        source_type="trusted_document",
    )

    assert node.entity_id == zera_entity.entity_id
    assert node.canonical_name == zera_entity.canonical_name
    assert node.provenance[0].source_id == "source-1"
    assert node.fields == {"summary": "Source-backed summary"}


def test_build_node_rejects_unknown_entity(resolver):
    with pytest.raises(NodeBuildError, match="could not be resolved"):
        NodeBuilder(resolver).build(
            node_id="NODE-UNKNOWN",
            entity_text="Unknown entity",
            fields={},
            source_id="source-1",
        )


def test_relationship_is_explicit_deterministic_and_deduplicated(registry, resolver):
    source_entity = registry.create_entity("Source Entity")
    target_entity = registry.create_entity("Target Entity")
    node = NodeBuilder(resolver).build(
        node_id="NODE-SOURCE",
        entity_text=source_entity.canonical_name,
        fields={},
        source_id="source-1",
    )
    store = NodeStore(registry)
    store.save(node)
    relationship = NodeRelationship(
        source_node_id=node.node_id,
        target_entity_id=target_entity.entity_id,
        relationship_type="explicitly_related",
        provenance=[SourceProvenance(source_id="source-2")],
    )

    first = store.add_relationship(relationship)
    second = store.add_relationship(relationship)

    assert first.relationship_id == second.relationship_id
    assert len(store.list_relationships(node.node_id)) == 1


def test_relationship_rejects_unknown_target_and_self_link(registry, resolver):
    entity = registry.create_entity("Source Entity")
    node = NodeBuilder(resolver).build(
        node_id="NODE-SOURCE",
        entity_text=entity.canonical_name,
        fields={},
        source_id="source-1",
    )
    store = NodeStore(registry)
    store.save(node)

    for target_entity_id in ("ENTITY-999999", entity.entity_id):
        with pytest.raises(NodeStoreError):
            store.add_relationship(
                NodeRelationship(
                    source_node_id=node.node_id,
                    target_entity_id=target_entity_id,
                    relationship_type="explicitly_related",
                    provenance=[SourceProvenance(source_id="source-2")],
                )
            )