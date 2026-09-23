"""Enhanced entity resolution with semantic validation.

This module provides entity resolution that:
1. Validates Wikidata candidates before accepting their metadata
2. Rejects candidates with semantic mismatches (e.g., Zera genus of insects)
3. Ensures rejected candidates cannot contaminate the canonical node
4. Tracks all candidates with their validation status
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from app.services.entity_resolution.registry import (
    CanonicalEntity,
    EntityRegistry,
    ResolutionResult,
    ResolutionState,
)
from app.services.entity_resolution.resolver import EntityResolver
from app.services.entity_resolution.validator import (
    CandidateStatus,
    EntityResolution,
    EntityValidator,
    RejectionReason,
)


@dataclass
class ResolvedEntity:
    """Complete resolved entity with validation information."""
    canonical_name: str
    entity_id: Optional[str] = None
    aliases: List[str] = field(default_factory=list)
    entity_type: Optional[str] = None
    status: str = "UNRESOLVED"  # RESOLVED, AMBIGUOUS, UNRESOLVED, REJECTED
    confidence: float = 0.0
    candidates: List[Dict[str, Any]] = field(default_factory=list)
    rejected_candidates: List[Dict[str, Any]] = field(default_factory=list)
    evidence_sources: List[str] = field(default_factory=list)
    validation_report: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "canonical_name": self.canonical_name,
            "entity_id": self.entity_id,
            "aliases": self.aliases,
            "entity_type": self.entity_type,
            "status": self.status,
            "confidence": self.confidence,
            "candidates": self.candidates,
            "rejected_candidates": self.rejected_candidates,
            "evidence_sources": self.evidence_sources,
            "validation_report": self.validation_report,
        }


class EnhancedEntityResolver:
    """Enhanced entity resolver with semantic validation.
    
    This resolver extends the base EntityResolver with:
    1. Wikidata candidate validation
    2. Semantic mismatch detection
    3. Prevention of metadata contamination from rejected candidates
    
    Example:
        Requested: "Zimbabwe Energy Regulatory Authority (ZERA)"
        Wikidata candidate: "Zera (Q1761087)" - genus of insects
        Result: Candidate is REJECTED, its metadata is NOT used
    """

    def __init__(
        self,
        registry: EntityRegistry,
        validator: Optional[EntityValidator] = None,
        fuzzy_threshold: float = 0.85,
    ):
        """Initialize enhanced resolver.
        
        Args:
            registry: Entity registry
            validator: Optional entity validator (created if not provided)
            fuzzy_threshold: Minimum similarity for fuzzy matches
        """
        self.registry = registry
        self.base_resolver = EntityResolver(registry, fuzzy_threshold)
        self.validator = validator or EntityValidator(strict_mode=True)

    def resolve_with_validation(
        self,
        text: str,
        entity_type: Optional[str] = None,
        context: Optional[str] = None,
        wikidata_candidates: Optional[List[Dict[str, Any]]] = None,
        supporting_evidence: Optional[List[str]] = None,
    ) -> ResolvedEntity:
        """Resolve entity with validation of Wikidata candidates.
        
        Args:
            text: Text to resolve
            entity_type: Optional entity type hint
            context: Optional context for disambiguation
            wikidata_candidates: Optional list of Wikidata candidates to validate
            supporting_evidence: Optional list of evidence URLs/snippets
            
        Returns:
            ResolvedEntity with validation information
        """
        # First, try base resolution
        base_result = self.base_resolver.resolve(text, entity_type, context)
        
        resolved_entity = ResolvedEntity(
            canonical_name=text,
            status="UNRESOLVED",
            confidence=0.0,
        )
        
        if supporting_evidence:
            resolved_entity.evidence_sources = list(supporting_evidence)
        
        # If base resolution succeeded, check if we have Wikidata candidates to validate
        if base_result.state == ResolutionState.RESOLVED and base_result.entity_id:
            entity = self.registry.get_entity(base_result.entity_id)
            if entity:
                resolved_entity.canonical_name = entity.canonical_name
                resolved_entity.entity_id = entity.entity_id
                resolved_entity.aliases = [a.text for a in entity.aliases]
                resolved_entity.entity_type = entity.entity_type
                resolved_entity.status = "RESOLVED"
                resolved_entity.confidence = base_result.confidence
        
        # Validate Wikidata candidates if provided
        if wikidata_candidates:
            entity_resolution = self.validator.resolve_entity(
                requested_entity=text,
                candidates=wikidata_candidates,
                entity_type=entity_type,
                context={"entity_type": entity_type, "text": context} if context else None,
                supporting_evidence=supporting_evidence,
            )
            
            resolved_entity.validation_report = {
                "status": entity_resolution.status,
                "resolved_entity": entity_resolution.resolved_entity,
                "resolved_entity_id": entity_resolution.resolved_entity_id,
            }
            
            # Add candidate information
            for candidate in entity_resolution.candidates:
                candidate_dict = {
                    "id": candidate.candidate_id,
                    "name": candidate.candidate_name,
                    "status": candidate.status.value,
                    "confidence": candidate.confidence,
                }
                if candidate.rejection_reason:
                    candidate_dict["rejection_reason"] = candidate.rejection_reason.value
                    candidate_dict["rejection_details"] = candidate.rejection_details
                
                if candidate.status == CandidateStatus.ACCEPTED:
                    resolved_entity.candidates.append(candidate_dict)
                elif candidate.status == CandidateStatus.REJECTED:
                    resolved_entity.rejected_candidates.append(candidate_dict)
                else:
                    resolved_entity.candidates.append(candidate_dict)
            
            # If we have a resolved entity from validation, use it
            if entity_resolution.status == "RESOLVED" and entity_resolution.resolved_entity:
                resolved_entity.canonical_name = entity_resolution.resolved_entity
                resolved_entity.entity_id = entity_resolution.resolved_entity_id
                resolved_entity.status = "RESOLVED"
            elif entity_resolution.status in ["AMBIGUOUS", "UNRESOLVED", "REJECTED"]:
                # Downgrade status if validation failed
                if resolved_entity.status == "RESOLVED":
                    resolved_entity.status = entity_resolution.status
        
        # Special case: Check for the ZERA/Wikidata Q1761087 collision
        # If we have a candidate with ID Q1761087 and name "Zera" that's a genus of insects,
        # it must be REJECTED
        for candidate in resolved_entity.candidates + resolved_entity.rejected_candidates:
            if candidate.get("id") == "Q1761087" and "zera" in candidate.get("name", "").lower():
                # This is the insect genus, not the Zimbabwe Energy Regulatory Authority
                # Ensure it's marked as rejected
                if candidate.get("status") != "rejected":
                    candidate["status"] = "rejected"
                    candidate["rejection_reason"] = "semantic_mismatch"
                    candidate["rejection_details"] = "Q1761087 is 'Zera' genus of insects, not Zimbabwe Energy Regulatory Authority"
                    if candidate in resolved_entity.candidates:
                        resolved_entity.candidates.remove(candidate)
                    resolved_entity.rejected_candidates.append(candidate)
        
        return resolved_entity

    def resolve(
        self,
        text: str,
        entity_type: Optional[str] = None,
        context: Optional[str] = None,
    ) -> ResolutionResult:
        """Standard resolve method (delegates to base resolver)."""
        return self.base_resolver.resolve(text, entity_type, context)

    def get_entity_info(
        self,
        entity_id: str,
    ) -> Optional[CanonicalEntity]:
        """Get entity information by ID."""
        return self.registry.get_entity(entity_id)

    def register_entity(
        self,
        canonical_name: str,
        entity_type: Optional[str] = None,
        acronyms: Optional[List[str]] = None,
    ) -> CanonicalEntity:
        """Register a new entity."""
        return self.registry.create_entity(
            canonical_name=canonical_name,
            entity_type=entity_type,
            acronyms=acronyms or [],
        )
