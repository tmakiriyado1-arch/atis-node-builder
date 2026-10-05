"""Mistral Web Research Provider for NORA.

This module provides a web-capable research agent that uses Mistral's
agent/tool infrastructure to perform web research. It:

1. Accepts candidate URLs from NORA's search gateway
2. Uses Mistral's web browsing tools to open/read URLs
3. Evaluates source relevance and entity identity
4. Extracts grounded, verifiable evidence
5. Returns structured research results

Architecture:
    NORA discovers candidate URLs
        ↓
    Mistral web agent researches/verifies sources
        ↓
    NORA validates and structures the resulting evidence

The key principle: Mistral performs web research. NORA owns truth validation,
provenance, ontology, persistence, and downstream node construction.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence

from app import config
from app.logging import logger
from app.services.research.evidence import EvidenceRecord


# =============================================================================
# Entity Match Types
# =============================================================================

class EntityMatchType(str, Enum):
    """Identity assessment statuses for source matching."""
    DIRECT = "DIRECT"           # Source clearly concerns the target entity
    ALIAS = "ALIAS"             # Source uses a known/valid alternate name
    CONTEXTUAL = "CONTEXTUAL"   # Context strongly establishes entity identity
    AMBIGUOUS = "AMBIGUOUS"     # Might concern entity, but identity unclear
    FALSE = "FALSE"             # Source concerns another entity


# =============================================================================
# Evidence Types
# =============================================================================

class EvidenceType(str, Enum):
    """Classification of extracted evidence by semantic type."""
    FACT = "FACT"               # Discrete factual statement
    ATTRIBUTE = "ATTRIBUTE"     # Entity property/characteristic
    RELATIONSHIP = "RELATIONSHIP"  # Explicit directional relationship
    ASSOCIATION = "ASSOCIATION"   # Meaningful connection
    SUMMARY = "SUMMARY"         # Concise source-grounded description


# =============================================================================
# Evidence Levels
# =============================================================================

class EvidenceLevel(str, Enum):
    """Level of explicitness for evidence."""
    DIRECT = "DIRECT"           # Directly stated in source
    STRONG_CONTEXTUAL = "STRONG_CONTEXTUAL"  # Strong contextual support
    INFERRED = "INFERRED"       # Inferred (must NOT be promoted to fact)


# =============================================================================
# Research Status
# =============================================================================

class ResearchStatus(str, Enum):
    """Overall research status."""
    SUFFICIENT = "SUFFICIENT"   # Enough trustworthy evidence found
    INSUFFICIENT = "INSUFFICIENT"  # Not enough trustworthy evidence
    AMBIGUOUS = "AMBIGUOUS"     # Entity identity ambiguous
    FALSE_ENTITY = "FALSE_ENTITY"  # No sources concern target entity
    FAILED = "FAILED"           # Research failed (API error, etc.)


# =============================================================================
# Rejection Reasons
# =============================================================================

class RejectionReason(str, Enum):
    """Reasons for rejecting sources or evidence."""
    ENTITY_MISMATCH = "ENTITY_MISMATCH"
    NO_USABLE_TEXT = "NO_USABLE_TEXT"
    MISTRAL_FAILURE = "MISTRAL_FAILURE"
    INVALID_JSON = "INVALID_JSON"
    INVALID_PASSAGE = "INVALID_PASSAGE"
    NO_SUPPORTED_FACTS = "NO_SUPPORTED_FACTS"
    AMBIGUOUS_ENTITY = "AMBIGUOUS_ENTITY"
    FALSE_ENTITY = "FALSE_ENTITY"
    DUPLICATE = "DUPLICATE"
    IRRELEVANT = "IRRELEVANT"
    UNTRUSTWORTHY_SOURCE = "UNTRUSTWORTHY_SOURCE"


# =============================================================================
# Data Models
# =============================================================================

@dataclass
class SourceAssessment:
    """Assessment of a source's relevance to the target entity."""
    url: str
    title: Optional[str] = None
    entity_match: bool = False
    match_type: EntityMatchType = EntityMatchType.FALSE
    match_confidence: float = 0.0
    is_usable: bool = False
    rejection_reason: Optional[RejectionReason] = None
    quality_notes: Optional[str] = None


@dataclass
class EvidenceItem:
    """A single atomic evidence item from a source."""
    evidence_id: str
    source_url: str
    source_title: Optional[str] = None
    evidence_type: EvidenceType = EvidenceType.FACT
    evidence_level: EvidenceLevel = EvidenceLevel.DIRECT
    subject: str = ""
    predicate: str = ""
    object: str = ""
    claim: str = ""
    passage: str = ""
    confidence: float = 0.0
    chunk_index: int = 0
    
    def __post_init__(self):
        # Generate claim if not provided
        if not self.claim and self.subject and self.predicate and self.object:
            self.claim = f"{self.subject} {self.predicate} {self.object}"


@dataclass
class SourceResult:
    """Research result from a single source URL."""
    url: str
    assessment: SourceAssessment
    evidence: List[EvidenceItem] = field(default_factory=list)
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    errors: List[str] = field(default_factory=list)
    
    @property
    def is_accepted(self) -> bool:
        return self.assessment.is_usable and self.assessment.entity_match
    
    @property
    def evidence_count(self) -> int:
        return len(self.evidence)


@dataclass
class MistralResearchResult:
    """Complete research result from Mistral web research agent."""
    entity_name: str
    entity_type: Optional[str] = None
    research_status: ResearchStatus = ResearchStatus.INSUFFICIENT
    sources_examined: int = 0
    sources_accepted: int = 0
    sources_rejected: int = 0
    evidence_items: List[EvidenceItem] = field(default_factory=list)
    source_results: List[SourceResult] = field(default_factory=list)
    conflicts: List[Dict[str, Any]] = field(default_factory=list)
    uncertainties: List[Dict[str, Any]] = field(default_factory=list)
    rejected_sources: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    diagnostics: Dict[str, Any] = field(default_factory=dict)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    
    @property
    def accepted_evidence_count(self) -> int:
        return sum(sr.evidence_count for sr in self.source_results if sr.is_accepted)
    
    @property
    def total_evidence_count(self) -> int:
        return sum(sr.evidence_count for sr in self.source_results)
    
    def to_evidence_records(self) -> List[EvidenceRecord]:
        """Convert to EvidenceRecord list for backward compatibility."""
        records = []
        for source_result in self.source_results:
            if not source_result.is_accepted:
                continue
            for evidence in source_result.evidence:
                record = EvidenceRecord(
                    url=evidence.source_url,
                    title=evidence.source_title or source_result.assessment.title or "",
                    snippet=evidence.passage[:500] + "..." if len(evidence.passage) > 500 else evidence.passage,
                    content=evidence.passage,
                    normalized_text=evidence.passage,
                    source="mistral_web_research",
                    query=self.entity_name,
                    entity_name=self.entity_name,
                    entity_id=None,
                    metadata={
                        "research_method": "mistral_web_agent",
                        "evidence_id": evidence.evidence_id,
                        "evidence_type": evidence.evidence_type.value,
                        "evidence_level": evidence.evidence_level.value,
                        "match_type": source_result.assessment.match_type.value,
                        "match_confidence": source_result.assessment.match_confidence,
                    },
                )
                records.append(record)
        return records
    
    def to_research_claims(self) -> List["ResearchClaim"]:
        """Convert evidence to ResearchClaim list for backward compatibility."""
        from app.services.research_engine import ResearchClaim
        
        claims = []
        for source_result in self.source_results:
            if not source_result.is_accepted:
                continue
            for evidence in source_result.evidence:
                claim = ResearchClaim(
                    claim=evidence.claim,
                    claim_text=evidence.claim,
                    field_name=self._evidence_type_to_field_name(evidence.evidence_type),
                    source_url=evidence.source_url,
                    source_title=evidence.source_title or source_result.assessment.title,
                    evidence_passage=evidence.passage,
                    source_type="webpage",
                    confidence=evidence.confidence,
                    extraction_method="mistral_web_research",
                    extracted_at=datetime.now(timezone.utc),
                    subject=evidence.subject,
                    predicate=evidence.predicate,
                    object=evidence.object,
                    evidence_urls=[evidence.source_url],
                    metadata={
                        "research_method": "mistral_web_agent",
                        "evidence_id": evidence.evidence_id,
                        "evidence_type": evidence.evidence_type.value,
                        "evidence_level": evidence.evidence_level.value,
                        "match_type": source_result.assessment.match_type.value,
                        "match_confidence": source_result.assessment.match_confidence,
                        "source_assessment": source_result.assessment.entity_match,
                    },
                )
                claims.append(claim)
        return claims
    
    def _evidence_type_to_field_name(self, evidence_type: EvidenceType) -> str:
        mapping = {
            EvidenceType.FACT: "fact",
            EvidenceType.ATTRIBUTE: "attribute",
            EvidenceType.RELATIONSHIP: "relationship",
            EvidenceType.ASSOCIATION: "association",
            EvidenceType.SUMMARY: "summary",
        }
        return mapping.get(evidence_type, "candidate_claim")


@dataclass
class ResearchContext:
    """Context for a research request."""
    entity_name: str
    entity_type: Optional[str] = None
    aliases: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    candidate_urls: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_name": self.entity_name,
            "entity_type": self.entity_type,
            "aliases": self.aliases,
            "metadata": self.metadata,
            "candidate_urls": self.candidate_urls,
        }


# =============================================================================
# Mistral Web Research Provider
# =============================================================================

class MistralWebResearchProvider:
    """Provider for Mistral web research agent.
    
    This provider uses Mistral's web-capable agent tools to:
    1. Open and read candidate URLs
    2. Evaluate source relevance and entity identity
    3. Extract grounded, verifiable evidence
    4. Return structured research results
    
    The provider accepts candidate URLs from NORA's search gateway and
    returns structured evidence that can be consumed by NORA's downstream
    validation and node construction pipeline.
    
    Usage:
        provider = MistralWebResearchProvider(
            api_key=config.MISTRAL_API_KEY,
            model=config.MISTRAL_RESEARCH_MODEL,
        )
        
        context = ResearchContext(
            entity_name="Theotechnic College",
            entity_type="Educational Institution",
            aliases=["Theotec", "Theotechnic"],
            metadata={"country": "Zimbabwe"},
            candidate_urls=["https://www.theotec.org/about", "https://www.activeministry.org/theotechnic"],
        )
        
        result = await provider.research(context)
        
        # Convert to EvidenceRecords for NORA pipeline
        evidence_records = result.to_evidence_records()
        
        # Or convert directly to ResearchClaims
        claims = result.to_research_claims()
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 60.0,
        max_retries: int = 2,
    ):
        """Initialize the Mistral web research provider.
        
        Args:
            api_key: Mistral API key (defaults to config.MISTRAL_API_KEY)
            model: Model to use (defaults to config.MISTRAL_RESEARCH_MODEL or MISTRAL_MODEL)
            timeout: Timeout for API calls
            max_retries: Maximum retries for failed calls
        """
        self.api_key = api_key or (config.MISTRAL_API_KEY or "").strip()
        self.model = model or (config.MISTRAL_RESEARCH_MODEL or config.MISTRAL_MODEL or "mistral-large-latest")
        self.timeout = timeout
        self.max_retries = max_retries
        
        logger.info(f"[MISTRAL_WEB_RESEARCH] Provider initialized: model={self.model}, timeout={self.timeout}s")
    
    async def research(
        self,
        context: ResearchContext,
        client: Any = None,
    ) -> MistralResearchResult:
        """Perform web research using Mistral's agent capabilities.
        
        This is the main entry point. It:
        1. Constructs a research prompt with the target entity and candidate URLs
        2. Calls Mistral with web browsing tools enabled
        3. Parses the structured response
        4. Validates the results
        5. Returns a MistralResearchResult
        
        Args:
            context: ResearchContext with entity info and candidate URLs
            client: Optional httpx.AsyncClient for reuse
            
        Returns:
            MistralResearchResult with structured evidence
        """
        import httpx
        import uuid
        
        if not self.api_key:
            logger.error("[MISTRAL_WEB_RESEARCH] No API key configured")
            return MistralResearchResult(
                entity_name=context.entity_name,
                entity_type=context.entity_type,
                research_status=ResearchStatus.FAILED,
                errors=["No Mistral API key configured"],
                diagnostics={"error": "no_api_key"},
            )
        
        if not context.candidate_urls:
            logger.warning("[MISTRAL_WEB_RESEARCH] No candidate URLs provided")
            return MistralResearchResult(
                entity_name=context.entity_name,
                entity_type=context.entity_type,
                research_status=ResearchStatus.INSUFFICIENT,
                errors=["No candidate URLs to research"],
                diagnostics={"candidate_url_count": 0},
            )
        
        # Build the research prompt
        prompt = self._build_research_prompt(context)
        
        # Log diagnostics
        logger.info(f"[MISTRAL_WEB_RESEARCH] Starting research for entity={context.entity_name}")
        logger.info(f"[MISTRAL_WEB_RESEARCH] candidate_urls={len(context.candidate_urls)}, model={self.model}")
        
        # Call Mistral with web browsing tools
        result = await self._call_mistral_web_research(prompt, context, client)
        
        if result is None:
            logger.error(f"[MISTRAL_WEB_RESEARCH] Mistral call failed for entity={context.entity_name}")
            return MistralResearchResult(
                entity_name=context.entity_name,
                entity_type=context.entity_type,
                research_status=ResearchStatus.FAILED,
                errors=["Mistral API call failed"],
                diagnostics={"error": "api_call_failed"},
            )
        
        # Parse and validate the response
        research_result = self._parse_research_response(context, result)
        
        # Mark completion
        research_result.completed_at = datetime.now(timezone.utc)
        
        # Log final diagnostics
        logger.info(f"[MISTRAL_WEB_RESEARCH] Completed: status={research_result.research_status.value}")
        logger.info(f"[MISTRAL_WEB_RESEARCH] sources_examined={research_result.sources_examined}, sources_accepted={research_result.sources_accepted}, sources_rejected={research_result.sources_rejected}")
        logger.info(f"[MISTRAL_WEB_RESEARCH] evidence_items={research_result.total_evidence_count}, accepted_evidence={research_result.accepted_evidence_count}")
        
        return research_result
    
    def _build_research_prompt(self, context: ResearchContext) -> str:
        """Build the research prompt for Mistral web agent.
        
        Args:
            context: ResearchContext with entity info and candidate URLs
            
        Returns:
            Prompt string for Mistral
        """
        # Build ontology context
        from app.services.ontology import get_ontology
        ontology = get_ontology()
        
        ontology_context = f"""Canonical ATIS Ontology:
- Entity Types: {', '.join(sorted(ontology.all_entity_types))}
- Relationship Predicates: {', '.join(sorted(ontology.relationship_predicates))}
- Association Predicates: {', '.join(sorted(ontology.association_predicates))}
- Countries: {', '.join(sorted(ontology.countries))}
- Sectors: {', '.join(sorted(ontology.sectors))}
- Statuses: {', '.join(sorted(ontology.statuses))}

Ontology Rules:
- Use ONLY canonical ontology values.
- Use EXACT ontology values (case-sensitive).
- If evidence does not support a classification, return NO claim rather than inventing.
"""
        
        # Build candidate URLs list
        urls_json = json.dumps(context.candidate_urls, ensure_ascii=False)
        
        # Build aliases list
        aliases_json = json.dumps(context.aliases, ensure_ascii=False) if context.aliases else "[]"
        
        # Build metadata JSON
        metadata_json = json.dumps(context.metadata, ensure_ascii=False) if context.metadata else "{}"
        
        prompt = f"""You are the web research agent for NORA.

## ROLE
Your job is to investigate one specific real-world entity using web search and source URLs, then return only grounded, verifiable evidence about that entity.

You are NOT a web search engine.
You are NOT allowed to browse for additional information beyond what is necessary to investigate the provided candidate URLs.
You are NOT allowed to use your pretrained knowledge to fill gaps.
You must use the candidate URLs as starting points and may follow links from those pages.

## TARGET ENTITY
Entity Name: {context.entity_name}
Entity Type: {context.entity_type or 'unknown'}
Aliases: {aliases_json}
Metadata: {metadata_json}

## CANDIDATE URLs
These are leads, not trusted evidence. You may:
- Open candidate URLs
- Inspect them
- Evaluate source relevance
- Verify entity identity
- Reject false entities
- Search for additional sources if needed
- Follow useful sources
- Compare sources
- Identify the correct entity

Candidate URLs: {urls_json}

## ENTITY MATCHING
Before extracting evidence, determine whether each source actually concerns the target entity.

Return entity_match with one of these statuses:
- DIRECT: The source clearly concerns the target entity
- ALIAS: The source uses a known or clearly valid alternate name for the same entity
- CONTEXTUAL: The source does not repeat the canonical name but surrounding context strongly establishes it concerns the target entity
- AMBIGUOUS: The source might concern the entity, but identity cannot be established confidently
- FALSE: The source concerns another entity

Only DIRECT, ALIAS, and sufficiently strong CONTEXTUAL matches may produce evidence.
AMBIGUOUS and FALSE sources must not generate factual evidence.

## SOURCE QUALITY
Do not equate HTTP 200 with usable source.
Evaluate whether the source actually contains meaningful information.

Reject:
- Unrelated organizations
- Search-result snippets
- Duplicate content
- Obvious false matches
- Empty pages
- Login pages
- Challenge pages
- Irrelevant directories
- Generic pages that merely contain a similar word
- Pages whose identity cannot be established

A search result is a discovery mechanism, not evidence.

## EVIDENCE TYPES
Evidence may be classified as:
- FACT: A discrete factual statement. Example: "The organization was established in 2018."
- ATTRIBUTE: A property of the entity. Examples: country, location, headquarters, entity_type, sector, status, founded_date, website, registration, ownership.
- RELATIONSHIP: An explicit directional relationship. Examples: operates, owns, manages, regulates, governs, oversees, administers, parent_of, subsidiary_of, located_in, part_of, offers, serves.
  Only use predicates permitted by the ATIS ontology.
- ASSOCIATION: A meaningful connection. Examples: member_of, partner_of, affiliated_with, associated_with, accredited_by, works_with.
- SUMMARY: A concise source-grounded description when appropriate.

Do not manufacture relationships from proximity.
For example: "A mentions B" does NOT automatically mean "A owns B", "A operates B", etc.
Those relationships require explicit evidence.

## EXACT PASSAGE REQUIREMENT
Every factual evidence item MUST contain the exact supporting passage from the source.
The passage must be:
- Verbatim
- Attributable to the source
- Sufficient to support the claim

Do NOT generate a paraphrase and label it as a passage.
If the source does not clearly support a claim, do not produce the claim.

## PROVENANCE
Every evidence item must include: source_url, source_title, evidence_type, passage, claim.
Optionally include: published_at, retrieved_at, author (when actually available).
Never invent publication dates, authors, or metadata.

## CLAIMS
A claim must be directly supported by one or more evidence records.
Conceptually: Claim -> Evidence -> Source -> URL.
Do not return unsupported claims.
If multiple sources support the same claim, reference all relevant evidence.

## RELATIONSHIPS AND ASSOCIATIONS
Relationships are particularly important for NORA.
Only extract relationships that are explicitly established.
If relationship certainty is weak, return it under uncertainty instead of treating it as established.

## CONFLICTS
If trustworthy sources disagree, do not silently choose one.
Return a structured conflict with both claims and their sources.

## UNCERTAINTY
Return uncertain findings separately.
Do not convert uncertainty into fact.

## OUTPUT SCHEMA
Return JSON only with this exact schema:

{{
  "entity_assessment": {{
    "entity_name": "{context.entity_name}",
    "entity_type": "{context.entity_type or 'unknown'}",
    "overall_match": true/false,
    "match_notes": "..."
  }},
  "sources": [
    {{
      "url": "https://example.org",
      "title": "...",
      "entity_match": true/false,
      "match_type": "DIRECT|ALIAS|CONTEXTUAL|AMBIGUOUS|FALSE",
      "match_confidence": 0.0-1.0,
      "is_usable": true/false,
      "rejection_reason": "..." or null,
      "evidence": [
        {{
          "evidence_id": "uuid",
          "source_url": "https://example.org",
          "source_title": "...",
          "evidence_type": "FACT|ATTRIBUTE|RELATIONSHIP|ASSOCIATION|SUMMARY",
          "evidence_level": "DIRECT|STRONG_CONTEXTUAL|INFERRED",
          "subject": "...",
          "predicate": "...",
          "object": "...",
          "claim": "...",
          "passage": "EXACT VERBATIM SOURCE PASSAGE",
          "confidence": 0.0-1.0,
          "chunk_index": 0
        }}
      ]
    }}
  ],
  "conflicts": [],
  "uncertainties": [],
  "rejected_sources": [
    {{
      "url": "https://example.com",
      "reason": "FALSE_ENTITY|AMBIGUOUS|IRRELEVANT|..."
    }}
  ],
  "errors": []
}}

## ONTOLOGY
{ontology_context}

## INSTRUCTIONS
1. Open each candidate URL
2. Verify if it concerns the target entity
3. Extract evidence with exact passages
4. Classify evidence by type and level
5. Return structured JSON only
6. Do not return prose outside the JSON object
"""
        
        return prompt
    
    async def _call_mistral_web_research(
        self,
        prompt: str,
        context: ResearchContext,
        client: Any = None,
    ) -> Optional[Dict[str, Any]]:
        """Call Mistral API with web browsing tools.
        
        Note: This uses the chat/completions endpoint with the web-search capable model.
        The Mistral API with models like mistral-large-latest supports web browsing
        when the appropriate tools are available.
        
        Args:
            prompt: The research prompt
            context: ResearchContext for diagnostics
            client: Optional httpx.AsyncClient for reuse
            
        Returns:
            Parsed JSON response or None on failure
        """
        import httpx
        
        # Build messages with web browsing tool request
        # For web-capable models, we use the web_search tool
        messages = [
            {
                "role": "user",
                "content": prompt,
            }
        ]
        
        # Tool configuration for web browsing
        # Note: The exact tool specification depends on the Mistral model capabilities
        # For mistral-large-latest and similar, web browsing is available through tools
        tools = [
            {
                "type": "web_search",
                "url": context.candidate_urls,
            }
        ]
        
        payload = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "temperature": 0.0,
            "top_p": 1.0,
            "response_format": {"type": "json_object"},
        }
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        for attempt in range(self.max_retries + 1):
            try:
                if client is not None:
                    response = await client.post(
                        "https://api.mistral.ai/v1/chat/completions",
                        headers=headers,
                        json=payload,
                        timeout=self.timeout,
                    )
                else:
                    async with httpx.AsyncClient(headers=headers, timeout=self.timeout) as http_client:
                        response = await http_client.post(
                            "https://api.mistral.ai/v1/chat/completions",
                            json=payload,
                        )
                
                response.raise_for_status()
                json_response = response.json()
                
                # Handle both standard and tool response formats
                choices = json_response.get("choices") or []
                if not isinstance(choices, list) or not choices:
                    # Check for tool output
                    tool_outputs = json_response.get("tool_outputs") or []
                    if tool_outputs:
                        # Extract content from tool outputs
                        content = tool_outputs[0].get("content", "") if tool_outputs else ""
                        try:
                            return json.loads(content)
                        except (TypeError, ValueError):
                            if attempt < self.max_retries:
                                continue
                            return None
                    if attempt < self.max_retries:
                        continue
                    return None
                
                raw_content = choices[0].get("message", {}).get("content") if isinstance(choices[0], dict) else ""
                if not isinstance(raw_content, str):
                    if attempt < self.max_retries:
                        continue
                    return None
                
                try:
                    parsed = json.loads(raw_content)
                    return parsed
                except (TypeError, ValueError):
                    if attempt < self.max_retries:
                        continue
                    return None
                    
            except Exception as e:
                logger.warning(f"[MISTRAL_WEB_RESEARCH] Attempt {attempt + 1} failed: {e}")
                if attempt < self.max_retries:
                    continue
                return None
        
        return None
    
    def _parse_research_response(
        self,
        context: ResearchContext,
        result: Dict[str, Any],
    ) -> MistralResearchResult:
        """Parse Mistral response into MistralResearchResult.
        
        Args:
            context: ResearchContext for the research request
            result: Parsed JSON response from Mistral
            
        Returns:
            MistralResearchResult with structured evidence
        """
        import uuid
        
        # Initialize result
        research_result = MistralResearchResult(
            entity_name=context.entity_name,
            entity_type=context.entity_type,
            research_status=ResearchStatus.INSUFFICIENT,
        )
        
        # Parse entity assessment
        entity_assessment = result.get("entity_assessment", {})
        if isinstance(entity_assessment, dict):
            research_result.diagnostics["entity_assessment"] = entity_assessment
        
        # Parse sources
        sources = result.get("sources") or []
        if not isinstance(sources, list):
            research_result.errors.append("Invalid sources format in response")
            research_result.research_status = ResearchStatus.FAILED
            return research_result
        
        research_result.sources_examined = len(sources)
        
        # Process each source
        for source_data in sources:
            if not isinstance(source_data, dict):
                continue
            
            # Parse source assessment
            assessment = self._parse_source_assessment(source_data)
            source_result = SourceResult(
                url=assessment.url,
                assessment=assessment,
            )
            
            # Parse evidence items
            evidence_data = source_data.get("evidence") or []
            for ev_data in evidence_data:
                if isinstance(ev_data, dict):
                    evidence = self._parse_evidence_item(ev_data, assessment.url)
                    if evidence:
                        source_result.evidence.append(evidence)
            
            # Track errors
            source_errors = source_data.get("errors") or []
            if isinstance(source_errors, list):
                source_result.errors.extend(source_errors)
            
            research_result.source_results.append(source_result)
            
            # Update counters
            if source_result.is_accepted:
                research_result.sources_accepted += 1
            else:
                research_result.sources_rejected += 1
                # Add to rejected sources list
                research_result.rejected_sources.append({
                    "url": assessment.url,
                    "reason": assessment.rejection_reason.value if assessment.rejection_reason else "UNKNOWN",
                    "match_type": assessment.match_type.value,
                    "match_confidence": assessment.match_confidence,
                })
        
        # Parse conflicts
        conflicts = result.get("conflicts") or []
        if isinstance(conflicts, list):
            research_result.conflicts = conflicts
        
        # Parse uncertainties
        uncertainties = result.get("uncertainties") or []
        if isinstance(uncertainties, list):
            research_result.uncertainties = uncertainties
        
        # Parse rejected sources (if provided separately)
        rejected = result.get("rejected_sources") or []
        if isinstance(rejected, list):
            research_result.rejected_sources.extend(rejected)
        
        # Parse errors
        errors = result.get("errors") or []
        if isinstance(errors, list):
            research_result.errors.extend(errors)
        
        # Collect all evidence items
        for source_result in research_result.source_results:
            research_result.evidence_items.extend(source_result.evidence)
        
        # Determine overall research status
        research_result.research_status = self._determine_research_status(research_result)
        
        return research_result
    
    def _parse_source_assessment(self, source_data: Dict[str, Any]) -> SourceAssessment:
        """Parse source assessment from Mistral response.
        
        Args:
            source_data: Source data from Mistral response
            
        Returns:
            SourceAssessment
        """
        url = source_data.get("url", "")
        title = source_data.get("title")
        entity_match = bool(source_data.get("entity_match", False))
        match_type_str = str(source_data.get("match_type") or "FALSE").upper()
        match_confidence = float(source_data.get("match_confidence") or 0.0)
        is_usable = bool(source_data.get("is_usable", False))
        rejection_reason_str = str(source_data.get("rejection_reason") or "").upper()
        quality_notes = source_data.get("quality_notes")
        
        # Parse match type
        try:
            match_type = EntityMatchType(match_type_str)
        except ValueError:
            match_type = EntityMatchType.FALSE
        
        # Parse rejection reason
        rejection_reason = None
        if rejection_reason_str:
            try:
                rejection_reason = RejectionReason(rejection_reason_str)
            except ValueError:
                pass
        
        return SourceAssessment(
            url=url,
            title=title,
            entity_match=entity_match,
            match_type=match_type,
            match_confidence=match_confidence,
            is_usable=is_usable,
            rejection_reason=rejection_reason,
            quality_notes=quality_notes,
        )
    
    def _parse_evidence_item(self, ev_data: Dict[str, Any], source_url: str) -> Optional[EvidenceItem]:
        """Parse evidence item from Mistral response.
        
        Args:
            ev_data: Evidence data from Mistral response
            source_url: Source URL for the evidence
            
        Returns:
            EvidenceItem or None if invalid
        """
        # Required fields
        evidence_id = str(ev_data.get("evidence_id") or f"ev_{uuid.uuid4()}")
        source_title = ev_data.get("source_title")
        evidence_type_str = str(ev_data.get("evidence_type") or "FACT").upper()
        evidence_level_str = str(ev_data.get("evidence_level") or "DIRECT").upper()
        subject = str(ev_data.get("subject") or "")
        predicate = str(ev_data.get("predicate") or "").lower()
        object_val = str(ev_data.get("object") or "")
        claim = str(ev_data.get("claim") or "")
        passage = str(ev_data.get("passage") or "")
        confidence = float(ev_data.get("confidence") or 0.8)
        chunk_index = int(ev_data.get("chunk_index") or 0)
        
        # Validate required fields
        if not passage:
            logger.warning(f"[MISTRAL_WEB_RESEARCH] Evidence item missing passage: {evidence_id}")
            return None
        
        if not claim:
            # Generate claim from subject-predicate-object if available
            if subject and predicate and object_val:
                claim = f"{subject} {predicate} {object_val}"
            else:
                logger.warning(f"[MISTRAL_WEB_RESEARCH] Evidence item missing claim: {evidence_id}")
                return None
        
        # Parse evidence type
        try:
            evidence_type = EvidenceType(evidence_type_str)
        except ValueError:
            evidence_type = EvidenceType.FACT
        
        # Parse evidence level
        try:
            evidence_level = EvidenceLevel(evidence_level_str)
        except ValueError:
            evidence_level = EvidenceLevel.DIRECT
        
        return EvidenceItem(
            evidence_id=evidence_id,
            source_url=source_url,
            source_title=source_title,
            evidence_type=evidence_type,
            evidence_level=evidence_level,
            subject=subject,
            predicate=predicate,
            object=object_val,
            claim=claim,
            passage=passage,
            confidence=confidence,
            chunk_index=chunk_index,
        )
    
    def _determine_research_status(self, result: MistralResearchResult) -> ResearchStatus:
        """Determine overall research status based on results.
        
        Args:
            result: MistralResearchResult to evaluate
            
        Returns:
            ResearchStatus
        """
        # If there are errors, check if they're fatal
        if result.errors:
            for error in result.errors:
                if "api" in error.lower() or "timeout" in error.lower() or "failed" in error.lower():
                    return ResearchStatus.FAILED
        
        # If no sources were examined, it's a failure
        if result.sources_examined == 0:
            return ResearchStatus.FAILED
        
        # If no sources were accepted, check if we have false entities
        if result.sources_accepted == 0:
            false_count = sum(1 for sr in result.rejected_sources if sr.get("reason") == "FALSE_ENTITY")
            ambiguous_count = sum(1 for sr in result.rejected_sources if sr.get("reason") == "AMBIGUOUS")
            
            if false_count == result.sources_examined:
                return ResearchStatus.FALSE_ENTITY
            elif ambiguous_count == result.sources_examined:
                return ResearchStatus.AMBIGUOUS
            else:
                return ResearchStatus.INSUFFICIENT
        
        # If we have accepted sources with evidence, check evidence quality
        if result.accepted_evidence_count > 0:
            return ResearchStatus.SUFFICIENT
        
        # If we have accepted sources but no evidence, it's insufficient
        if result.sources_accepted > 0 and result.accepted_evidence_count == 0:
            return ResearchStatus.INSUFFICIENT
        
        return ResearchStatus.INSUFFICIENT

    def validate_result(self, result: MistralResearchResult) -> tuple[bool, List[str]]:
        """Perform deterministic validation on the research result.
        
        This validates that:
        1. Every evidence item has a source URL
        2. Every evidence item has a non-empty passage
        3. Every evidence item has a claim
        4. Only acceptable entity matches produce evidence
        5. No unsupported claims are accepted
        
        Args:
            result: MistralResearchResult to validate
            
        Returns:
            Tuple of (is_valid, list_of_validation_errors)
        """
        errors = []
        
        # Validate each source result
        for source_result in result.source_results:
            # Check source URL
            if not source_result.assessment.url:
                errors.append(f"Source missing URL: {source_result.assessment.title or 'Untitled'}")
            
            # Check that only accepted sources have evidence
            if not source_result.is_accepted and source_result.evidence:
                errors.append(
                    f"Non-accepted source has evidence: {source_result.assessment.url} "
                    f"(match_type={source_result.assessment.match_type.value})"
                )
            
            # Validate each evidence item
            for evidence in source_result.evidence:
                validation_errors = self._validate_evidence_item(evidence, source_result)
                errors.extend(validation_errors)
        
        # Check for unsupported claims
        unsupported_claims = self._find_unsupported_claims(result)
        errors.extend(unsupported_claims)
        
        is_valid = len(errors) == 0
        return is_valid, errors
    
    def _validate_evidence_item(
        self,
        evidence: EvidenceItem,
        source_result: SourceResult,
    ) -> List[str]:
        """Validate a single evidence item.
        
        Args:
            evidence: EvidenceItem to validate
            source_result: Parent SourceResult for context
            
        Returns:
            List of validation error strings
        """
        errors = []
        
        # Check source URL
        if not evidence.source_url:
            errors.append(f"Evidence {evidence.evidence_id} missing source_url")
        
        # Check passage
        if not evidence.passage or not evidence.passage.strip():
            errors.append(f"Evidence {evidence.evidence_id} has empty passage")
        
        # Check claim
        if not evidence.claim or not evidence.claim.strip():
            errors.append(f"Evidence {evidence.evidence_id} has empty claim")
        
        # Check that evidence level is acceptable
        if evidence.evidence_level == EvidenceLevel.INFERRED:
            errors.append(
                f"Evidence {evidence.evidence_id} has INFERRED level which cannot be promoted to fact "
                f"(claim: {evidence.claim[:50]})"
            )
        
        # Check that source was accepted
        if not source_result.is_accepted:
            errors.append(
                f"Evidence {evidence.evidence_id} from non-accepted source "
                f"(match_type={source_result.assessment.match_type.value})"
            )
        
        # Check entity match type
        if source_result.assessment.match_type not in [
            EntityMatchType.DIRECT,
            EntityMatchType.ALIAS,
            EntityMatchType.CONTEXTUAL,
        ]:
            errors.append(
                f"Evidence {evidence.evidence_id} from source with match_type={source_result.assessment.match_type.value} "
                f"which cannot produce accepted evidence"
            )
        
        return errors
    
    def _find_unsupported_claims(self, result: MistralResearchResult) -> List[str]:
        """Find claims without supporting evidence.
        
        Args:
            result: MistralResearchResult to check
            
        Returns:
            List of error strings for unsupported claims
        """
        errors = []
        
        # Build a set of all evidence IDs
        evidence_ids = {ev.evidence_id for ev in result.evidence_items}
        
        # Check each source result for claims
        for source_result in result.source_results:
            if not source_result.is_accepted:
                continue
            
            for evidence in source_result.evidence:
                # If evidence has a claim but no evidence_id, that's suspicious
                if evidence.claim and not evidence.evidence_id:
                    errors.append(f"Claim without evidence_id: {evidence.claim[:50]}")
        
        return errors

    def deduplicate_evidence(self, result: MistralResearchResult) -> MistralResearchResult:
        """Remove duplicate evidence items from the result.
        
        Args:
            result: MistralResearchResult to deduplicate
            
        Returns:
            MistralResearchResult with duplicates removed
        """
        seen_passages = set()
        seen_claims = set()
        
        for source_result in result.source_results:
            unique_evidence = []
            for evidence in source_result.evidence:
                # Create a fingerprint for duplicate detection
                passage_key = hash(evidence.passage.strip().lower())
                claim_key = hash(evidence.claim.strip().lower())
                
                # Check if we've seen this passage or claim
                if passage_key in seen_passages or claim_key in seen_claims:
                    logger.info(f"[MISTRAL_WEB_RESEARCH] Duplicate evidence removed: {evidence.evidence_id}")
                    continue
                
                seen_passages.add(passage_key)
                seen_claims.add(claim_key)
                unique_evidence.append(evidence)
            
            source_result.evidence = unique_evidence
        
        # Recalculate counts
        result.evidence_items = []
        result.sources_accepted = 0
        for source_result in result.source_results:
            if source_result.is_accepted:
                result.sources_accepted += 1
            result.evidence_items.extend(source_result.evidence)
        
        return result

    def validate_and_clean_result(self, result: MistralResearchResult) -> tuple[MistralResearchResult, List[str]]:
        """Perform validation and cleanup on a research result.
        
        This:
        1. Validates the result
        2. Removes duplicate evidence
        3. Filters out invalid evidence items
        4. Returns cleaned result with validation errors
        
        Args:
            result: MistralResearchResult to validate and clean
            
        Returns:
            Tuple of (cleaned_result, validation_errors)
        """
        # First validate
        is_valid, validation_errors = self.validate_result(result)
        
        # Remove invalid evidence
        cleaned_result = self._remove_invalid_evidence(result)
        
        # Deduplicate
        cleaned_result = self.deduplicate_evidence(cleaned_result)
        
        # Recalculate status
        cleaned_result.research_status = self._determine_research_status(cleaned_result)
        
        return cleaned_result, validation_errors
    
    def _remove_invalid_evidence(self, result: MistralResearchResult) -> MistralResearchResult:
        """Remove evidence items that fail validation.
        
        Args:
            result: MistralResearchResult to clean
            
        Returns:
            MistralResearchResult with invalid evidence removed
        """
        for source_result in result.source_results:
            valid_evidence = []
            for evidence in source_result.evidence:
                # Check basic validity
                if not evidence.source_url:
                    logger.warning(f"[MISTRAL_WEB_RESEARCH] Removing evidence with no source_url: {evidence.evidence_id}")
                    continue
                if not evidence.passage or not evidence.passage.strip():
                    logger.warning(f"[MISTRAL_WEB_RESEARCH] Removing evidence with empty passage: {evidence.evidence_id}")
                    continue
                if not evidence.claim or not evidence.claim.strip():
                    logger.warning(f"[MISTRAL_WEB_RESEARCH] Removing evidence with empty claim: {evidence.evidence_id}")
                    continue
                if evidence.evidence_level == EvidenceLevel.INFERRED:
                    logger.warning(f"[MISTRAL_WEB_RESEARCH] Removing INFERRED evidence: {evidence.evidence_id}")
                    continue
                if not source_result.is_accepted:
                    logger.warning(f"[MISTRAL_WEB_RESEARCH] Removing evidence from non-accepted source: {evidence.evidence_id}")
                    continue
                
                valid_evidence.append(evidence)
            
            source_result.evidence = valid_evidence
        
        # Recollect evidence items
        result.evidence_items = []
        for source_result in result.source_results:
            result.evidence_items.extend(source_result.evidence)
        
        return result


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    "EntityMatchType",
    "EvidenceType",
    "EvidenceLevel",
    "ResearchStatus",
    "RejectionReason",
    "SourceAssessment",
    "EvidenceItem",
    "SourceResult",
    "MistralResearchResult",
    "ResearchContext",
    "MistralWebResearchProvider",
]
