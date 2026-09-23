"""Entity resolution validation for rejecting mismatched candidates.

This module provides semantic validation to ensure that Wikidata/Wikipedia candidates
do not contaminate the research with incorrect entity metadata.

Key principle: A candidate must pass semantic validation before its metadata
can be associated with the requested entity.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from app.services.entity_resolution.registry import ResolutionState


class CandidateStatus(str, Enum):
    """Status of a candidate entity after validation."""
    ACCEPTED = "accepted"           # Candidate matches the requested entity
    REJECTED = "rejected"           # Candidate does NOT match (semantic mismatch)
    AMBIGUOUS = "ambiguous"         # Cannot determine with confidence
    PENDING = "pending"             # Not yet validated


class RejectionReason(str, Enum):
    """Reason for rejecting a candidate entity."""
    SEMANTIC_MISMATCH = "semantic_mismatch"  # Labels/descriptions don't match
    TYPE_MISMATCH = "type_mismatch"          # Entity types are incompatible
    COUNTRY_MISMATCH = "country_mismatch"    # Country/location doesn't match
    SECTOR_MISMATCH = "sector_mismatch"      # Sector/industry doesn't match
    DOMAIN_MISMATCH = "domain_mismatch"      # URL domain doesn't match expected
    LOW_CONFIDENCE = "low_confidence"        # Confidence score too low
    NO_EVIDENCE = "no_evidence"              # No supporting evidence found
    CONTRADICTORY_EVIDENCE = "contradictory_evidence"  # Evidence contradicts


@dataclass
class CandidateValidation:
    """Result of validating a candidate entity against the requested entity."""
    candidate_id: str  # e.g., "Q1761087"
    candidate_name: str  # e.g., "Zera"
    candidate_description: str = ""
    candidate_metadata: Dict[str, Any] = field(default_factory=dict)
    status: CandidateStatus = CandidateStatus.PENDING
    rejection_reason: Optional[RejectionReason] = None
    rejection_details: str = ""
    confidence: float = 0.0  # 0-1 confidence in the match
    matching_terms: List[str] = field(default_factory=list)
    non_matching_terms: List[str] = field(default_factory=list)
    supporting_evidence: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "candidate_id": self.candidate_id,
            "candidate_name": self.candidate_name,
            "candidate_description": self.candidate_description,
            "candidate_metadata": self.candidate_metadata,
            "status": self.status.value,
            "rejection_reason": self.rejection_reason.value if self.rejection_reason else None,
            "rejection_details": self.rejection_details,
            "confidence": self.confidence,
            "matching_terms": self.matching_terms,
            "non_matching_terms": self.non_matching_terms,
            "supporting_evidence": self.supporting_evidence,
        }


@dataclass
class EntityResolution:
    """Complete entity resolution result with validated candidates."""
    requested_entity: str
    resolved_entity: Optional[str] = None
    resolved_entity_id: Optional[str] = None
    status: str = "UNRESOLVED"  # RESOLVED, AMBIGUOUS, UNRESOLVED, REJECTED
    candidates: List[CandidateValidation] = field(default_factory=list)
    accepted_candidates: List[CandidateValidation] = field(default_factory=list)
    rejected_candidates: List[CandidateValidation] = field(default_factory=list)
    ambiguous_candidates: List[CandidateValidation] = field(default_factory=list)
    evidence_sources: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "requested_entity": self.requested_entity,
            "resolved_entity": self.resolved_entity,
            "resolved_entity_id": self.resolved_entity_id,
            "status": self.status,
            "candidates": [c.to_dict() for c in self.candidates],
            "accepted_candidates": [c.to_dict() for c in self.accepted_candidates],
            "rejected_candidates": [c.to_dict() for c in self.rejected_candidates],
            "ambiguous_candidates": [c.to_dict() for c in self.ambiguous_candidates],
            "evidence_sources": self.evidence_sources,
        }


class EntityValidator:
    """Validate entity candidates against the requested entity.
    
    This validator ensures that:
    1. Wikidata candidates with semantic mismatches are REJECTED
    2. Their metadata cannot contaminate the canonical node
    3. Only candidates that pass validation contribute to entity resolution
    
    Example:
        Requested: "Zimbabwe Energy Regulatory Authority (ZERA)"
        Candidate: "Zera (Q1761087)" - genus of insects
        Result: REJECTED with reason SEMANTIC_MISMATCH
    """

    # Keywords that indicate biological/non-organization entities
    BIOLOGICAL_KEYWORDS = {
        "genus", "species", "family", "order", "class", "phylum", "kingdom",
        "insect", "insects", "animal", "animals", "plant", "plants",
        "organism", "organisms", "biology", "biological", "taxonomy", "taxon",
        "ncbi", "taxonomic", "zoology", "botany",
    }
    
    # Keywords that indicate organization entities
    ORGANIZATION_KEYWORDS = {
        "authority", "regulatory", "regulator", "commission", "agency",
        "government", "ministry", "department", "bureau", "office",
        "organization", "institution", "company", "corporation",
        "pool", "cooperation", "consortium", "alliance",
        "council", "committee", "board", "foundation",
    }
    
    # Keywords that indicate location entities
    LOCATION_KEYWORDS = {
        "country", "nation", "state", "province", "region",
        "city", "town", "district", "location",
    }
    
    # Keywords that indicate person entities
    PERSON_KEYWORDS = {
        "person", "people", "human", "individual",
    }
    
    # Keywords that indicate project entities
    PROJECT_KEYWORDS = {
        "project", "program", "initiative", "scheme",
        "plan", "proposal", "development",
    }
    
    def __init__(
        self,
        min_confidence: float = 0.7,
        strict_mode: bool = True,
    ):
        """Initialize validator.
        
        Args:
            min_confidence: Minimum confidence to accept a candidate
            strict_mode: If True, reject on any semantic mismatch
        """
        self.min_confidence = min_confidence
        self.strict_mode = strict_mode

    def validate_candidate(
        self,
        candidate_id: str,
        candidate_name: str,
        candidate_description: str = "",
        candidate_metadata: Optional[Dict[str, Any]] = None,
        requested_entity: str = "",
        entity_type: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        supporting_evidence: Optional[List[str]] = None,
    ) -> CandidateValidation:
        """Validate a candidate entity against the requested entity.
        
        Args:
            candidate_id: Wikidata ID or other identifier (e.g., "Q1761087")
            candidate_name: Candidate name (e.g., "Zera")
            candidate_description: Candidate description from Wikidata
            candidate_metadata: Additional metadata from Wikidata
            requested_entity: The entity name being researched
            entity_type: Optional expected entity type
            context: Optional context dict with additional info
            supporting_evidence: Optional list of evidence URLs/snippets
            
        Returns:
            CandidateValidation with status and details
        """
        validation = CandidateValidation(
            candidate_id=candidate_id,
            candidate_name=candidate_name,
            candidate_description=candidate_description,
            candidate_metadata=candidate_metadata or {},
        )
        
        # Extract information from requested entity
        requested_lower = requested_entity.lower()
        requested_base = self._remove_acronym(requested_entity)
        requested_acronym = self._extract_acronym(requested_entity)
        
        # Extract information from candidate
        candidate_lower = candidate_name.lower()
        candidate_base = self._remove_acronym(candidate_name)
        candidate_acronym = self._extract_acronym(candidate_name)
        
        # Collect matching and non-matching terms
        matching_terms: Set[str] = set()
        non_matching_terms: Set[str] = set()
        
        # Check 1: Exact name match (with or without acronym)
        if self._exact_match(requested_entity, candidate_name):
            validation.confidence = 1.0
            validation.status = CandidateStatus.ACCEPTED
            validation.rejection_reason = None
            validation.rejection_details = "Exact name match"
            return validation
        
        # Check 2: Acronym match
        if requested_acronym and candidate_acronym:
            if requested_acronym == candidate_acronym:
                matching_terms.add(f"acronym:{requested_acronym}")
                validation.confidence += 0.3
        
        # Check 3: Base name match (without acronym)
        if requested_base and candidate_base:
            if self._exact_match(requested_base, candidate_base):
                matching_terms.add(f"base_name:{requested_base}")
                validation.confidence += 0.4
            elif self._fuzzy_match(requested_base, candidate_base):
                matching_terms.add(f"fuzzy_base:{requested_base}")
                validation.confidence += 0.2
        
        # Check 4: Semantic compatibility
        semantic_score, semantic_terms = self._check_semantic_compatibility(
            requested_entity, requested_lower, candidate_name, candidate_lower,
            candidate_description, candidate_metadata, entity_type, context
        )
        validation.confidence += semantic_score * 0.3
        matching_terms.update(t for t in semantic_terms if t.startswith("match:"))
        non_matching_terms.update(t for t in semantic_terms if t.startswith("mismatch:"))
        
        # Check 5: Metadata compatibility
        metadata_score, metadata_terms = self._check_metadata_compatibility(
            candidate_metadata, entity_type, context
        )
        validation.confidence += metadata_score * 0.2
        matching_terms.update(t for t in metadata_terms if t.startswith("match:"))
        non_matching_terms.update(t for t in metadata_terms if t.startswith("mismatch:"))
        
        # Check 6: Type compatibility
        type_score, type_terms = self._check_type_compatibility(
            candidate_metadata, entity_type
        )
        validation.confidence += type_score * 0.2
        matching_terms.update(t for t in type_terms if t.startswith("match:"))
        non_matching_terms.update(t for t in type_terms if t.startswith("mismatch:"))
        
        validation.matching_terms = sorted(matching_terms)
        validation.non_matching_terms = sorted(non_matching_terms)
        
        # Determine status based on confidence and checks
        if validation.confidence >= self.min_confidence:
            validation.status = CandidateStatus.ACCEPTED
        elif validation.confidence >= 0.3:
            validation.status = CandidateStatus.AMBIGUOUS
        else:
            validation.status = CandidateStatus.REJECTED
        
        # Override: If we found critical semantic mismatches, REJECT regardless of score
        if non_matching_terms:
            for term in non_matching_terms:
                if "mismatch:semantic" in term or "mismatch:type" in term:
                    validation.status = CandidateStatus.REJECTED
                    validation.rejection_reason = RejectionReason.SEMANTIC_MISMATCH
                    validation.rejection_details = f"Semantic mismatch: {term}"
                    break
        
        # Set rejection reason if rejected
        if validation.status == CandidateStatus.REJECTED:
            if not validation.rejection_reason:
                validation.rejection_reason = RejectionReason.SEMANTIC_MISMATCH
                validation.rejection_details = "Candidate does not match requested entity"
        
        # Add supporting evidence
        if supporting_evidence:
            validation.supporting_evidence = list(supporting_evidence)
        
        return validation

    def _exact_match(self, a: str, b: str) -> bool:
        """Check for exact match (case-insensitive, ignoring punctuation)."""
        a_clean = re.sub(r"[^a-z0-9]+", "", a.lower())
        b_clean = re.sub(r"[^a-z0-9]+", "", b.lower())
        return a_clean == b_clean

    def _fuzzy_match(self, a: str, b: str, threshold: float = 0.8) -> bool:
        """Check for fuzzy match using simple ratio."""
        from difflib import SequenceMatcher
        a_clean = a.lower().strip()
        b_clean = b.lower().strip()
        if not a_clean or not b_clean:
            return False
        return SequenceMatcher(None, a_clean, b_clean).ratio() >= threshold

    def _check_semantic_compatibility(
        self,
        requested_entity: str,
        requested_lower: str,
        candidate_name: str,
        candidate_lower: str,
        candidate_description: str,
        candidate_metadata: Optional[Dict[str, Any]],
        entity_type: Optional[str],
        context: Optional[Dict[str, Any]],
    ) -> Tuple[float, List[str]]:
        """Check semantic compatibility between requested and candidate entities.
        
        Returns:
            Tuple of (score 0-1, list of term descriptions)
        """
        score = 0.0
        terms: List[str] = []
        
        # Combine all text for analysis
        requested_text = f"{requested_entity} {requested_lower}"
        candidate_text = f"{candidate_name} {candidate_lower} {candidate_description.lower()}"
        
        # Check for biological keywords in candidate (indicates mismatch for orgs)
        if entity_type and "organization" in entity_type.lower():
            for keyword in self.BIOLOGICAL_KEYWORDS:
                if keyword in candidate_text:
                    terms.append(f"mismatch:semantic_biological_{keyword}")
                    score -= 0.5  # Strong penalty for biological mismatch
        
        # Check for organization keywords in requested
        for keyword in self.ORGANIZATION_KEYWORDS:
            if keyword in requested_text:
                terms.append(f"match:requested_org_{keyword}")
                score += 0.1
        
        # Check for organization keywords in candidate
        for keyword in self.ORGANIZATION_KEYWORDS:
            if keyword in candidate_text:
                terms.append(f"match:candidate_org_{keyword}")
                score += 0.1
        
        # Check for location keywords
        for keyword in self.LOCATION_KEYWORDS:
            if keyword in requested_text and keyword in candidate_text:
                terms.append(f"match:location_{keyword}")
                score += 0.1
        
        # Check country compatibility from context
        if context and isinstance(context, dict):
            country = context.get("country", "")
            if country:
                country_lower = country.lower()
                if country_lower in requested_text:
                    terms.append(f"match:requested_country_{country_lower}")
                    score += 0.2
                if country_lower in candidate_text:
                    terms.append(f"match:candidate_country_{country_lower}")
                    score += 0.2
        
        # Check for explicit mismatch patterns
        # Example: "Zera" genus of insects vs "Zimbabwe Energy Regulatory Authority"
        if "insect" in candidate_text and "energy" in requested_text:
            terms.append("mismatch:semantic_insect_vs_energy")
            score -= 0.5
        
        if "genus" in candidate_text and "authority" in requested_text:
            terms.append("mismatch:semantic_genus_vs_authority")
            score -= 0.5
        
        # Normalize score to 0-1
        score = max(0.0, min(1.0, score))
        return score, terms

    def _check_metadata_compatibility(
        self,
        candidate_metadata: Optional[Dict[str, Any]],
        entity_type: Optional[str],
        context: Optional[Dict[str, Any]],
    ) -> Tuple[float, List[str]]:
        """Check if candidate metadata is compatible with expected entity.
        
        Returns:
            Tuple of (score 0-1, list of term descriptions)
        """
        score = 0.0
        terms: List[str] = []
        
        if not candidate_metadata:
            return 0.0, terms
        
        # Check country metadata
        if context and isinstance(context, dict):
            expected_country = context.get("country", "")
            if expected_country:
                candidate_country = candidate_metadata.get("country") or \
                                  candidate_metadata.get("country_id")
                if candidate_country:
                    if expected_country.lower() in str(candidate_country).lower():
                        terms.append(f"match:country_{expected_country}")
                        score += 0.5
                    else:
                        terms.append(f"mismatch:country_expected_{expected_country}_got_{candidate_country}")
                        score -= 0.3
        
        # Check instance_of (P31) for organization type
        instance_of = candidate_metadata.get("instance_of") or \
                     candidate_metadata.get("instance_of_ids")
        if instance_of:
            # Check if it's an organization
            instance_str = str(instance_of).lower()
            if "organization" in instance_str or "agency" in instance_str:
                terms.append("match:instance_organization")
                score += 0.3
            elif "genus" in instance_str or "taxon" in instance_str:
                terms.append("mismatch:instance_genus")
                score -= 0.5
        
        # Check official website domain
        official_website = candidate_metadata.get("official_website", "")
        if official_website:
            # Check if website matches expected patterns
            if context and isinstance(context, dict):
                expected_domains = context.get("expected_domains", [])
                for domain in expected_domains:
                    if domain in official_website:
                        terms.append(f"match:website_domain_{domain}")
                        score += 0.3
        
        score = max(0.0, min(1.0, score))
        return score, terms

    def _check_type_compatibility(
        self,
        candidate_metadata: Optional[Dict[str, Any]],
        entity_type: Optional[str],
    ) -> Tuple[float, List[str]]:
        """Check if candidate type is compatible with expected entity type.
        
        Returns:
            Tuple of (score 0-1, list of term descriptions)
        """
        score = 0.0
        terms: List[str] = []
        
        if not entity_type:
            return 0.5, terms  # Neutral score if no expected type
        
        expected_type_lower = entity_type.lower()
        
        # Check instance_of (P31) in metadata
        instance_of = candidate_metadata.get("instance_of") if candidate_metadata else None
        if instance_of:
            instance_str = str(instance_of).lower()
            if expected_type_lower in instance_str or instance_str in expected_type_lower:
                terms.append(f"match:type_{expected_type_lower}")
                score += 0.5
            else:
                terms.append(f"mismatch:type_expected_{expected_type_lower}_got_{instance_str}")
                score -= 0.5
        
        score = max(0.0, min(1.0, score))
        return score, terms

    @staticmethod
    def _extract_acronym(name: str) -> Optional[str]:
        """Extract acronym from parentheses at end of name."""
        match = re.search(r"\s*\(([A-Z]{2,10})\s*$", name.strip())
        if match:
            return match.group(1).strip()
        return None

    @staticmethod
    def _remove_acronym(name: str) -> str:
        """Remove acronym in parentheses from end of name."""
        return re.sub(r"\s*\([^)]+\)\s*$", "", name.strip())

    def resolve_entity(
        self,
        requested_entity: str,
        candidates: List[Dict[str, Any]],
        entity_type: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        supporting_evidence: Optional[List[str]] = None,
    ) -> EntityResolution:
        """Resolve entity by validating all candidates and determining the best match.
        
        Args:
            requested_entity: The entity name being researched
            candidates: List of candidate dicts with id, name, description, metadata
            entity_type: Optional expected entity type
            context: Optional context dict
            supporting_evidence: Optional list of evidence URLs/snippets
            
        Returns:
            EntityResolution with validated candidates and resolution status
        """
        resolution = EntityResolution(
            requested_entity=requested_entity,
            status="UNRESOLVED",
        )
        
        if supporting_evidence:
            resolution.evidence_sources = list(supporting_evidence)
        
        # Validate each candidate
        for candidate in candidates:
            candidate_id = candidate.get("id", "") or candidate.get("entity_id", "")
            candidate_name = candidate.get("name", "") or candidate.get("title", "")
            candidate_description = candidate.get("description", "") or \
                                  candidate.get("snippet", "")
            candidate_metadata = candidate.get("metadata", {})
            
            validation = self.validate_candidate(
                candidate_id=candidate_id,
                candidate_name=candidate_name,
                candidate_description=candidate_description,
                candidate_metadata=candidate_metadata,
                requested_entity=requested_entity,
                entity_type=entity_type,
                context=context,
                supporting_evidence=supporting_evidence,
            )
            
            resolution.candidates.append(validation)
            
            if validation.status == CandidateStatus.ACCEPTED:
                resolution.accepted_candidates.append(validation)
            elif validation.status == CandidateStatus.REJECTED:
                resolution.rejected_candidates.append(validation)
            else:
                resolution.ambiguous_candidates.append(validation)
        
        # Determine resolution status
        if resolution.accepted_candidates:
            # Use the highest confidence accepted candidate
            best_candidate = max(
                resolution.accepted_candidates,
                key=lambda c: c.confidence
            )
            resolution.resolved_entity = best_candidate.candidate_name
            resolution.resolved_entity_id = best_candidate.candidate_id
            resolution.status = "RESOLVED"
        elif resolution.ambiguous_candidates:
            resolution.status = "AMBIGUOUS"
        else:
            resolution.status = "UNRESOLVED"
        
        # Special case: If all candidates are rejected, status is REJECTED
        if resolution.candidates and not resolution.accepted_candidates and not resolution.ambiguous_candidates:
            resolution.status = "REJECTED"
        
        return resolution
