"""Deterministic orchestration for the existing NORA research-to-import pipeline."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Iterable, List, Optional, Sequence

from app.models import CanonicalNodeRow, ImportBundle, NodeDraft
from app.services.canonical_row_builder import CanonicalNodeRowBuilder
from app.services.claim_classifier import ClaimClassifier
from app.services.entity_resolution.registry import EntityRegistry, ResolutionState
from app.services.entity_resolution.resolver import EntityResolver
from app.services.node_draft_builder import NodeDraftBuilder
from app.services.research.evidence import EvidenceRecord, deduplicate_evidence
from app.services.research.mistral_enrichment import enrich_evidence_with_mistral
from app.services.research.search_provider import SearchProvider
from app.services.research_engine import ResearchClaim, ResearchEngine, ResearchResult
from app.services.rita_intake import RITAEntity


@dataclass
class PipelineResult:
    """The orchestrated output for one entity through research, routing, draft, and export stages."""

    entity: Optional[Any] = None
    evidence: List[EvidenceRecord] = field(default_factory=list)
    claims: List[ResearchClaim] = field(default_factory=list)
    node_draft: Optional[NodeDraft] = None
    canonical_row: Optional[CanonicalNodeRow] = None
    import_bundle: Optional[ImportBundle] = None
    status: str = "pending"
    error_message: Optional[str] = None
    resolution: Optional[Any] = None
    classifications: dict[str, List[str]] = field(default_factory=dict)
    source_entity_id: Optional[str] = None


class EntityPipelineService:
    """Coordinate the existing NORA research, identity, classification, draft, and export stages."""

    def __init__(
        self,
        search_provider: Optional[SearchProvider] = None,
        llm_provider: Optional[Any] = None,
        registry: Optional[EntityRegistry] = None,
        resolver: Optional[EntityResolver] = None,
        research_engine: Optional[ResearchEngine] = None,
        classifier: Optional[ClaimClassifier] = None,
        node_builder: Optional[NodeDraftBuilder] = None,
        row_builder: Optional[CanonicalNodeRowBuilder] = None,
        enricher: Optional[Any] = None,
    ) -> None:
        self.registry = registry or EntityRegistry()
        self.resolver = resolver or EntityResolver(self.registry)
        self.search_provider = search_provider
        self.llm_provider = llm_provider
        self.research_engine = research_engine or ResearchEngine(self.search_provider, llm_provider=None)
        self.classifier = classifier or ClaimClassifier(registry=self.registry, resolver=self.resolver)
        self.node_builder = node_builder or NodeDraftBuilder(registry=self.registry, resolver=self.resolver)
        self.row_builder = row_builder or CanonicalNodeRowBuilder()
        self.enricher = enricher or enrich_evidence_with_mistral

    async def run(self, entity: RITAEntity | str) -> PipelineResult:
        """Run the full deterministic pipeline for one RITA entity or entity name."""
        entity_name, rita_entity = self._coerce_entity(entity)
        if not entity_name:
            return PipelineResult(
                entity=entity,
                status="failed",
                error_message="entity is required",
            )

        source_entity_id = None if rita_entity is None else getattr(rita_entity, "entity_id", None)
        result = PipelineResult(entity=rita_entity or entity_name, status="pending", source_entity_id=source_entity_id)

        research_result = await self.research_engine.research(
            entity_name,
            entity_type=getattr(rita_entity, "rita_type", None) if rita_entity is not None else None,
            context=getattr(rita_entity, "metadata", None) if rita_entity is not None else None,
        )
        result.evidence = deduplicate_evidence(research_result.evidence or [])
        result.resolution = self.resolver.resolve(entity_name, entity_type=getattr(rita_entity, "rita_type", None) if rita_entity is not None else None)

        if research_result.status != "completed" or not result.evidence:
            result.status = "failed"
            result.error_message = research_result.error_message or "Research did not produce usable evidence."
            return result

        claims = await self._enrich_entity(entity_name, result.evidence, entity=rita_entity)
        result.claims = claims
        if not claims:
            result.status = "insufficient"
            result.error_message = "No claim candidates were produced from the supplied evidence."
            return result

        if result.resolution.state in {ResolutionState.AMBIGUOUS, ResolutionState.CONFLICT, ResolutionState.POSSIBLE_MATCH, ResolutionState.NEW_ENTITY}:
            result.status = "ambiguous"
            result.error_message = result.resolution.reasoning or "Subject identity could not be resolved confidently."
            return result

        if result.resolution.state != ResolutionState.RESOLVED:
            result.status = "failed"
            result.error_message = result.resolution.reasoning or "Subject identity resolution failed."
            return result

        result.classifications = self.classifier.route(claims)
        node_draft = self.node_builder.build(claims)
        result.node_draft = node_draft

        try:
            row = self.row_builder.build(node_draft)
        except ValueError as exc:
            result.status = "failed"
            result.error_message = str(exc)
            return result

        result.canonical_row = row
        result.import_bundle = ImportBundle.from_rows([row])
        result.status = "completed"
        return result

    async def run_batch(self, entities: Sequence[RITAEntity | str]) -> list[PipelineResult]:
        """Run the pipeline deterministically over multiple entities while preserving input order."""
        if entities is None:
            return []

        seen: set[str] = set()
        results: list[PipelineResult] = []
        for entity in entities:
            key = self._entity_key(entity)
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            results.append(await self.run(entity))
        return results

    def run_sync(self, entity: RITAEntity | str) -> PipelineResult:
        return asyncio.run(self.run(entity))

    def run_batch_sync(self, entities: Sequence[RITAEntity | str]) -> list[PipelineResult]:
        return asyncio.run(self.run_batch(entities))

    async def _enrich_entity(self, entity_name: str, evidence: Sequence[EvidenceRecord], entity: Optional[RITAEntity] = None) -> List[ResearchClaim]:
        if not evidence:
            return []

        llm_provider = self.llm_provider
        api_key = getattr(llm_provider, "api_key", None) if llm_provider is not None else None
        if not api_key:
            return []

        if self.enricher is not None:
            claims = await self.enricher(entity_name, list(evidence), api_key=api_key, model=getattr(llm_provider, "model", None) if llm_provider is not None else None)
            if isinstance(claims, list):
                return [claim for claim in claims if isinstance(claim, ResearchClaim)]
            return []
        return []

    @staticmethod
    def _coerce_entity(entity: RITAEntity | str) -> tuple[str, Optional[RITAEntity]]:
        if entity is None:
            return "", None
        if isinstance(entity, RITAEntity):
            return (str(entity.name).strip(), entity)
        text = str(entity).strip()
        if not text:
            return "", None
        return text, None

    @staticmethod
    def _entity_key(entity: RITAEntity | str) -> str:
        if entity is None:
            return ""
        if isinstance(entity, RITAEntity):
            return str(entity.entity_id).strip() or str(entity.name).strip()
        text = str(entity).strip()
        return text.lower()


NoraPipeline = EntityPipelineService
