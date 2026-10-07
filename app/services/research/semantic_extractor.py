"""Semantic extraction pipeline for atomic evidence from research documents.

This module provides structured semantic extraction with:
- Document-level provenance (ResearchDocument wrapping EvidenceRecord)
- Atomic evidence with exact passage quotes
- Entity match verification before extraction
- Categorization: FACT, ATTRIBUTE, RELATIONSHIP, ASSOCIATION
- Conservative relationship extraction (explicit only)
- Full backward compatibility with ResearchClaim
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.services.research.evidence import EvidenceRecord, EvidenceStatus, ExtractionQuality
from app.services.ontology import get_ontology, RELATIONSHIP_PREDICATES, ASSOCIATION_PREDICATES


# =============================================================================
# Evidence Types
# =============================================================================

class EvidenceType(str, Enum):
    """Classification of extracted evidence by semantic type."""
    FACT = "FACT"                   # Verifiable factual statement
    ATTRIBUTE = "ATTRIBUTE"         # Entity property/characteristic (type, country, sector, status)
    RELATIONSHIP = "RELATIONSHIP"   # Explicit relationship (regulates, manages, oversees, etc.)
    ASSOCIATION = "ASSOCIATION"     # Looser association (connected_to, associated_with, etc.)
    SUMMARY = "SUMMARY"             # Descriptive summary of what entity does


# =============================================================================
# Models
# =============================================================================

@dataclass
class AtomicEvidence:
    """Atomic evidence extracted from a document with exact passage and provenance.
    
    This is the fundamental unit of extracted knowledge. Each AtomicEvidence
    represents a single semantic fact, attribute, relationship, or association
    with its exact source passage and full provenance.
    
    Attributes:
        subject: The entity being described (should match the research entity)
        predicate: The relationship or attribute predicate
        object: The target of the relationship or value of the attribute
        passage: The EXACT quote from the source document supporting this evidence
        evidence_type: Classification (FACT, ATTRIBUTE, RELATIONSHIP, ASSOCIATION, SUMMARY)
        source_url: URL of the source document
        source_title: Title of the source document
        document_id: Reference to the ResearchDocument
        chunk_index: Index of the chunk within the document
        confidence: Metadata confidence (not truth value)
        extraction_method: Method used for extraction
        extracted_at: Timestamp of extraction
        metadata: Additional provenance metadata
    """
    
    subject: str
    predicate: str
    object: str
    passage: str
    evidence_type: EvidenceType
    source_url: str
    source_title: Optional[str] = None
    document_id: Optional[str] = None
    chunk_index: int = 0
    confidence: float = 0.0
    extraction_method: str = "semantic_extraction"
    extracted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Validate and normalize fields."""
        self.subject = str(self.subject or "").strip()
        self.predicate = str(self.predicate or "").strip().lower()
        self.object = str(self.object or "").strip()
        self.passage = str(self.passage or "").strip()
        
        # Ensure confidence is between 0 and 1
        self.confidence = max(0.0, min(1.0, self.confidence))
    
    def to_research_claim(self) -> "ResearchClaim":
        """Convert to ResearchClaim for backward compatibility.
        
        Returns:
            ResearchClaim with equivalent information
        """
        from app.services.research_engine import ResearchClaim
        
        return ResearchClaim(
            claim=f"{self.subject} {self.predicate} {self.object}",
            claim_text=f"{self.subject} {self.predicate} {self.object}",
            field_name=self._evidence_type_to_field_name(),
            source_url=self.source_url,
            source_title=self.source_title,
            evidence_passage=self.passage,
            source_type="webpage",
            confidence=self.confidence,
            extraction_method=self.extraction_method,
            extracted_at=self.extracted_at,
            subject=self.subject,
            predicate=self.predicate,
            object=self.object,
            evidence_urls=[self.source_url] if self.source_url else [],
        )
    
    def _evidence_type_to_field_name(self) -> str:
        """Map evidence type to field name."""
        mapping = {
            EvidenceType.FACT: "fact",
            EvidenceType.ATTRIBUTE: "attribute",
            EvidenceType.RELATIONSHIP: "relationship",
            EvidenceType.ASSOCIATION: "association",
            EvidenceType.SUMMARY: "summary",
        }
        return mapping.get(self.evidence_type, "candidate_claim")
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "subject": self.subject,
            "predicate": self.predicate,
            "object": self.object,
            "passage": self.passage,
            "evidence_type": self.evidence_type.value,
            "source_url": self.source_url,
            "source_title": self.source_title,
            "document_id": self.document_id,
            "chunk_index": self.chunk_index,
            "confidence": self.confidence,
            "extraction_method": self.extraction_method,
            "extracted_at": self.extracted_at.isoformat(),
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AtomicEvidence":
        """Deserialize from dictionary."""
        return cls(
            subject=data.get("subject", ""),
            predicate=data.get("predicate", ""),
            object=data.get("object", ""),
            passage=data.get("passage", ""),
            evidence_type=EvidenceType(data.get("evidence_type", "FACT")),
            source_url=data.get("source_url", ""),
            source_title=data.get("source_title"),
            document_id=data.get("document_id"),
            chunk_index=data.get("chunk_index", 0),
            confidence=data.get("confidence", 0.0),
            extraction_method=data.get("extraction_method", "semantic_extraction"),
            extracted_at=datetime.fromisoformat(data.get("extracted_at")) if data.get("extracted_at") else datetime.now(timezone.utc),
            metadata=data.get("metadata", {}),
        )


@dataclass
class ResearchDocument:
    """Document-level wrapper for EvidenceRecord with semantic extraction support.
    
    This class wraps an EvidenceRecord and provides:
    - Document boundary for extraction
    - Chunking with provenance
    - Entity match verification
    - Authoritative semantic text access
    
    Attributes:
        evidence_record: The underlying EvidenceRecord
        document_id: Unique identifier for this document
        chunks: List of text chunks with their indices
    """
    
    evidence_record: EvidenceRecord
    document_id: str = field(default_factory=lambda: f"doc_{datetime.now(timezone.utc).timestamp()}")
    chunks: List[Tuple[int, str]] = field(default_factory=list)  # (chunk_index, text)
    
    def __post_init__(self):
        """Initialize chunks from evidence content."""
        if not self.chunks:
            self.chunks = self._create_chunks()
    
    @property
    def url(self) -> str:
        """Get the document URL."""
        return self.evidence_record.url
    
    @property
    def title(self) -> str:
        """Get the document title."""
        return self.evidence_record.title or ""
    
    @property
    def normalized_text(self) -> str:
        """Get the authoritative semantic text (never HTML)."""
        return getattr(self.evidence_record, 'normalized_text', None) or \
               getattr(self.evidence_record, 'content', None) or \
               self.evidence_record.snippet or ""
    
    @property
    def full_content(self) -> str:
        """Get full content (may be HTML if normalized_text not available)."""
        return getattr(self.evidence_record, 'content', None) or \
               self.evidence_record.snippet or ""
    
    @property
    def source_type(self) -> str:
        """Get the source type classification."""
        return getattr(self.evidence_record, 'source_type', 'other')
    
    def _create_chunks(
        self,
        max_chunk_size: int = 4000,
        overlap: int = 200,
    ) -> List[Tuple[int, str]]:
        """Create overlapping chunks from document content.
        
        Args:
            max_chunk_size: Maximum size of each chunk
            overlap: Number of overlapping characters between chunks
            
        Returns:
            List of (chunk_index, text) tuples
        """
        content = self.normalized_text
        if not content.strip():
            return []
        
        chunks = []
        start = 0
        chunk_index = 0
        
        while start < len(content):
            end = min(start + max_chunk_size, len(content))
            chunk = content[start:end]
            chunks.append((chunk_index, chunk))
            
            if end >= len(content):
                break
            start = end - overlap
            chunk_index += 1
        
        return chunks
    
    def get_chunk(self, chunk_index: int) -> Optional[str]:
        """Get a specific chunk by index."""
        for idx, text in self.chunks:
            if idx == chunk_index:
                return text
        return None
    
    @classmethod
    def from_evidence_record(
        cls,
        evidence_record: EvidenceRecord,
        document_id: Optional[str] = None,
    ) -> "ResearchDocument":
        """Create a ResearchDocument from an EvidenceRecord.
        
        Args:
            evidence_record: The EvidenceRecord to wrap
            document_id: Optional document ID override
            
        Returns:
            ResearchDocument instance
        """
        return cls(
            evidence_record=evidence_record,
            document_id=document_id or f"doc_{hash(evidence_record.url)}_{datetime.now(timezone.utc).timestamp()}",
        )


@dataclass
class ExtractionResult:
    """Result from semantic extraction on a single document.
    
    Attributes:
        document: The ResearchDocument that was extracted
        atomic_evidence: List of extracted AtomicEvidence items
        entity_match_verified: Whether entity match was verified
        extraction_errors: List of any errors encountered during extraction
    """
    
    document: ResearchDocument
    atomic_evidence: List[AtomicEvidence] = field(default_factory=list)
    entity_match_verified: bool = False
    extraction_errors: List[str] = field(default_factory=list)
    
    @property
    def evidence_count(self) -> int:
        """Get the number of atomic evidence items."""
        return len(self.atomic_evidence)
    
    @property
    def document_id(self) -> str:
        """Get the document ID."""
        return self.document.document_id
    
    def to_research_claims(self) -> List["ResearchClaim"]:
        """Convert all atomic evidence to ResearchClaim objects."""
        from app.services.research_engine import ResearchClaim
        
        return [ae.to_research_claim() for ae in self.atomic_evidence]


# =============================================================================
# Mistral Semantic Extractor
# =============================================================================

class MistralSemanticExtractor:
    """Main semantic extractor using Mistral LLM.
    
    Features:
    - Entity match verification FIRST before any extraction
    - Document chunking with provenance
    - Structured extraction (facts, attributes, relationships, associations)
    - Atomic evidence with exact passages
    - Conservative relationship extraction (explicit only, not inferred)
    
    Usage:
        extractor = MistralSemanticExtractor(api_key="...", model="...")
        
        # Extract from evidence records
        results = await extractor.extract(
            entity_name="ZERA",
            evidence_records=[...],
        )
        
        # Get all atomic evidence
        all_evidence = []
        for result in results:
            all_evidence.extend(result.atomic_evidence)
        
        # Convert to ResearchClaims for backward compatibility
        claims = []
        for result in results:
            claims.extend(result.to_research_claims())
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        max_chunk_size: int = 4000,
        chunk_overlap: int = 200,
        max_retries: int = 2,
        timeout: float = 30.0,
    ):
        """Initialize the extractor.
        
        Args:
            api_key: Mistral API key (defaults to config.MISTRAL_API_KEY)
            model: Model to use (defaults to config.MISTRAL_MODEL)
            max_chunk_size: Maximum chunk size for document splitting
            chunk_overlap: Overlap between chunks
            max_retries: Maximum retries for LLM calls
            timeout: Timeout for LLM calls
        """
        from app import config
        
        self.api_key = api_key or (config.MISTRAL_API_KEY or "").strip()
        self.model = model or config.MISTRAL_MODEL or "mistral-large-latest"
        self.max_chunk_size = max_chunk_size
        self.chunk_overlap = chunk_overlap
        self.max_retries = max_retries
        self.timeout = timeout
        self.ontology = get_ontology()
    
    def _verify_entity_match(
        self,
        entity_name: str,
        document: ResearchDocument,
    ) -> bool:
        """Verify entity match for semantic extraction.
        
        This method is now a NO-OP that always returns True.
        Entity matching is handled by the RelevanceFilter BEFORE extraction.
        
        Once a page has passed the LLM semantic relevance stage (RelevanceFilter),
        the semantic extractor should NOT reject the document merely because the
        literal entity name is absent from the body. Instead, the extraction prompt
        performs the semantic identity assessment using target entity, aliases,
        entity context, URL, domain, title, and document content.
        
        Args:
            entity_name: The entity being researched
            document: The ResearchDocument to check
            
        Returns:
            True (always) - entity matching is done by RelevanceFilter
        """
        # Always return True - entity matching is handled by RelevanceFilter
        return True
    
    def _create_document_chunks(
        self,
        document: ResearchDocument,
    ) -> List[Dict[str, Any]]:
        """Create chunk context for Mistral prompt.
        
        Args:
            document: The ResearchDocument to chunk
            
        Returns:
            List of chunk dicts with provenance
        """
        chunks = []
        
        for chunk_index, text in document.chunks:
            chunks.append({
                "chunk_index": chunk_index,
                "text": text,
                "url": document.url,
                "title": document.title,
                "total_chunks": len(document.chunks),
            })
        
        return chunks
    
    def _build_ontology_context(self) -> str:
        """Build ontology context for the Mistral prompt.
        
        Returns:
            Ontology context string
        """
        return f"""Canonical ATIS Ontology:
- Entity Types: {', '.join(sorted(self.ontology.all_entity_types))}
- Valid Subtypes: {', '.join(sorted(self.ontology.organization_subtypes | self.ontology.concept_subtypes))}
- Relationship Predicates: {', '.join(sorted(self.ontology.relationship_predicates))}
- Association Predicates: {', '.join(sorted(self.ontology.association_predicates))}
- Countries: {', '.join(sorted(self.ontology.countries))}
- Sectors: {', '.join(sorted(self.ontology.sectors))}
- Statuses: {', '.join(sorted(self.ontology.statuses))}

Ontology Rules:
- Select ONLY from the canonical ontology values above.
- If evidence does NOT explicitly support a classification, return NO claim rather than inventing.
- Use the EXACT ontology values (case-sensitive).
- Be CONSERVATIVE: only extract what is EXPLICITLY stated in the evidence.
- Do NOT infer relationships that are not explicitly stated.
"""
    
    def _build_extraction_prompt(
        self,
        entity_name: str,
        document: ResearchDocument,
        chunks: List[Dict[str, Any]],
    ) -> str:
        """Build the extraction prompt for Mistral with formal research contract.
        
        Args:
            entity_name: The entity being researched
            document: The ResearchDocument being extracted
            chunks: The document chunks
            
        Returns:
            Prompt string
        """
        ontology_context = self._build_ontology_context()
        
        # Build the required JSON format example
        json_example = {
            "entity_assessment": {
                "entity_match": True,
                "match_type": "DIRECT",
                "match_confidence": 0.98
            },
            "atomic_evidence": [
                {
                    "subject": "<entity_name>",
                    "predicate": "<predicate_from_ontology>",
                    "object": "<target_or_value>",
                    "evidence_type": "<FACT|ATTRIBUTE|RELATIONSHIP|ASSOCIATION|SUMMARY>",
                    "evidence_level": "DIRECT",
                    "passage": "<exact_quote_from_evidence>",
                    "chunk_index": 0
                }
            ],
            "uncertainties": [],
            "conflicts": [],
            "errors": []
        }
        
        prompt = (
            "You are NORA's semantic research extraction engine.\n"
            "\n"
            "## ROLE\n"
            "Your job is to transform supplied source documents into structured, evidence-backed knowledge about ONE requested entity.\n"
            "You are NOT a web search engine.\n"
            "You are NOT allowed to browse for additional information.\n"
            "You are NOT allowed to use your pretrained knowledge to fill gaps.\n"
            "You must use ONLY the supplied document content.\n"
            "\n"
            "## TARGET ENTITY\n"
            "The request contains canonical name, aliases, entity type, country/region, and known metadata.\n"
            "These fields are identity hints, not facts to be blindly asserted.\n"
            "The document may refer to the entity using: canonical name, alias, abbreviation, shortened name, institutional name, domain-associated name, or grammatical variation.\n"
            "Do NOT require the exact canonical name string to appear.\n"
            "Example: Target: Theotechnic College. Document: Theo Technical College. This may still be the same entity.\n"
            "Determine identity from the supplied evidence.\n"
            "\n"
            "## ENTITY MATCHING\n"
            "Before extracting evidence, determine whether the document is actually about the target entity.\n"
            "Return entity_match with:\n"
            "- DIRECT: document explicitly identifies the requested entity\n"
            "- ALIAS: document uses an identifiable alternate name, abbreviation, or institutional variation\n"
            "- CONTEXTUAL: document strongly establishes the entity through multiple identifying details\n"
            "- AMBIGUOUS: document could refer to the entity, but identity is not sufficiently established\n"
            "- FALSE: document concerns another entity\n"
            "Only DIRECT, ALIAS, and sufficiently strong CONTEXTUAL matches may produce evidence.\n"
            "Do not extract facts about an unrelated entity merely because the page contains similar words.\n"
            "\n"
            "## EVIDENCE PRINCIPLE\n"
            "An evidence item is a discrete statement that can be supported directly by the supplied document.\n"
            "Every evidence item MUST contain: subject, predicate, object, evidence_type, passage, source_url, chunk_index.\n"
            "The passage MUST be an exact verbatim substring of the supplied document.\n"
            "Never paraphrase the passage. Never synthesize a passage. Never write a passage that does not exist in the document.\n"
            "\n"
            "## EVIDENCE TYPES\n"
            "- FACT: A discrete factual statement. Example: The institution was established in 1998.\n"
            "- ATTRIBUTE: A property of the entity. Examples: country, location, headquarters, entity_type, sector, status, founded_date, website, registration, ownership.\n"
            "- RELATIONSHIP: An explicit directional relationship. Examples: operates, owns, manages, regulates, governs, oversees, administers, parent_of, subsidiary_of, located_in, part_of, offers, serves.\n"
            "  Only use predicates permitted by the ATIS ontology.\n"
            "- ASSOCIATION: A meaningful connection. Examples: member_of, partner_of, affiliated_with, associated_with, accredited_by, works_with.\n"
            "- SUMMARY: A concise description of what the entity does, but still supported by an exact source passage.\n"
            "\n"
            "## EXPLICITNESS RULES\n"
            "Use three evidence levels: DIRECT, STRONG_CONTEXTUAL, INFERRED.\n"
            "Only DIRECT and STRONG_CONTEXTUAL evidence may become extracted evidence.\n"
            "INFERRED information MUST NOT be promoted into a fact.\n"
            "Example: If a page says 'The college offers engineering and construction programmes.', you may extract: offers -> engineering programmes, offers -> construction programmes.\n"
            "You may NOT infer: is accredited by X, owns Y, is regulated by Z, unless the document explicitly supports those relationships.\n"
            "\n"
            "## RELATIONSHIPS\n"
            "Relationships must be conservative. A relationship requires explicit textual support.\n"
            "Do NOT infer: located_in, owned_by, regulated_by, partner_of, accredited_by, member_of merely because the entities appear near each other.\n"
            "If the document says 'The college operates under the Ministry of ...', then the relationship may be extracted.\n"
            "If the page merely mentions the Ministry elsewhere, do not create a relationship.\n"
            "\n"
            "## ATTRIBUTES\n"
            "Extract supported attributes: entity_type, subtype, country, region, city, headquarters, status, founded_date, established_date, website, sector, industry, ownership, registration, mission, activities, services, programmes.\n"
            "Only return an attribute when the document supports it.\n"
            "\n"
            "## IDENTITY AND ALIASES\n"
            "If the document identifies an alternate name, extract it as: subject = target entity, predicate = alias, object = alternate name.\n"
            "Do not replace the canonical RITA name. The RITA canonical name remains the identity used by NORA.\n"
            "\n"
            "## CONFLICTING INFORMATION\n"
            "If two passages in the same document conflict, return them in conflicts array.\n"
            "NORA will resolve conflicts at the evidence aggregation stage.\n"
            "\n"
            "## UNCERTAINTY\n"
            "Never convert uncertainty into fact. Return unsupported or uncertain information separately in uncertainties array.\n"
            "\n"
            "## CHUNKING\n"
            "Long documents may be split into deterministic chunks. Each chunk preserves: document_id, source_url, chunk_index, total_chunks, text.\n"
            "An extracted passage must be validated against the complete document whenever possible.\n"
            "\n"
            "## QUALITY ARCHITECTURE\n"
            "Do NOT use number of URLs, number of search results, or number of crawled pages as the final semantic quality measure.\n"
            "Track: URLs discovered, URLs crawled, successful crawls, documents with usable text, documents matching entity, atomic evidence extracted, valid atomic evidence, invalid/rejected evidence, distinct source URLs, direct evidence count, relationship evidence count, attribute evidence count, conflicts, uncertainties.\n"
            "The semantic quality decision must be based on the resulting evidence.\n"
            "\n"
            f"{ontology_context}\n\n"
            "## CONTEXT\n"
            f"Entity: {entity_name or 'unknown'}\n"
            f"Document: {document.title or 'Untitled'} ({document.url})\n\n"
            f"Chunks: {json.dumps(chunks, ensure_ascii=False)}\n\n"
            "## OUTPUT SCHEMA\n"
            "Return JSON only with this exact schema:\n"
            f"{json.dumps(json_example, indent=2)}\n\n"
            "IMPORTANT: Do not return prose outside the JSON object.\n"
        )
        
        return prompt
    
    async def _call_mistral(
        self,
        prompt: str,
        client: Any = None,
    ) -> Optional[Dict[str, Any]]:
        """Call Mistral API with the extraction prompt.
        
        Args:
            prompt: The extraction prompt
            client: Optional httpx.AsyncClient for reuse
            
        Returns:
            Parsed JSON response or None on failure
        """
        import httpx
        
        if not self.api_key:
            return None
        
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0,
            "top_p": 1.0,
            "response_format": {"type": "json_object"},
        }
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        from app.services.research.mistral_response import extract_mistral_message_content
        
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
                
                # Use canonical normalization
                raw_content = extract_mistral_message_content(json_response, context="SEMANTIC_EXTRACTOR")
                
                if raw_content is None:
                    logger.warning(f"[SEMANTIC_EXTRACTOR] LLM_NORMALIZATION_RESULT=None")
                    if attempt < self.max_retries:
                        continue
                    return None
                
                logger.info(f"[SEMANTIC_EXTRACTOR] LLM_RESPONSE_TYPE=str LLM_NORMALIZED_TEXT_LENGTH={len(raw_content)}")
                
                try:
                    parsed = json.loads(raw_content)
                    logger.info(f"[SEMANTIC_EXTRACTOR] JSON_PARSE_RESULT=success")
                    return parsed
                except (TypeError, ValueError) as e:
                    logger.warning(f"[SEMANTIC_EXTRACTOR] JSON_PARSE_RESULT=failure error={e}")
                    if attempt < self.max_retries:
                        continue
                    return None
                    
            except Exception as e:
                logger.warning(f"[SEMANTIC_EXTRACTOR] LLM call attempt {attempt + 1} failed: {e}")
                if attempt < self.max_retries:
                    continue
                return None
        
        return None
    
    def _parse_extraction_result(
        self,
        entity_name: str,
        document: ResearchDocument,
        parsed: Dict[str, Any],
    ) -> ExtractionResult:
        """Parse Mistral response into ExtractionResult.
        
        Args:
            entity_name: The entity being researched
            document: The ResearchDocument
            parsed: The parsed JSON response from Mistral
            
        Returns:
            ExtractionResult with atomic evidence
        """
        import logging
        logger = logging.getLogger(__name__)
        
        atomic_evidence = []
        errors = []
        entity_match_verified = False
        
        # Log semantic extraction start
        logger.info(f"[SEMANTIC_EXTRACTION] document_id={document.document_id}, url={document.url}, entity={entity_name}")
        
        # Check entity match from Mistral response
        entity_assessment = parsed.get("entity_assessment", {})
        if isinstance(entity_assessment, dict):
            entity_match_verified = bool(entity_assessment.get("entity_match", False))
            match_type = entity_assessment.get("match_type", "UNKNOWN")
            match_confidence = entity_assessment.get("match_confidence", 0.0)
            logger.info(f"[SEMANTIC_EXTRACTION] entity_match={entity_match_verified}, match_type={match_type}, confidence={match_confidence}")
        else:
            # Fallback: check old format or verify ourselves
            if isinstance(parsed.get("entity_match_verified"), bool):
                entity_match_verified = parsed["entity_match_verified"]
            else:
                entity_match_verified = self._verify_entity_match(entity_name, document)
            logger.info(f"[SEMANTIC_EXTRACTION] entity_match={entity_match_verified} (fallback)")
        
        # Get errors
        if isinstance(parsed.get("errors"), list):
            errors = [str(e) for e in parsed["errors"]]
        
        # Log document details
        logger.info(f"[SEMANTIC_EXTRACTION] normalized_chars={len(document.normalized_text)}, chunks={len(document.chunks)}")
        
        # Parse atomic evidence
        evidence_list = parsed.get("atomic_evidence") or []
        if not isinstance(evidence_list, list):
            logger.warning(f"[SEMANTIC_EXTRACTION] No atomic_evidence list in response")
            return ExtractionResult(
                document=document,
                atomic_evidence=[],
                entity_match_verified=entity_match_verified,
                extraction_errors=errors + ["No atomic_evidence list in response"],
            )
        
        logger.info(f"[SEMANTIC_EXTRACTION] atomic_evidence_items={len(evidence_list)}")
        
        for item in evidence_list:
            if not isinstance(item, dict):
                continue
            
            # Extract fields
            subject = str(item.get("subject") or "").strip()
            predicate = str(item.get("predicate") or "").strip().lower()
            obj = str(item.get("object") or "").strip()
            passage = str(item.get("passage") or "").strip()
            evidence_type_str = str(item.get("evidence_type") or "FACT").upper()
            chunk_index = int(item.get("chunk_index") or 0)
            
            # Validate evidence type
            try:
                evidence_type = EvidenceType(evidence_type_str)
            except ValueError:
                evidence_type = EvidenceType.FACT
            
            # Skip if no passage (required)
            if not passage:
                continue
            
            # Skip if subject doesn't match entity (conservative)
            # Allow partial matches for acronyms, etc.
            if entity_name and entity_name.strip():
                normalized_entity = entity_name.strip().lower()
                if normalized_entity not in subject.lower():
                    # Check if the passage contains the entity
                    if normalized_entity not in passage.lower():
                        continue
            
            # Validate predicate against ontology
            ontology = get_ontology()
            is_relationship = ontology.is_relationship_predicate(predicate)
            is_association = ontology.is_association_predicate(predicate)
            
            # If predicate is a relationship or association, ensure evidence type matches
            if is_relationship and evidence_type != EvidenceType.RELATIONSHIP:
                # Override to RELATIONSHIP if predicate is canonical
                evidence_type = EvidenceType.RELATIONSHIP
            elif is_association and evidence_type != EvidenceType.ASSOCIATION:
                evidence_type = EvidenceType.ASSOCIATION
            
            # Create atomic evidence
            atomic_evidence.append(AtomicEvidence(
                subject=subject,
                predicate=predicate,
                object=obj,
                passage=passage,
                evidence_type=evidence_type,
                source_url=document.url,
                source_title=document.title,
                document_id=document.document_id,
                chunk_index=chunk_index,
                confidence=0.8,
                extraction_method="mistral_semantic",
                metadata={
                    "source_type": document.source_type,
                    "entity_match_verified": entity_match_verified,
                },
            ))
        
        # Log final result
        logger.info(f"[SEMANTIC_EXTRACTION] accepted_evidence={len(atomic_evidence)}, rejected={len(evidence_list) - len(atomic_evidence)}")
        
        return ExtractionResult(
            document=document,
            atomic_evidence=atomic_evidence,
            entity_match_verified=entity_match_verified,
            extraction_errors=errors,
        )
    
    async def extract(
        self,
        entity_name: str,
        evidence_records: Sequence[EvidenceRecord],
        client: Any = None,
    ) -> List[ExtractionResult]:
        """Extract atomic evidence from evidence records.
        
        This is the main entry point. It:
        1. Wraps each EvidenceRecord in a ResearchDocument
        2. Verifies entity match for each document
        3. Extracts atomic evidence using Mistral
        4. Returns ExtractionResult for each document
        
        Args:
            entity_name: The entity being researched
            evidence_records: List of EvidenceRecord to extract from
            client: Optional httpx.AsyncClient for reuse
            
        Returns:
            List of ExtractionResult, one per document
        """
        results = []
        
        logger.info(f"[SEMANTIC_EXTRACTION {entity_name}] Starting extraction with {len(evidence_records)} evidence records")
        
        extraction_stats = {
            'input_records': len(evidence_records),
            'documents_processed': 0,
            'documents_skipped': 0,
            'documents_with_errors': 0,
            'llm_calls': 0,
            'llm_success': 0,
            'llm_failure': 0,
            'total_atomic_evidence': 0,
            'total_rejected': 0,
        }
        
        for record in evidence_records:
            if not record or not record.url:
                extraction_stats['documents_skipped'] += 1
                continue
            
            # Skip unusable evidence
            if hasattr(record, 'evidence_status') and record.evidence_status == EvidenceStatus.UNUSABLE:
                extraction_stats['documents_skipped'] += 1
                continue
            
            extraction_stats['documents_processed'] += 1
            
            # Create ResearchDocument
            document = ResearchDocument.from_evidence_record(record)
            
            # Create chunks
            chunks = self._create_document_chunks(document)
            if not chunks:
                logger.info(f"[SEMANTIC_EXTRACTION {entity_name}] No chunks for {document.url[:60]}")
                results.append(ExtractionResult(
                    document=document,
                    atomic_evidence=[],
                    entity_match_verified=True,
                    extraction_errors=["No chunks created from document"],
                ))
                extraction_stats['documents_with_errors'] += 1
                continue
            
            # Build prompt
            prompt = self._build_extraction_prompt(entity_name, document, chunks)
            
            # Call Mistral
            extraction_stats['llm_calls'] += 1
            parsed = await self._call_mistral(prompt, client)
            
            if parsed is None:
                logger.info(f"[SEMANTIC_EXTRACTION {entity_name}] LLM call failed for {document.url[:60]}")
                extraction_stats['llm_failure'] += 1
                # Fallback: create basic atomic evidence from document
                result = self._create_fallback_extraction(entity_name, document)
                results.append(result)
                continue
            
            extraction_stats['llm_success'] += 1
            
            # Parse result
            result = self._parse_extraction_result(entity_name, document, parsed)
            extraction_stats['total_atomic_evidence'] += len(result.atomic_evidence)
            extraction_stats['total_rejected'] += len(parsed.get("atomic_evidence", [])) - len(result.atomic_evidence)
            results.append(result)
        
        # Log extraction statistics
        logger.info(f"[SEMANTIC_EXTRACTION {entity_name}] Extraction stats: {extraction_stats}")
        
        return results
    
    def _create_fallback_extraction(
        self,
        entity_name: str,
        document: ResearchDocument,
    ) -> ExtractionResult:
        """Create fallback extraction when Mistral fails.
        
        This creates a single SUMMARY atomic evidence from the full document.
        
        Args:
            entity_name: The entity being researched
            document: The ResearchDocument
            
        Returns:
            ExtractionResult with fallback evidence
        """
        content = document.normalized_text
        if not content:
            return ExtractionResult(
                document=document,
                atomic_evidence=[],
                entity_match_verified=self._verify_entity_match(entity_name, document),
                extraction_errors=["No content available for fallback"],
            )
        
        # Create a summary evidence item
        atomic_evidence = [AtomicEvidence(
            subject=entity_name or "",
            predicate="described_as",
            object=content[:200] + "..." if len(content) > 200 else content,
            passage=content[:500] + "..." if len(content) > 500 else content,
            evidence_type=EvidenceType.SUMMARY,
            source_url=document.url,
            source_title=document.title,
            document_id=document.document_id,
            chunk_index=0,
            confidence=0.5,
            extraction_method="fallback",
            metadata={
                "source_type": document.source_type,
                "entity_match_verified": self._verify_entity_match(entity_name, document),
            },
        )]
        
        return ExtractionResult(
            document=document,
            atomic_evidence=atomic_evidence,
            entity_match_verified=self._verify_entity_match(entity_name, document),
            extraction_errors=["Mistral API call failed, using fallback"],
        )
    
    async def extract_single(
        self,
        entity_name: str,
        evidence_record: EvidenceRecord,
        client: Any = None,
    ) -> ExtractionResult:
        """Extract from a single evidence record.
        
        Args:
            entity_name: The entity being researched
            evidence_record: Single EvidenceRecord to extract from
            client: Optional httpx.AsyncClient for reuse
            
        Returns:
            ExtractionResult for the document
        """
        results = await self.extract(entity_name, [evidence_record], client)
        return results[0] if results else ExtractionResult(
            document=ResearchDocument.from_evidence_record(evidence_record),
            atomic_evidence=[],
            entity_match_verified=False,
            extraction_errors=["No results returned"],
        )


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    "AtomicEvidence",
    "EvidenceType",
    "ExtractionResult",
    "ResearchDocument",
    "MistralSemanticExtractor",
]
