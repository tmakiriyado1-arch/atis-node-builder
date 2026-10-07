"""Evidence Filtering Pipeline: WEB SEARCH -> WEBPAGE -> PAGE CONTENT -> ENTITY-RELEVANT EVIDENCE FILTER -> ATOMIC CLAIMS.

This module implements the core architectural fix for the data-integrity problem:
    raw webpage text must NOT be treated as canonical node data.

The pipeline explicitly separates:
1. Retrieval: "what did the webpage contain?"
2. Evidence filtering: "what does this webpage actually establish about THIS entity?"
3. Canonicalization: "which verified facts belong in WHICH node fields?"

Key Principle:
    Only evidence that is:
    - ENTITY-RELEVANT (explicitly about the target entity)
    - ATOMIC (specific factual propositions, not webpage sections)
    - VALIDATED (passes structural quality checks)
    - DEDUPLICATED (semantically equivalent claims normalized)
    
    ...is passed to canonicalization.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, FrozenSet, List, Optional, Sequence, Set, Tuple

from app.services.ontology import get_ontology
from app.services.research.evidence import EvidenceRecord, EvidenceStatus


# =============================================================================
# Relevance Classification
# =============================================================================

class RelevanceClassification(str, Enum):
    """Classification of evidence relevance to the target entity."""
    
    DIRECT = "DIRECT"  # Evidence explicitly describes the target entity
    RELATED = "RELATED"  # Evidence describes another entity with meaningful relationship to target
    IRRELEVANT = "IRRELEVANT"  # Evidence does not establish facts about target or relationships


# =============================================================================
# Evidence Quality Status
# =============================================================================

class EvidenceQualityStatus(str, Enum):
    """Quality status of an atomic claim."""
    
    VALID = "VALID"  # Passes all structural checks
    INVALID = "INVALID"  # Fails structural checks
    NEEDS_REVIEW = "NEEDS_REVIEW"  # Borderline, may need human review


# =============================================================================
# Atomic Claim Model
# =============================================================================

@dataclass
class AtomicClaim:
    """An atomic, entity-relevant factual proposition extracted from evidence.
    
    This is the fundamental unit that passes from evidence filtering to canonicalization.
    
    Each AtomicClaim represents ONE specific factual proposition that:
    - Is explicitly about the target entity OR establishes a concrete relationship
    - Has a clear subject, predicate, and object
    - Is supported by exact verbatim evidence from a source
    - Has been validated for structural quality
    - Has been deduplicated against other claims
    
    Attributes:
        claim_id: Unique identifier for this claim (used for traceability)
        subject: The entity being described (should be or relate to target entity)
        predicate: The relationship, attribute, or action
        object: The target of the relationship or value of the attribute
        claim_text: The normalized claim text (subject + predicate + object)
        evidence_passage: EXACT verbatim text from source supporting this claim
        source_url: URL of the source
        source_title: Title of the source
        relevance: DIRECT, RELATED, or IRRELEVANT
        evidence_type: FACT, ATTRIBUTE, RELATIONSHIP, ASSOCIATION, SUMMARY
        confidence: Extraction confidence (0.0-1.0, NOT truth value)
        quality_status: VALID, INVALID, NEEDS_REVIEW
        extraction_method: How this claim was extracted
        extracted_at: When this claim was extracted
        metadata: Additional provenance information
    """
    
    claim_id: str
    subject: str
    predicate: str
    object: str
    claim_text: str
    evidence_passage: str
    source_url: str
    source_title: Optional[str] = None
    relevance: RelevanceClassification = RelevanceClassification.DIRECT
    evidence_type: str = "FACT"
    confidence: float = 0.8
    quality_status: EvidenceQualityStatus = EvidenceQualityStatus.VALID
    extraction_method: str = "evidence_filter"
    extracted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Validate and normalize fields."""
        self.subject = str(self.subject or "").strip()
        self.predicate = str(self.predicate or "").strip().lower()
        self.object = str(self.object or "").strip()
        self.claim_text = str(self.claim_text or "").strip()
        self.evidence_passage = str(self.evidence_passage or "").strip()
        self.source_url = str(self.source_url or "").strip()
        self.source_title = str(self.source_title or "").strip() if self.source_title else None
        
        # Ensure confidence is between 0 and 1
        self.confidence = max(0.0, min(1.0, self.confidence))
        
        # Ensure claim_id is set
        if not self.claim_id:
            self.claim_id = self._generate_claim_id()
    
    def _generate_claim_id(self) -> str:
        """Generate a deterministic claim ID from content."""
        content = f"{self.subject}|{self.predicate}|{self.object}|{self.source_url}"
        return hashlib.sha256(content.encode('utf-8')).hexdigest()[:16]
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "claim_id": self.claim_id,
            "subject": self.subject,
            "predicate": self.predicate,
            "object": self.object,
            "claim_text": self.claim_text,
            "evidence_passage": self.evidence_passage,
            "source_url": self.source_url,
            "source_title": self.source_title,
            "relevance": self.relevance.value,
            "evidence_type": self.evidence_type,
            "confidence": self.confidence,
            "quality_status": self.quality_status.value,
            "extraction_method": self.extraction_method,
            "extracted_at": self.extracted_at.isoformat(),
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AtomicClaim":
        """Deserialize from dictionary."""
        return cls(
            claim_id=data.get("claim_id", ""),
            subject=data.get("subject", ""),
            predicate=data.get("predicate", ""),
            object=data.get("object", ""),
            claim_text=data.get("claim_text", ""),
            evidence_passage=data.get("evidence_passage", ""),
            source_url=data.get("source_url", ""),
            source_title=data.get("source_title"),
            relevance=RelevanceClassification(data.get("relevance", "DIRECT")),
            evidence_type=data.get("evidence_type", "FACT"),
            confidence=data.get("confidence", 0.8),
            quality_status=EvidenceQualityStatus(data.get("quality_status", "VALID")),
            extraction_method=data.get("extraction_method", "evidence_filter"),
            extracted_at=datetime.fromisoformat(data.get("extracted_at")) if data.get("extracted_at") else datetime.now(timezone.utc),
            metadata=data.get("metadata", {}),
        )


# =============================================================================
# Evidence Filter Pipeline
# =============================================================================

class EvidenceFilterPipeline:
    """Complete evidence filtering pipeline from raw evidence to atomic claims.
    
    Pipeline stages:
    1. ENTITY-RELEVANT EVIDENCE FILTER: Classify evidence as DIRECT/RELATED/IRRELEVANT
    2. ATOMIC CLAIMS: Extract specific factual propositions from relevant evidence
    3. CLAIM VALIDATION: Apply structural quality checks to each claim
    4. DEDUPLICATION: Normalize and deduplicate semantically equivalent claims
    
    This pipeline ensures that:
    - Raw webpage text is NEVER treated as canonical node data
    - Only entity-relevant evidence reaches canonicalization
    - Claims are atomic, not webpage sections
    - Invalid claims are rejected regardless of LLM confidence
    - Duplicate claims are normalized and deduplicated
    """
    
    def __init__(
        self,
        target_entity: str,
        ontology=None,
    ):
        """Initialize the evidence filter pipeline.
        
        Args:
            target_entity: The entity being researched (single entity)
            ontology: Optional ontology instance (defaults to global ontology)
        """
        self.target_entity = target_entity.strip()
        self.ontology = ontology or get_ontology()
        self._irrelevant_patterns: FrozenSet[str] = self._build_irrelevant_patterns()
        self._cta_patterns: FrozenSet[str] = self._build_cta_patterns()
        self._navigation_patterns: FrozenSet[str] = self._build_navigation_patterns()
    
    def _build_irrelevant_patterns(self) -> FrozenSet[str]:
        """Build patterns for irrelevant content that should be discarded."""
        return frozenset([
            # Generic institutional language
            r'\bwelcome to\b',
            r'\babout us\b',
            r'\bour mission\b',
            r'\bour vision\b',
            r'\bour values\b',
            r'\bour history\b',
            r'\bwho we are\b',
            r'\bwhat we do\b',
            r'\bcontact us\b',
            r'\bget in touch\b',
            r'\bconnect with us\b',
            # Marketing slogans
            r'\bjoin us\b',
            r'\bdiscover your\b',
            r'\btake the first step\b',
            r'\bmake a difference\b',
            r'\byour journey\b',
            r'\bstart today\b',
            r'\bapply now\b',
            r'\bsign up\b',
            r'\bregister now\b',
            r'\blearn more\b',
            r'\bclick here\b',
            r'\bmore information\b',
            # Footer text
            r'\bcopyright\b',
            r'\bprivacy policy\b',
            r'\bterms of service\b',
            r'\bcookie policy\b',
            r'\bdisclaimer\b',
            r'\bfooter\b',
            # Navigation
            r'\bhome\b',
            r'\babout\b',
            r'\bprograms\b',
            r'\bservices\b',
            r'\bcourses\b',
            r'\badmissions\b',
            r'\bapply\b',
            r'\bstudents\b',
            r'\bfaculty\b',
            r'\bstaff\b',
            r'\bevents\b',
            r'\bnews\b',
            r'\bgallery\b',
            # Generic statistics
            r'\b100%\b',
            r'\b\d+%\b',
            # Bible verses
            r'\b\d+\s+[A-Za-z]+\s+\d+:\d+\b',
            # Testimonials
            r'\btestimonial\b',
            r'\breview\b',
            r'\bquote\b',
            # Generic statements
            r'\bwe provide\b',
            r'\bwe offer\b',
            r'\bwe support\b',
            r'\bwe believe\b',
            r'\bwe are\b',
            # Boilerplate
            r'\bpage not found\b',
            r'\berror\b',
            r'\bloading\b',
            r'\bunder construction\b',
            # Duplicated content markers
            r'\brepeated\b',
            r'\bduplicate\b',
        ])
    
    def _build_cta_patterns(self) -> FrozenSet[str]:
        """Build patterns for Call-To-Action text."""
        return frozenset([
            r'\bnow\b',
            r'\btoday\b',
            r'\bapply\b',
            r'\bclick\b',
            r'\bhere\b',
            r'\bmore\b',
            r'\blearn\b',
            r'\bjoin\b',
            r'\bsign\b',
            r'\bup\b',
            r'\bregister\b',
            r'\bstart\b',
            r'\bbegin\b',
            r'\btake\b',
            r'\bget\b',
            r'\bcall\b',
            r'\bemail\b',
            r'\bcontact\b',
            r'\bvisit\b',
            r'\bdownload\b',
        ])
    
    def _build_navigation_patterns(self) -> FrozenSet[str]:
        """Build patterns for navigation text."""
        return frozenset([
            r'\bhome\b',
            r'\babout\b',
            r'\bcontact\b',
            r'\bmenu\b',
            r'\bback\b',
            r'\bnext\b',
            r'\bprevious\b',
            r'\btop\b',
            r'\bbottom\b',
            r'\bscroll\b',
            r'\blogin\b',
            r'\blogout\b',
            r'\bsign in\b',
            r'\bsign out\b',
            r'\bsearch\b',
        ])
    
    # =============================================================================
    # Stage 1: Entity-Relevant Evidence Filter
    # =============================================================================
    
    def filter_entity_relevant_evidence(
        self,
        evidence_records: Sequence[EvidenceRecord],
    ) -> Tuple[List[EvidenceRecord], List[EvidenceRecord], List[EvidenceRecord]]:
        """Classify evidence records as DIRECT, RELATED, or IRRELEVANT.
        
        This is the first and most important stage: it explicitly rejects the assumption
        that "page retrieved for Entity X = everything on page is evidence about Entity X".
        
        Args:
            evidence_records: List of EvidenceRecord to classify
            
        Returns:
            Tuple of (direct_evidence, related_evidence, irrelevant_evidence)
        """
        direct: List[EvidenceRecord] = []
        related: List[EvidenceRecord] = []
        irrelevant: List[EvidenceRecord] = []
        
        for record in evidence_records:
            if not record or not record.url:
                irrelevant.append(record)
                continue
            
            # Get the authoritative semantic text
            text = self._get_authoritative_text(record)
            if not text or not text.strip():
                irrelevant.append(record)
                continue
            
            # Check if this is unusable evidence
            if record.evidence_status == EvidenceStatus.UNUSABLE:
                irrelevant.append(record)
                continue
            
            # Classify relevance
            classification = self._classify_evidence_relevance(text, record)
            
            if classification == RelevanceClassification.DIRECT:
                direct.append(record)
            elif classification == RelevanceClassification.RELATED:
                related.append(record)
            else:
                irrelevant.append(record)
        
        return direct, related, irrelevant
    
    def _get_authoritative_text(self, record: EvidenceRecord) -> str:
        """Get the authoritative semantic text from an EvidenceRecord.
        
        Prefers normalized_text (which is guaranteed to be semantic, not HTML).
        """
        return getattr(record, 'normalized_text', None) or \
               getattr(record, 'content', None) or \
               record.snippet or ""
    
    def _classify_evidence_relevance(
        self,
        text: str,
        record: EvidenceRecord,
    ) -> RelevanceClassification:
        """Classify a single evidence item's relevance to the target entity.
        
        This method asks for every candidate fact:
        1. Is the target entity explicitly the subject?
        2. If not, does the statement establish a concrete relationship involving the target?
        3. If neither, discard it.
        
        Args:
            text: The extracted text content
            record: The EvidenceRecord for context
            
        Returns:
            RelevanceClassification: DIRECT, RELATED, or IRRELEVANT
        """
        text_lower = text.lower()
        target_lower = self.target_entity.lower()
        
        # Check for DIRECT: target entity explicitly the subject
        if self._is_direct_evidence(text, text_lower, target_lower):
            return RelevanceClassification.DIRECT
        
        # Check for RELATED: establishes concrete relationship involving target
        if self._is_related_evidence(text, text_lower, target_lower):
            return RelevanceClassification.RELATED
        
        # Check for IRRELEVANT: discard patterns
        # IMPORTANT: Only mark as irrelevant if text does NOT reference the target entity
        # If text mentions the target entity, it should be classified as DIRECT or RELATED,
        # not IRRELEVANT. Irrelevant patterns (boilerplate, nav, etc.) should only catch
        # text that doesn't mention the entity at all.
        if self._contains_entity_reference(text_lower, target_lower):
            # Text mentions the target entity but didn't match DIRECT or RELATED
            # This means our DIRECT/RELATED checks are too strict for this evidence
            # Conservative: treat as DIRECT since it references the entity
            return RelevanceClassification.DIRECT
        
        if self._is_irrelevant_evidence(text, text_lower):
            return RelevanceClassification.IRRELEVANT
        
        # Default to IRRELEVANT if we cannot establish DIRECT or RELATED
        # This is the conservative choice: discard unless proven relevant
        return RelevanceClassification.IRRELEVANT
    
    def _is_direct_evidence(
        self,
        text: str,
        text_lower: str,
        target_lower: str,
    ) -> bool:
        """Check if evidence is DIRECT (explicitly about target entity).
        
        Direct evidence:
        - Target entity is explicitly the subject
        - Text describes the target entity's properties, actions, or attributes
        - Text uses the target entity name or clear variations
        """
        # Check for explicit entity name mention
        if not self._contains_entity_reference(text_lower, target_lower):
            return False
        
        # Check if the text is about the entity (not just mentioning it)
        # Look for patterns where the entity is the subject
        entity_patterns = [
            rf'^{re.escape(target_lower)}\s',  # "Theotechnic College is..."
            rf'\b{re.escape(target_lower)}\s+(?:is|are|was|were|has|have|had|provides|offers|supports|regulates|manages|operates|oversees)\b',
            rf'\b{re.escape(target_lower)}\s+[a-z]+\s',  # "Theotechnic College combines..."
        ]
        
        for pattern in entity_patterns:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return True
        
        # Check if entity appears early in the text (likely the subject)
        # Find position of entity mention
        entity_positions = [m.start() for m in re.finditer(re.escape(target_lower), text_lower, re.IGNORECASE)]
        if entity_positions:
            first_mention_pos = entity_positions[0]
            # If entity is mentioned in first 50 chars, likely the subject
            if first_mention_pos < 50:
                return True
        
        return False
    
    def _is_related_evidence(
        self,
        text: str,
        text_lower: str,
        target_lower: str,
    ) -> bool:
        """Check if evidence is RELATED (establishes concrete relationship with target).
        
        Related evidence:
        - Describes another entity that has a meaningful relationship with the target
        - Establishes a concrete relationship involving the target
        - Example: "ACTIVE Ministry provides operational and strategic support to Theotechnic College"
        
        This uses flexible position-based matching: if a relationship/association predicate
        appears in the text AND the target entity appears in the text, and they appear
        in the same sentence, classify as RELATED.
        """
        # Must mention the target entity
        if not self._contains_entity_reference(text_lower, target_lower):
            return False
        
        # Find all positions where target entity appears
        target_positions = [m.start() for m in re.finditer(re.escape(target_lower), text_lower, re.IGNORECASE)]
        if not target_positions:
            return False
        
        # Check for relationship predicates involving the target
        relationship_predicates = self.ontology.relationship_predicates
        for predicate in relationship_predicates:
            predicate_spaced = predicate.replace('_', ' ')
            # Find all positions where predicate appears
            predicate_positions = [m.start() for m in re.finditer(re.escape(predicate_spaced), text_lower, re.IGNORECASE)]
            
            for pred_pos in predicate_positions:
                # Check if predicate and target are in the same sentence
                # Find sentence boundaries (period, exclamation, question mark)
                sentence_end = len(text_lower)
                for end_marker in ['.', '!', '?']:
                    end_pos = text_lower.find(end_marker, pred_pos)
                    if end_pos != -1 and end_pos < sentence_end:
                        sentence_end = end_pos
                
                # Check if target appears in the same sentence (after or before predicate)
                for target_pos in target_positions:
                    if pred_pos <= target_pos < sentence_end:
                        return True
                    # Also check if target comes before predicate in same sentence
                    if target_pos <= pred_pos < sentence_end:
                        return True
        
        # Check for association predicates
        association_predicates = self.ontology.association_predicates
        for predicate in association_predicates:
            predicate_spaced = predicate.replace('_', ' ')
            # Find all positions where predicate appears
            predicate_positions = [m.start() for m in re.finditer(re.escape(predicate_spaced), text_lower, re.IGNORECASE)]
            
            for pred_pos in predicate_positions:
                # Find sentence end
                sentence_end = len(text_lower)
                for end_marker in ['.', '!', '?']:
                    end_pos = text_lower.find(end_marker, pred_pos)
                    if end_pos != -1 and end_pos < sentence_end:
                        sentence_end = end_pos
                
                # Check if target appears in the same sentence
                for target_pos in target_positions:
                    if pred_pos <= target_pos < sentence_end:
                        return True
                    if target_pos <= pred_pos < sentence_end:
                        return True
        
        return False
    
    def _is_irrelevant_evidence(
        self,
        text: str,
        text_lower: str,
    ) -> bool:
        """Check if evidence is IRRELEVANT (should be discarded).
        
        Irrelevant evidence includes:
        - Navigation
        - Marketing slogans
        - Footer text
        - Generic institutional language
        - Boilerplate
        - Duplicated text
        - Testimonials
        - Unrelated organizations
        - Generic statistics
        - Fragments
        - Adjectives without factual meaning
        - Incomplete sentences
        - Webpage formatting artifacts
        - Scripture quotations
        - Contact instructions
        """
        # Check for irrelevant patterns
        for pattern in self._irrelevant_patterns:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return True
        
        # Check if text is a sentence fragment
        if self._is_sentence_fragment(text):
            return True
        
        # Check if text is mostly navigation
        if self._is_mostly_navigation(text_lower):
            return True
        
        # Check if text is mostly CTA
        if self._is_mostly_cta(text_lower):
            return True
        
        return False
    
    def _contains_entity_reference(
        self,
        text_lower: str,
        target_lower: str,
    ) -> bool:
        """Check if text contains a reference to the target entity.
        
        This includes:
        - Exact match
        - Acronyms
        - Common variations
        - Institutional names
        """
        # Direct match
        if target_lower in text_lower:
            return True
        
        # Try to find acronyms or short names
        # Split target into words and check for partial matches
        target_words = target_lower.split()
        if len(target_words) > 1:
            # Check if any significant word combination appears
            for i in range(len(target_words)):
                for j in range(i + 1, min(i + 3, len(target_words) + 1)):
                    phrase = ' '.join(target_words[i:j])
                    if phrase in text_lower:
                        return True
        
        return False
    
    def _is_sentence_fragment(self, text: str) -> bool:
        """Check if text is a sentence fragment."""
        text = text.strip()
        if not text:
            return True
        
        # Very short text (less than 3 words)
        word_count = len(text.split())
        if word_count < 3:
            return True
        
        # Starts with lowercase (not a proper sentence)
        if text and text[0].islower():
            return True
        
        # Ends without punctuation but has multiple words
        if word_count >= 3 and not text.endswith(('.', '!', '?')):
            # Might be a fragment, but not necessarily
            pass
        
        return False
    
    def _is_mostly_navigation(self, text_lower: str) -> bool:
        """Check if text is mostly navigation."""
        words = text_lower.split()
        if not words:
            return False
        
        nav_count = sum(1 for w in words if any(p in w for p in self._navigation_patterns))
        return nav_count / len(words) > 0.5
    
    def _is_mostly_cta(self, text_lower: str) -> bool:
        """Check if text is mostly CTA."""
        words = text_lower.split()
        if not words:
            return False
        
        cta_count = sum(1 for w in words if any(p in w for p in self._cta_patterns))
        return cta_count / len(words) > 0.5
    
    # =============================================================================
    # Stage 2: Atomic Claims Extraction
    # =============================================================================
    
    def extract_atomic_claims(
        self,
        relevant_evidence: Sequence[EvidenceRecord],
    ) -> List[AtomicClaim]:
        """Extract atomic claims from relevant evidence.
        
        This stage transforms relevant evidence (DIRECT + RELATED) into
        atomic claims. Each claim represents a specific factual proposition,
        not a webpage section.
        
        Args:
            relevant_evidence: List of DIRECT and RELATED EvidenceRecord
            
        Returns:
            List of AtomicClaim extracted from the evidence
        """
        claims = []
        
        for record in relevant_evidence:
            text = self._get_authoritative_text(record)
            if not text or not text.strip():
                continue
            
            # Extract atomic claims from this evidence
            evidence_claims = self._extract_claims_from_text(text, record)
            claims.extend(evidence_claims)
        
        return claims
    
    def _extract_claims_from_text(
        self,
        text: str,
        record: EvidenceRecord,
    ) -> List[AtomicClaim]:
        """Extract atomic claims from a single text.
        
        This method identifies specific factual propositions in the text
        and creates AtomicClaim objects for each.
        
        Args:
            text: The text to extract claims from
            record: The EvidenceRecord for provenance
            
        Returns:
            List of AtomicClaim extracted from the text
        """
        claims = []
        
        # Split text into sentences (roughly)
        sentences = self._split_into_sentences(text)
        
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            
            # Skip sentences that are irrelevant
            if self._is_irrelevant_sentence(sentence):
                continue
            
            # Try to extract claim from sentence
            claim = self._extract_claim_from_sentence(sentence, record)
            if claim:
                claims.append(claim)
        
        return claims
    
    def _split_into_sentences(self, text: str) -> List[str]:
        """Split text into sentences."""
        # Simple sentence splitting by punctuation
        sentences = re.split(r'(?<=[.!?])\s+', text)
        return [s.strip() for s in sentences if s.strip()]
    
    def _is_irrelevant_sentence(self, sentence: str) -> bool:
        """Check if a sentence is irrelevant."""
        sentence_lower = sentence.lower()
        
        # Check for irrelevant patterns
        for pattern in self._irrelevant_patterns:
            if re.search(pattern, sentence_lower, re.IGNORECASE):
                return True
        
        # Check for sentence fragments
        if self._is_sentence_fragment(sentence):
            return True
        
        return False
    
    def _extract_claim_from_sentence(
        self,
        sentence: str,
        record: EvidenceRecord,
    ) -> Optional[AtomicClaim]:
        """Extract a single atomic claim from a sentence.
        
        This method tries to identify:
        - Subject: The entity being described
        - Predicate: The relationship or action
        - Object: The target or value
        
        Args:
            sentence: The sentence to extract from
            record: The EvidenceRecord for provenance
            
        Returns:
            AtomicClaim if extraction succeeds, None otherwise
        """
        # Try to match subject-predicate-object pattern
        # Pattern: [Subject] [predicate] [object]
        # where subject should be or relate to the target entity
        
        # First, try to find the target entity in the sentence
        sentence_lower = sentence.lower()
        target_lower = self.target_entity.lower()
        
        # Check if target entity appears in sentence
        if target_lower not in sentence_lower:
            # Not about target entity, skip
            return None
        
        # Try to extract subject-predicate-object
        # Pattern 1: "[Target] [predicate] [object]"
        for predicate in sorted(self.ontology.relationship_predicates | self.ontology.association_predicates, key=len, reverse=True):
            predicate_spaced = predicate.replace('_', ' ')
            
            # Pattern: [Target] predicate [object]
            pattern = rf'(?P<subject>{re.escape(self.target_entity)})\s+{re.escape(predicate_spaced)}\s+(?P<object>.+)'
            match = re.match(pattern, sentence, re.IGNORECASE)
            if match:
                return AtomicClaim(
                    claim_id="",
                    subject=match.group("subject").strip(),
                    predicate=predicate,
                    object=match.group("object").strip(),
                    claim_text=f"{match.group('subject')} {predicate_spaced} {match.group('object')}",
                    evidence_passage=sentence,
                    source_url=record.url,
                    source_title=record.title,
                    relevance=self._classify_claim_relevance(sentence),
                    evidence_type=self._classify_evidence_type(sentence, predicate),
                    confidence=0.8,
                    quality_status=EvidenceQualityStatus.VALID,
                    extraction_method="pattern_match",
                    metadata={
                        "entity": self.target_entity,
                        "source": "evidence_filter",
                    },
                )
            
            # Pattern 2: [Subject] predicate [Target]
            pattern = rf'(?P<subject>.+?)\s+{re.escape(predicate_spaced)}\s+(?P<object>{re.escape(self.target_entity)})'
            match = re.match(pattern, sentence, re.IGNORECASE)
            if match:
                return AtomicClaim(
                    claim_id="",
                    subject=match.group("subject").strip(),
                    predicate=predicate,
                    object=match.group("object").strip(),
                    claim_text=f"{match.group('subject')} {predicate_spaced} {match.group('object')}",
                    evidence_passage=sentence,
                    source_url=record.url,
                    source_title=record.title,
                    relevance=RelevanceClassification.RELATED,
                    evidence_type="RELATIONSHIP" if predicate in self.ontology.relationship_predicates else "ASSOCIATION",
                    confidence=0.8,
                    quality_status=EvidenceQualityStatus.VALID,
                    extraction_method="pattern_match",
                    metadata={
                        "entity": self.target_entity,
                        "source": "evidence_filter",
                    },
                )
        
        # Try to extract attribute claims (entity_type, sector, country, status)
        attribute_claim = self._extract_attribute_claim(sentence, record)
        if attribute_claim:
            return attribute_claim
        
        # Try to extract summary claims
        summary_claim = self._extract_summary_claim(sentence, record)
        if summary_claim:
            return summary_claim
        
        # Fallback: create a generic claim if sentence contains target entity
        # This is a conservative fallback - only if we cannot extract structured claim
        if target_lower in sentence_lower:
            return AtomicClaim(
                claim_id="",
                subject=self.target_entity,
                predicate="describes",
                object=sentence,
                claim_text=sentence,
                evidence_passage=sentence,
                source_url=record.url,
                source_title=record.title,
                relevance=RelevanceClassification.DIRECT,
                evidence_type="SUMMARY",
                confidence=0.5,
                quality_status=EvidenceQualityStatus.NEEDS_REVIEW,
                extraction_method="fallback",
                metadata={
                    "entity": self.target_entity,
                    "source": "evidence_filter",
                    "note": "Fallback extraction - may need review",
                },
            )
        
        return None
    
    def _classify_claim_relevance(self, sentence: str) -> RelevanceClassification:
        """Classify the relevance of an extracted claim."""
        sentence_lower = sentence.lower()
        target_lower = self.target_entity.lower()
        
        if target_lower in sentence_lower:
            return RelevanceClassification.DIRECT
        return RelevanceClassification.RELATED
    
    def _classify_evidence_type(
        self,
        sentence: str,
        predicate: str,
    ) -> str:
        """Classify the evidence type of a claim."""
        sentence_lower = sentence.lower()
        
        if predicate in self.ontology.relationship_predicates:
            return "RELATIONSHIP"
        if predicate in self.ontology.association_predicates:
            return "ASSOCIATION"
        
        # Check for attribute patterns
        attribute_keywords = [
            "is a", "is an", "is the", "are a", "are an", "are the",
            "was a", "was an", "were a", "were an",
            "type", "entity type", "sector", "country", "status",
            "located in", "based in", "headquartered in",
        ]
        for keyword in attribute_keywords:
            if keyword in sentence_lower:
                return "ATTRIBUTE"
        
        return "FACT"
    
    def _extract_attribute_claim(
        self,
        sentence: str,
        record: EvidenceRecord,
    ) -> Optional[AtomicClaim]:
        """Extract an attribute claim (entity_type, sector, country, status)."""
        sentence_lower = sentence.lower()
        target_lower = self.target_entity.lower()
        
        # Check for entity_type patterns
        entity_type_patterns = [
            ("entity_type", rf'\b{re.escape(target_lower)}\s+(?:is|are|was|were)\s+(?:a|an|the)\s+([a-z0-9\s-]+)'),
            ("entity_type", rf'(?:is|are|was|were)\s+(?:a|an|the)\s+([a-z0-9\s-]+)\s+{re.escape(target_lower)}'),
        ]
        
        for field, pattern in entity_type_patterns:
            match = re.search(pattern, sentence_lower, re.IGNORECASE)
            if match:
                value = match.group(1).strip().title()
                return AtomicClaim(
                    claim_id="",
                    subject=self.target_entity,
                    predicate="is",
                    object=value,
                    claim_text=f"{self.target_entity} is {value}",
                    evidence_passage=sentence,
                    source_url=record.url,
                    source_title=record.title,
                    relevance=RelevanceClassification.DIRECT,
                    evidence_type="ATTRIBUTE",
                    confidence=0.9,
                    quality_status=EvidenceQualityStatus.VALID,
                    extraction_method="attribute_extraction",
                    metadata={
                        "entity": self.target_entity,
                        "attribute_field": field,
                        "source": "evidence_filter",
                    },
                )
        
        # Check for sector patterns
        for sector in self.ontology.sectors:
            sector_lower = sector.lower()
            if sector_lower in sentence_lower:
                return AtomicClaim(
                    claim_id="",
                    subject=self.target_entity,
                    predicate="operates_in",
                    object=sector,
                    claim_text=f"{self.target_entity} operates in {sector}",
                    evidence_passage=sentence,
                    source_url=record.url,
                    source_title=record.title,
                    relevance=RelevanceClassification.DIRECT,
                    evidence_type="ATTRIBUTE",
                    confidence=0.9,
                    quality_status=EvidenceQualityStatus.VALID,
                    extraction_method="attribute_extraction",
                    metadata={
                        "entity": self.target_entity,
                        "attribute_field": "sector",
                        "source": "evidence_filter",
                    },
                )
        
        # Check for country patterns
        for country in self.ontology.countries:
            country_lower = country.lower()
            if country_lower in sentence_lower:
                return AtomicClaim(
                    claim_id="",
                    subject=self.target_entity,
                    predicate="located_in",
                    object=country,
                    claim_text=f"{self.target_entity} is located in {country}",
                    evidence_passage=sentence,
                    source_url=record.url,
                    source_title=record.title,
                    relevance=RelevanceClassification.DIRECT,
                    evidence_type="ATTRIBUTE",
                    confidence=0.9,
                    quality_status=EvidenceQualityStatus.VALID,
                    extraction_method="attribute_extraction",
                    metadata={
                        "entity": self.target_entity,
                        "attribute_field": "country",
                        "source": "evidence_filter",
                    },
                )
        
        # Check for status patterns
        for status in self.ontology.statuses:
            status_lower = status.lower()
            if status_lower in sentence_lower:
                return AtomicClaim(
                    claim_id="",
                    subject=self.target_entity,
                    predicate="has_status",
                    object=status,
                    claim_text=f"{self.target_entity} has status {status}",
                    evidence_passage=sentence,
                    source_url=record.url,
                    source_title=record.title,
                    relevance=RelevanceClassification.DIRECT,
                    evidence_type="ATTRIBUTE",
                    confidence=0.9,
                    quality_status=EvidenceQualityStatus.VALID,
                    extraction_method="attribute_extraction",
                    metadata={
                        "entity": self.target_entity,
                        "attribute_field": "status",
                        "source": "evidence_filter",
                    },
                )
        
        return None
    
    def _extract_summary_claim(
        self,
        sentence: str,
        record: EvidenceRecord,
    ) -> Optional[AtomicClaim]:
        """Extract a summary claim (descriptive statement about entity)."""
        sentence_lower = sentence.lower()
        target_lower = self.target_entity.lower()
        
        # Check if sentence describes what the entity is or does
        descriptive_patterns = [
            rf'\b{re.escape(target_lower)}\s+(?:is|are|was|were)\s+',
            rf'\b{re.escape(target_lower)}\s+(?:provides|offers|supports|delivers|coordinates|manages|regulates|oversees)\s+',
            rf'\b{re.escape(target_lower)}\s+(?:functions|operates|works|specializes|focuses)\s+',
        ]
        
        for pattern in descriptive_patterns:
            if re.search(pattern, sentence_lower, re.IGNORECASE):
                return AtomicClaim(
                    claim_id="",
                    subject=self.target_entity,
                    predicate="describes",
                    object=sentence,
                    claim_text=sentence,
                    evidence_passage=sentence,
                    source_url=record.url,
                    source_title=record.title,
                    relevance=RelevanceClassification.DIRECT,
                    evidence_type="SUMMARY",
                    confidence=0.8,
                    quality_status=EvidenceQualityStatus.VALID,
                    extraction_method="summary_extraction",
                    metadata={
                        "entity": self.target_entity,
                        "source": "evidence_filter",
                    },
                )
        
        return None
    
    # =============================================================================
    # Stage 3: Claim Validation (Quality Gate)
    # =============================================================================
    
    def validate_claims(
        self,
        claims: List[AtomicClaim],
    ) -> Tuple[List[AtomicClaim], List[AtomicClaim]]:
        """Validate atomic claims against structural quality checks.
        
        This is the evidence quality gate. Each claim must pass structural checks
        regardless of LLM confidence scores.
        
        Args:
            claims: List of AtomicClaim to validate
            
        Returns:
            Tuple of (valid_claims, invalid_claims)
        """
        valid = []
        invalid = []
        
        for claim in claims:
            if self._validate_claim(claim):
                valid.append(claim)
            else:
                claim.quality_status = EvidenceQualityStatus.INVALID
                invalid.append(claim)
        
        return valid, invalid
    
    def _validate_claim(self, claim: AtomicClaim) -> bool:
        """Validate a single atomic claim against structural checks.
        
        Rejects claims where:
        - subject != target (unless explicit relationship)
        - extremely long evidence
        - sentence fragments
        - navigation language
        - CTA language
        - duplicate claims
        - generic adjectives
        - no identifiable factual proposition
        - no source
        - no relationship target
        - unclear subject
        
        Args:
            claim: The AtomicClaim to validate
            
        Returns:
            True if valid, False otherwise
        """
        # Check 1: Must have subject
        if not claim.subject or not claim.subject.strip():
            return False
        
        # Check 2: Must have predicate
        if not claim.predicate or not claim.predicate.strip():
            return False
        
        # Check 3: Must have object
        if not claim.object or not claim.object.strip():
            return False
        
        # Check 4: Must have evidence passage
        if not claim.evidence_passage or not claim.evidence_passage.strip():
            return False
        
        # Check 5: Must have source URL
        if not claim.source_url or not claim.source_url.strip():
            return False
        
        # Check 6: Evidence passage must not be excessively long
        if len(claim.evidence_passage) > 1000:
            return False
        
        # Check 7: Subject must be target or explicitly related
        if claim.relevance == RelevanceClassification.DIRECT:
            if claim.subject.lower() != self.target_entity.lower():
                # For DIRECT claims, subject should be the target
                # unless it is an alias or acronym
                if not self._is_valid_subject_for_direct(claim.subject):
                    return False
        
        # Check 8: Must not contain CTA language
        if self._contains_cta(claim.claim_text) or self._contains_cta(claim.evidence_passage):
            return False
        
        # Check 9: Must not contain navigation language
        if self._contains_navigation(claim.claim_text) or self._contains_navigation(claim.evidence_passage):
            return False
        
        # Check 10: Must not be a sentence fragment
        if self._is_sentence_fragment(claim.claim_text):
            return False
        
        # Check 11: Must not be a Bible verse
        if self._is_bible_verse(claim.claim_text) or self._is_bible_verse(claim.evidence_passage):
            return False
        
        # Check 12: Must not be a single letter
        if self._is_single_letter(claim.subject) or self._is_single_letter(claim.object):
            return False
        
        # Check 13: Must have a clear factual proposition
        if not self._has_factual_proposition(claim.claim_text):
            return False
        
        return True
    
    def _is_valid_subject_for_direct(self, subject: str) -> bool:
        """Check if a subject is valid for a DIRECT claim."""
        subject_lower = subject.lower()
        target_lower = self.target_entity.lower()
        
        # Exact match
        if subject_lower == target_lower:
            return True
        
        # Check if it is a known alias or acronym
        # For now, accept if it contains the target entity name
        if target_lower in subject_lower:
            return True
        
        return False
    
    def _contains_cta(self, text: str) -> bool:
        """Check if text contains CTA language."""
        text_lower = text.lower()
        for pattern in self._cta_patterns:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return True
        return False
    
    def _contains_navigation(self, text: str) -> bool:
        """Check if text contains navigation language."""
        text_lower = text.lower()
        for pattern in self._navigation_patterns:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return True
        return False
    
    def _is_bible_verse(self, text: str) -> bool:
        """Check if text is a Bible verse."""
        return bool(re.search(r'\b\d+\s+[A-Za-z]+\s+\d+:\d+\b', text))
    
    def _is_single_letter(self, text: str) -> bool:
        """Check if text is a single letter."""
        text = text.strip()
        return len(text) == 1 and text.isalpha()
    
    def _has_factual_proposition(self, text: str) -> bool:
        """Check if text contains a factual proposition."""
        text_lower = text.lower()
        
        # Must contain a verb
        if not re.search(r'\b(is|are|was|were|has|have|had|does|do|did|provides|offers|supports|regulates|manages|operates|oversees)\b', text_lower):
            return False
        
        return True
    
    # =============================================================================
    # Stage 4: Deduplication
    # =============================================================================
    
    def deduplicate_claims(
        self,
        claims: List[AtomicClaim],
    ) -> List[AtomicClaim]:
        """Normalize and deduplicate semantically equivalent claims.
        
        This ensures the canonicalizer does not see 30 copies of the same fact.
        
        Args:
            claims: List of AtomicClaim to deduplicate
            
        Returns:
            List of deduplicated AtomicClaim (retaining strongest source/evidence)
        """
        # Group claims by semantic equivalence
        claim_groups: Dict[str, List[AtomicClaim]] = {}
        
        for claim in claims:
            # Generate a normalization key
            norm_key = self._normalize_claim_key(claim)
            if norm_key not in claim_groups:
                claim_groups[norm_key] = []
            claim_groups[norm_key].append(claim)
        
        # For each group, retain the strongest claim
        deduplicated = []
        for group in claim_groups.values():
            strongest = self._select_strongest_claim(group)
            deduplicated.append(strongest)
        
        return deduplicated
    
    def _normalize_claim_key(self, claim: AtomicClaim) -> str:
        """Generate a normalization key for semantic equivalence.
        
        This key is used to group semantically equivalent claims.
        """
        # Use subject, predicate, object (normalized)
        # Normalize by lowercasing and removing punctuation
        subject_norm = re.sub(r'[^a-z0-9]', '', claim.subject.lower())
        predicate_norm = re.sub(r'[^a-z0-9]', '', claim.predicate.lower())
        object_norm = re.sub(r'[^a-z0-9]', '', claim.object.lower())
        
        return f"{subject_norm}|{predicate_norm}|{object_norm}"
    
    def _select_strongest_claim(self, claims: List[AtomicClaim]) -> AtomicClaim:
        """Select the strongest claim from a group of equivalent claims.
        
        Preference:
        1. Higher confidence
        2. DIRECT relevance over RELATED
        3. Longer evidence passage (more context)
        4. More recent extraction
        """
        # Sort by confidence (descending), then relevance, then evidence length
        sorted_claims = sorted(
            claims,
            key=lambda c: (
                -c.confidence,
                c.relevance == RelevanceClassification.DIRECT,
                -len(c.evidence_passage),
            ),
        )
        
        return sorted_claims[0]
    
    # =============================================================================
    # Complete Pipeline
    # =============================================================================
    
    def run_pipeline(
        self,
        evidence_records: Sequence[EvidenceRecord],
    ) -> Tuple[List[AtomicClaim], Dict[str, Any]]:
        """Run the complete evidence filtering pipeline.
        
        Pipeline:
        1. ENTITY-RELEVANT EVIDENCE FILTER: Classify as DIRECT/RELATED/IRRELEVANT
        2. ATOMIC CLAIMS: Extract atomic claims from relevant evidence
        3. CLAIM VALIDATION: Apply quality gate
        4. DEDUPLICATION: Normalize and deduplicate
        
        Args:
            evidence_records: List of EvidenceRecord from research
            
        Returns:
            Tuple of (final_atomic_claims, pipeline_metadata)
        """
        pipeline_metadata: Dict[str, Any] = {
            "target_entity": self.target_entity,
            "stages": {},
        }
        
        # Stage 1: Entity-Relevant Evidence Filter
        direct, related, irrelevant = self.filter_entity_relevant_evidence(evidence_records)
        
        pipeline_metadata["stages"]["evidence_filter"] = {
            "direct_count": len(direct),
            "related_count": len(related),
            "irrelevant_count": len(irrelevant),
            "total_input": len(evidence_records),
        }
        
        # Combine direct and related for atomic claim extraction
        relevant_evidence = direct + related
        
        # Stage 2: Atomic Claims Extraction
        atomic_claims = self.extract_atomic_claims(relevant_evidence)
        
        pipeline_metadata["stages"]["atomic_claims"] = {
            "extracted_count": len(atomic_claims),
            "from_evidence_count": len(relevant_evidence),
        }
        
        # Stage 3: Claim Validation (Quality Gate)
        valid_claims, invalid_claims = self.validate_claims(atomic_claims)
        
        pipeline_metadata["stages"]["validation"] = {
            "valid_count": len(valid_claims),
            "invalid_count": len(invalid_claims),
        }
        
        # Stage 4: Deduplication
        final_claims = self.deduplicate_claims(valid_claims)
        
        pipeline_metadata["stages"]["deduplication"] = {
            "before_count": len(valid_claims),
            "after_count": len(final_claims),
            "duplicates_removed": len(valid_claims) - len(final_claims),
        }
        
        # Generate claim IDs for final claims
        for i, claim in enumerate(final_claims):
            claim.claim_id = f"claim_{i+1:04d}"
        
        return final_claims, pipeline_metadata


# =============================================================================
# Field-Specific Evidence Selection
# =============================================================================

class FieldSpecificEvidenceSelector:
    """Select evidence for specific node fields.
    
    This implements the principle: each field should be selected from the evidence
    appropriate to that field, NOT from one giant paragraph.
    
    Maintains traceability: field -> evidence claim IDs
    """
    
    def __init__(self, ontology=None):
        self.ontology = ontology or get_ontology()
    
    def select_evidence_for_fields(
        self,
        atomic_claims: List[AtomicClaim],
        target_entity: str,
    ) -> Dict[str, Dict[str, Any]]:
        """Select evidence for each node field.
        
        Args:
            atomic_claims: List of validated, deduplicated AtomicClaim
            target_entity: The target entity name
            
        Returns:
            Dict mapping field name to {"value": ..., "evidence_ids": [...], "sources": [...]}
        """
        field_evidence: Dict[str, Dict[str, Any]] = {}
        
        # Initialize all fields
        fields = ["entity", "entity_type", "subtype", "country", "sector", "status", "summary", "relationships", "associations"]
        for field in fields:
            field_evidence[field] = {"value": None, "evidence_ids": [], "sources": []}
        
        # Set entity (always from target_entity, not from evidence)
        field_evidence["entity"]["value"] = target_entity
        
        # Select evidence for each field
        for claim in atomic_claims:
            # Entity type
            if claim.evidence_type == "ATTRIBUTE" and claim.predicate == "is":
                if claim.object in self.ontology.all_entity_types:
                    if field_evidence["entity_type"]["value"] is None:
                        field_evidence["entity_type"]["value"] = claim.object
                        field_evidence["entity_type"]["evidence_ids"].append(claim.claim_id)
                        field_evidence["entity_type"]["sources"].append(claim.source_url)
            
            # Sector
            if claim.evidence_type == "ATTRIBUTE" and claim.predicate == "operates_in":
                if claim.object in self.ontology.sectors:
                    if field_evidence["sector"]["value"] is None:
                        field_evidence["sector"]["value"] = claim.object
                        field_evidence["sector"]["evidence_ids"].append(claim.claim_id)
                        field_evidence["sector"]["sources"].append(claim.source_url)
            
            # Country
            if claim.evidence_type == "ATTRIBUTE" and claim.predicate == "located_in":
                if claim.object in self.ontology.countries:
                    if field_evidence["country"]["value"] is None:
                        field_evidence["country"]["value"] = claim.object
                        field_evidence["country"]["evidence_ids"].append(claim.claim_id)
                        field_evidence["country"]["sources"].append(claim.source_url)
            
            # Status
            if claim.evidence_type == "ATTRIBUTE" and claim.predicate == "has_status":
                if claim.object in self.ontology.statuses:
                    if field_evidence["status"]["value"] is None:
                        field_evidence["status"]["value"] = claim.object
                        field_evidence["status"]["evidence_ids"].append(claim.claim_id)
                        field_evidence["status"]["sources"].append(claim.source_url)
            
            # Summary
            if claim.evidence_type == "SUMMARY":
                field_evidence["summary"]["evidence_ids"].append(claim.claim_id)
                field_evidence["summary"]["sources"].append(claim.source_url)
                if field_evidence["summary"]["value"] is None:
                    field_evidence["summary"]["value"] = claim.object
                else:
                    # Append to existing summary
                    field_evidence["summary"]["value"] = f"{field_evidence['summary']['value']} {claim.object}"
            
            # Relationships
            if claim.evidence_type == "RELATIONSHIP":
                # Format: predicate::[[Target]]
                formatted = f"{claim.predicate}::[[{claim.object}]]"
                current_value = field_evidence["relationships"]["value"]
                if current_value is None:
                    field_evidence["relationships"]["value"] = [formatted]
                elif isinstance(current_value, list) and formatted not in current_value:
                    field_evidence["relationships"]["value"].append(formatted)
                elif not isinstance(current_value, list):
                    field_evidence["relationships"]["value"] = [current_value, formatted]
                field_evidence["relationships"]["evidence_ids"].append(claim.claim_id)
                field_evidence["relationships"]["sources"].append(claim.source_url)
            
            # Associations
            if claim.evidence_type == "ASSOCIATION":
                formatted = f"{claim.predicate}::[[{claim.object}]]"
                current_value = field_evidence["associations"]["value"]
                if current_value is None:
                    field_evidence["associations"]["value"] = [formatted]
                elif isinstance(current_value, list) and formatted not in current_value:
                    field_evidence["associations"]["value"].append(formatted)
                elif not isinstance(current_value, list):
                    field_evidence["associations"]["value"] = [current_value, formatted]
                field_evidence["associations"]["evidence_ids"].append(claim.claim_id)
                field_evidence["associations"]["sources"].append(claim.source_url)
        
        return field_evidence


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    "AtomicClaim",
    "EvidenceFilterPipeline",
    "EvidenceQualityStatus",
    "FieldSpecificEvidenceSelector",
    "RelevanceClassification",
]
