"""End-to-end NORA processing pipeline for Markdown ATIS sources."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from app.models import ATISNode, NodeRelationship, SourceProvenance
from app.services.entity_resolution.registry import EntityRegistry, ResolutionState
from app.services.entity_resolution.resolver import EntityResolver
from app.services.node_builder import NodeBuilder
from app.services.node_store import NodeStore, NodeStoreError
from app.services.queue_manager import EntityQueue, QueueStatus
from app.source_ingestion import MarkdownSourceParser, SourceDocument


class NORAProcessor:
    """Process Markdown source documents into validated local NORA nodes."""

    def __init__(
        self,
        registry: Optional[EntityRegistry] = None,
        resolver: Optional[EntityResolver] = None,
        queue: Optional[EntityQueue] = None,
        store: Optional[NodeStore] = None,
    ):
        self.registry = registry or EntityRegistry()
        self.resolver = resolver or EntityResolver(self.registry)
        self.queue = queue or EntityQueue()
        self.store = store or NodeStore(self.registry)
        self.node_builder = NodeBuilder(self.resolver)
        self.parser = MarkdownSourceParser()

    def process_file(self, source_path: str | Path) -> Dict[str, Any]:
        file_path = Path(source_path)
        if not file_path.exists():
            return {
                "status": "failed",
                "error": f"source file not found: {file_path}",
                "node_id": None,
                "entity_id": None,
                "canonical_name": None,
                "provenance": [],
                "relationships": [],
            }

        document = self.parser.parse(file_path)
        primary = self._resolve_primary_entity(document)
        if primary is None:
            self._queue_unresolved(document)
            return {
                "status": "unresolved",
                "source_path": str(file_path),
                "document": {
                    "title": document.title,
                    "links": document.links,
                    "references": document.references,
                },
                "node_id": None,
                "entity_id": None,
                "canonical_name": None,
                "provenance": [],
                "relationships": [],
                "unresolved": [*document.links, *document.references],
            }

        node_id = self._node_id_for_source(document.path, primary["entity_id"])
        source_uri = str(file_path)
        excerpt = document.body[:500] if document.body else document.raw_content[:500]
        node = self.node_builder.build(
            node_id=node_id,
            entity_text=primary["canonical_name"],
            fields={
                "title": document.title,
                "body": document.body,
                "frontmatter": document.frontmatter,
                "links": document.links,
                "references": document.references,
            },
            source_id=str(file_path),
            source_type="markdown",
            source_uri=source_uri,
            excerpt=excerpt,
        )

        created = False
        updated = False
        unchanged = False
        existing = self.store.get(node.node_id)
        if existing is None:
            self.store.save(node)
            created = True
        elif existing.model_dump() == node.model_dump():
            unchanged = True
        else:
            self.store.save(node)
            updated = True

        relationships = self._extract_explicit_relationships(document, node)

        return {
            "status": "ok",
            "source_path": str(file_path),
            "node_id": node.node_id,
            "entity_id": node.entity_id,
            "canonical_name": node.canonical_name,
            "created": created,
            "updated": updated,
            "unchanged": unchanged,
            "provenance": [item.model_dump() for item in node.provenance],
            "relationships": [item.model_dump() for item in relationships],
            "document": {
                "title": document.title,
                "links": document.links,
                "references": document.references,
            },
        }

    def process_directory(self, directory_path: str | Path) -> Dict[str, Any]:
        directory = Path(directory_path)
        summary: Dict[str, Any] = {
            "discovered": 0,
            "processed": 0,
            "failed": 0,
            "created": 0,
            "updated": 0,
            "unchanged": 0,
            "relationships_created": 0,
            "unresolved": 0,
            "documents": [],
            "errors": [],
        }

        if not directory.exists() or not directory.is_dir():
            summary["errors"].append(f"directory not found: {directory}")
            return summary

        for file_path in sorted(directory.iterdir()):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in {".md", ".markdown"}:
                continue

            summary["discovered"] += 1
            try:
                result = self.process_file(file_path)
                summary["documents"].append({"path": str(file_path), "status": result["status"]})
                summary["processed"] += 1
                if result.get("created"):
                    summary["created"] += 1
                if result.get("updated"):
                    summary["updated"] += 1
                if result.get("unchanged"):
                    summary["unchanged"] += 1
                if result.get("relationships"):
                    summary["relationships_created"] += len(result["relationships"])
                if result.get("status") == "unresolved":
                    summary["unresolved"] += 1
            except Exception as exc:  # pragma: no cover - process continuity
                summary["failed"] += 1
                summary["errors"].append({"path": str(file_path), "error": str(exc)})

        return summary

    def list_nodes(self) -> List[Dict[str, Any]]:
        return [node.model_dump() for node in self.store.list()]

    def get_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        node = self.store.get(node_id)
        return None if node is None else node.model_dump()

    def list_relationships(self, node_id: str) -> List[Dict[str, Any]]:
        return [relationship.model_dump() for relationship in self.store.list_relationships(node_id)]

    def list_unresolved(self) -> List[Dict[str, Any]]:
        return [item.__dict__ for item in self.queue.list_all() if item.status in {QueueStatus.PENDING, QueueStatus.ERROR}]

    def _resolve_primary_entity(self, document: SourceDocument) -> Optional[Dict[str, Any]]:
        candidates: List[str] = []
        for key in ("entity", "entity_name", "title", "name", "subject"):
            value = document.frontmatter.get(key)
            if isinstance(value, str) and value.strip():
                candidates.append(value.strip())
        if document.title:
            candidates.append(document.title.strip())
        for candidate in document.links + document.references:
            if candidate and candidate not in candidates:
                candidates.append(candidate)

        for candidate in candidates:
            result = self.resolver.resolve(candidate)
            if result.state == ResolutionState.RESOLVED and result.entity_id:
                entity = self.registry.get_entity(result.entity_id)
                if entity is not None:
                    return {
                        "entity_id": entity.entity_id,
                        "canonical_name": entity.canonical_name,
                        "display_name": candidate,
                    }

        for candidate in candidates:
            result = self.resolver.resolve(candidate)
            if result.state in {ResolutionState.NEW_ENTITY, ResolutionState.POSSIBLE_MATCH, ResolutionState.AMBIGUOUS}:
                self.queue.enqueue(
                    canonical_name=candidate,
                    source_context=document.body[:200],
                    notes=f"Unresolved from source: {document.path}",
                )
        return None

    def _queue_unresolved(self, document: SourceDocument) -> None:
        for candidate in [document.title, *(document.links), *(document.references)]:
            if not candidate:
                continue
            result = self.resolver.resolve(candidate)
            if result.state in {ResolutionState.NEW_ENTITY, ResolutionState.POSSIBLE_MATCH, ResolutionState.AMBIGUOUS}:
                self.queue.enqueue(
                    canonical_name=candidate,
                    source_context=document.body[:200],
                    notes=f"Unresolved from source: {document.path}",
                )

    def _extract_explicit_relationships(self, document: SourceDocument, node: ATISNode) -> List[NodeRelationship]:
        relationships: List[NodeRelationship] = []
        seen: set[tuple[str, str, str]] = set()
        provenance = SourceProvenance(
            source_id=str(document.path),
            source_type="markdown",
            source_uri=str(document.path),
            excerpt=document.body[:500] if document.body else document.raw_content[:500],
        )

        for reference in document.references + document.links:
            if not reference:
                continue
            result = self.resolver.resolve(reference)
            if result.state != ResolutionState.RESOLVED or result.entity_id is None:
                continue
            if result.entity_id == node.entity_id:
                continue
            relationship_key = (node.node_id, result.entity_id, "references")
            if relationship_key in seen:
                continue
            seen.add(relationship_key)
            relationship = NodeRelationship(
                source_node_id=node.node_id,
                target_entity_id=result.entity_id,
                relationship_type="references",
                provenance=[provenance],
            )
            try:
                stored = self.store.add_relationship(relationship)
            except NodeStoreError:
                continue
            relationships.append(stored)
        return relationships

    @staticmethod
    def _node_id_for_source(source_path: str, entity_id: str) -> str:
        digest = hashlib.sha256(f"{source_path}|{entity_id}".encode("utf-8")).hexdigest()[:12]
        return f"NODE-{digest.upper()}"
