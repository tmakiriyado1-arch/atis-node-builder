"""Process-local storage for validated NORA nodes and explicit relationships."""
from hashlib import sha256
from typing import Dict, List

from app.models import ATISNode, NodeRelationship
from app.services.entity_resolution.registry import EntityRegistry


class NodeStoreError(ValueError):
    """Raised when a node or relationship cannot be stored safely."""


class NodeStore:
    """Deterministic process-local store pending the repository's DB contract."""

    def __init__(self, registry: EntityRegistry):
        self.nodes: Dict[str, ATISNode] = {}
        self.relationships: Dict[str, NodeRelationship] = {}
        self.registry = registry

    def save(self, node: ATISNode) -> ATISNode:
        existing = self.nodes.get(node.node_id)
        if existing and existing.entity_id != node.entity_id:
            raise NodeStoreError("node_id is already assigned to another entity")
        if existing:
            known_sources = {item.source_id for item in node.provenance}
            provenance = list(node.provenance)
            provenance.extend(
                item for item in existing.provenance if item.source_id not in known_sources
            )
            node = node.model_copy(update={"provenance": provenance})
        self.nodes[node.node_id] = node
        return node

    def get(self, node_id: str) -> ATISNode | None:
        return self.nodes.get(node_id)

    def list(self) -> List[ATISNode]:
        return list(self.nodes.values())

    def add_relationship(self, relationship: NodeRelationship) -> NodeRelationship:
        if relationship.source_node_id not in self.nodes:
            raise NodeStoreError("source node does not exist")
        source = self.nodes[relationship.source_node_id]
        if source.entity_id == relationship.target_entity_id:
            raise NodeStoreError("self-relationships are not valid")
        if self.registry.get_entity(relationship.target_entity_id) is None:
            raise NodeStoreError("target entity does not exist")
        relationship_id = relationship.relationship_id or self._relationship_id(relationship)
        relationship = relationship.model_copy(update={"relationship_id": relationship_id})
        existing = self.relationships.get(relationship_id)
        if existing and existing != relationship:
            raise NodeStoreError("relationship_id collision")
        self.relationships[relationship_id] = relationship
        return relationship

    def list_relationships(self, node_id: str) -> List[NodeRelationship]:
        return sorted(
            (item for item in self.relationships.values() if item.source_node_id == node_id),
            key=lambda item: item.relationship_id or "",
        )

    @staticmethod
    def _relationship_id(relationship: NodeRelationship) -> str:
        provenance = ",".join(item.source_id for item in relationship.provenance)
        value = "|".join(
            [
                relationship.source_node_id,
                relationship.target_entity_id,
                relationship.relationship_type,
                provenance,
            ]
        )
        return f"REL-{sha256(value.encode('utf-8')).hexdigest()[:16]}"