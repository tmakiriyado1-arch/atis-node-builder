"""Build validated nodes from trusted, already-parsed source material."""
from typing import Any, Dict, Optional

from app.models import ATISNode, SourceProvenance
from app.services.entity_resolution.resolver import EntityResolver
from app.services.entity_resolution.registry import ResolutionState


class NodeBuildError(ValueError):
    """Raised when source material cannot produce a valid node."""


class NodeBuilder:
    """Construct nodes without inventing fields or resolving unknown entities."""

    def __init__(self, resolver: EntityResolver):
        self.resolver = resolver

    def build(
        self,
        node_id: str,
        entity_text: str,
        fields: Dict[str, Any],
        source_id: str,
        source_type: Optional[str] = None,
        source_uri: Optional[str] = None,
        excerpt: Optional[str] = None,
    ) -> ATISNode:
        if not node_id or not node_id.strip():
            raise NodeBuildError("node_id is required")
        if not isinstance(fields, dict):
            raise NodeBuildError("fields must be an object")

        result = self.resolver.resolve(entity_text)
        if result.state != ResolutionState.RESOLVED or not result.entity_id:
            raise NodeBuildError(
                f"entity could not be resolved: {result.state.value}; {result.reasoning}"
            )

        entity = self.resolver.registry.get_entity(result.entity_id)
        if entity is None:
            raise NodeBuildError("resolved entity is missing from the registry")

        provenance = SourceProvenance(
            source_id=source_id,
            source_type=source_type,
            source_uri=source_uri,
            excerpt=excerpt,
        )
        return ATISNode(
            node_id=node_id.strip(),
            entity_id=entity.entity_id,
            canonical_name=entity.canonical_name,
            entity_type=entity.entity_type,
            fields=dict(sorted(fields.items())),
            provenance=[provenance],
        )