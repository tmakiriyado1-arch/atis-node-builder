"""Research engine and source-backed search pipeline for NORA."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from app import config
from app.services.research.evidence import EvidenceRecord, deduplicate_evidence, normalize_search_result
from app.services.research.mistral_enrichment import enrich_evidence_with_mistral
from app.services.research.search_provider import SearchProvider


@dataclass
class ResearchClaim:
    """A claim extracted from research evidence."""

    claim: str = ""
    field_name: str = "candidate_claim"
    source_url: str = ""
    source_title: Optional[str] = None
    publication_date: Optional[str] = None
    evidence_passage: str = ""
    source_type: str = "webpage"
    confidence: float = 0.0
    extraction_method: str = "search_result"
    extracted_at: datetime = field(default_factory=datetime.now)
    subject: Optional[str] = None
    predicate: Optional[str] = None
    object: Optional[str] = None
    claim_text: Optional[str] = None
    evidence_urls: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.claim_text is None:
            self.claim_text = self.claim or ""
        if not self.claim:
            self.claim = self.claim_text or ""
        if not self.subject and self.claim_text:
            match = re.search(
                r"^(?P<subject>.+?)\s+(?P<predicate>regulates|manages|oversees|supports|operates|provides|governs|controls|establishes|requires|enforces|includes|covers|monitors|administers|coordinates|maintains|owns|leads|is|was|used in|connected to|relevant to|associated with|related to)\s+(?P<object>.+)$",
                self.claim_text,
                flags=re.IGNORECASE,
            )
            if match:
                self.subject = match.group("subject").strip(" .")
                self.predicate = match.group("predicate").strip().lower()
                self.object = match.group("object").strip(" .")
        if not self.evidence_urls and self.source_url:
            self.evidence_urls = [self.source_url]
        if self.object is None and self.subject and self.predicate and self.claim_text:
            self.object = self.claim_text.replace(self.subject, "", 1).replace(self.predicate, "", 1).strip(" .")


@dataclass
class ResearchResult:
    """Result of researching an entity."""

    entity_name: str
    claims: List[ResearchClaim] = field(default_factory=list)
    summary: str = ""
    sources_count: int = 0
    research_completed_at: datetime = field(default_factory=datetime.now)
    status: str = "completed"
    error_message: Optional[str] = None
    evidence: List[EvidenceRecord] = field(default_factory=list)

    def add_claim(
        self,
        claim: str,
        field_name: str,
        source_url: str,
        source_title: Optional[str] = None,
        evidence_passage: str = "",
        confidence: float = 0.0,
        subject: Optional[str] = None,
        predicate: Optional[str] = None,
        object: Optional[str] = None,
        claim_text: Optional[str] = None,
        evidence_urls: Optional[List[str]] = None,
    ) -> None:
        """Add extracted claim to result."""
        self.claims.append(
            ResearchClaim(
                claim=claim,
                field_name=field_name,
                source_url=source_url,
                source_title=source_title,
                evidence_passage=evidence_passage,
                confidence=confidence,
                subject=subject,
                predicate=predicate,
                object=object,
                claim_text=claim_text or claim,
                evidence_urls=list(evidence_urls) if evidence_urls else ([source_url] if source_url else []),
            )
        )


class ResearchEngine:
    """Deterministic research pipeline using a search provider and evidence snippets."""

    def __init__(self, search_provider: Optional[SearchProvider], llm_provider: Optional[Any] = None):
        self.search_provider = search_provider
        self.llm_provider = llm_provider

    def generate_queries(
        self,
        entity_name: str,
        entity_type: Optional[str] = None,
        context: Optional[str] = None,
        max_queries: int = 2,
    ) -> List[str]:
        """Generate a small set of deterministic search queries for the entity."""
        cleaned_name = (entity_name or "").strip()
        queries: List[str] = []

        if cleaned_name:
            queries.append(cleaned_name)

        if len(queries) >= max_queries:
            return queries[:max_queries]

        contextual_parts = []
        if entity_type and str(entity_type).strip():
            contextual_parts.append(str(entity_type).strip())
        if context and str(context).strip():
            contextual_parts.append(str(context).strip())

        if contextual_parts:
            secondary = " ".join([cleaned_name, *contextual_parts]).strip() if cleaned_name else " ".join(contextual_parts).strip()
            if secondary and secondary not in queries:
                queries.append(secondary)

        return queries[:max_queries]

    async def research(
        self,
        entity_name: str,
        entity_type: Optional[str] = None,
        fields_to_research: Optional[List[str]] = None,
        context: Optional[str] = None,
    ) -> ResearchResult:
        """Search for public evidence, deduplicate sources, and return structured results."""
        cleaned_name = (entity_name or "").strip()
        result = ResearchResult(entity_name=cleaned_name or "", status="failed")

        if not cleaned_name:
            result.error_message = "entity_name is required for research"
            return result

        if self.search_provider is None:
            result.error_message = "No search provider is configured for research"
            return result

        queries = self.generate_queries(cleaned_name, entity_type=entity_type, context=context, max_queries=2)
        evidence_records: List[EvidenceRecord] = []
        claims: List[ResearchClaim] = []

        for query in queries:
            try:
                search_results = await self.search_provider.search(query, max_results=5)
            except Exception as exc:  # pragma: no cover - exercised via provider harness
                result.error_message = f"Search provider failed while researching '{cleaned_name}': {exc}"
                result.summary = "Research failed before useful evidence could be collected."
                return result

            if not isinstance(search_results, list):
                continue

            for item in search_results:
                record = normalize_search_result(
                    item,
                    entity_id=None,
                    entity_name=cleaned_name,
                    query=query,
                    source="public_web_search",
                )
                if record is not None:
                    evidence_records.append(record)

        deduped_evidence = deduplicate_evidence(evidence_records)
        if not deduped_evidence:
            result.error_message = (
                f"No usable search results were returned for '{cleaned_name}'. "
                "The provider did not surface enough public evidence to continue this slice."
            )
            result.summary = "No public evidence was available for this entity in the current research slice."
            return result

        if self.llm_provider is not None:
            try:
                claims = await enrich_evidence_with_mistral(
                    cleaned_name,
                    deduped_evidence,
                    api_key=getattr(self.llm_provider, "api_key", config.MISTRAL_API_KEY),
                )
            except Exception:
                claims = []
            if not claims:
                claims = []
        if not claims:
            for evidence in deduped_evidence:
                field_name = (fields_to_research or ["entity_profile"])[0]
                claims.append(
                    ResearchClaim(
                        claim=evidence.snippet,
                        field_name=field_name,
                        source_url=evidence.url,
                        source_title=evidence.title or None,
                        evidence_passage=evidence.snippet,
                        source_type="webpage",
                        confidence=0.0,
                        extraction_method="search_result",
                        extracted_at=datetime.now(),
                    )
                )

        result.claims = claims
        result.evidence = deduped_evidence
        result.sources_count = len(deduped_evidence)
        result.status = "completed"
        result.research_completed_at = datetime.now()
        result.summary = (
            f"Searched for '{cleaned_name}' and collected {len(deduped_evidence)} deduplicated evidence record(s). "
            "Candidate claims were produced only from the supplied evidence. No facts were verified."
        )
        return result
