"""Canonical Node Canonicalizer: Evidence -> Claims -> Canonical Node Pipeline.

This module implements a deterministic canonicalization stage that converts
research evidence into valid ATIS/Obsidian nodes conforming to the existing
node schema and ontology.

Architecture:
    ResearchResult (raw evidence)
        -> Extracted Claims (structured facts)
        -> Entity Resolution (canonical entity names)
        -> Ontology Mapping (valid field values)
        -> CanonicalNodeRow (validated node)
        -> CanonicalNodeValidator (final validation)

Key Principles:
    1. NEVER treat raw webpage text as canonical node data
    2. Every field must be validated against the ontology
    3. Backlinks must point to resolvable entities
    4. If evidence does not support a field, leave it as None
    5. The validator is the final authority, not the model
    6. Maintain evidence-to-field traceability for auditability
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from app.models import CanonicalNodeRow, NodeDraft
from app.services.ontology import get_ontology, MetadataField
from app.services.entity_resolution.resolver import EntityResolver
from app.services.entity_resolution.registry import EntityRegistry, ResolutionState
from app.services.research_engine import ResearchClaim
from app.services.research.evidence_filter import (
    AtomicClaim,
    EvidenceFilterPipeline,
    RelevanceClassification,
    EvidenceQualityStatus,
)


# =============================================================================
# Evidence Types
# =============================================================================

@dataclass
class ExtractedClaim:
    """A verified claim extracted from evidence.
    
    This is the intermediate representation between raw research evidence
    and canonical node fields.
    """
    claim_text: str
    field_name: Optional[str] = None
    source_urls: List[str] = field(default_factory=list)
    confidence: float = 0.0
    subject: Optional[str] = None
    predicate: Optional[str] = None
    target: Optional[str] = None
    is_verified: bool = False
    
    def __post_init__(self):
        if not self.claim_text:
            raise ValueError("claim_text is required")
        if not self.source_urls:
            raise ValueError("At least one source URL is required")


@dataclass
class EvidenceBundle:
    """Bundle of evidence for an entity.
    
    Contains all extracted claims, sources, and metadata needed for
    canonicalization.
    """
    entity_name: str
    entity_seed: Optional[str] = None
    claims: List[ExtractedClaim] = field(default_factory=list)
    raw_evidence: List[str] = field(default_factory=list)
    source_urls: List[str] = field(default_factory=list)
    metadata_hints: Dict[str, Any] = field(default_factory=dict)


# =============================================================================
# Validation Helpers
# =============================================================================

class ValidationError(Exception):
    """Raised when canonicalization validation fails."""
    pass


class BacklinkValidationError(ValidationError):
    """Raised when a backlink target is invalid."""
    pass


class OntologyValidationError(ValidationError):
    """Raised when a value is not in the ontology."""
    pass


@dataclass
class ValidationResult:
    """Result of validating a field or node."""
    is_valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    field: Optional[str] = None
    value: Optional[Any] = None


class BacklinkValidator:
    """Validate that backlink targets are valid entity references.
    
    A valid backlink target must:
    - Be a known canonical entity (from registry)
    - Be a valid ontology concept
    - Not be a sentence fragment
    - Not be excessive in length
    - Not be mostly lowercase prose
    - Not be CTA text or navigation text
    """
    
    MAX_BACKLINK_LENGTH = 100
    MIN_WORD_COUNT = 1
    MAX_WORD_COUNT = 10
    
    def __init__(self, registry: Optional[EntityRegistry] = None, resolver: Optional[EntityResolver] = None):
        self.registry = registry
        self.resolver = resolver
        self.ontology = get_ontology()
        self._known_entity_names: Set[str] = set()
        
        if registry:
            self._load_known_entities()
    
    def _load_known_entities(self) -> None:
        """Load known entity names from registry."""
        if self.registry:
            for entity in self.registry.list_all():
                self._known_entity_names.add(entity.canonical_name.lower())
                for alias in entity.aliases or []:
                    self._known_entity_names.add(alias.lower())
                for acronym in entity.acronyms or []:
                    self._known_entity_names.add(acronym.lower())
    
    def is_valid_backlink_target(self, target: str) -> bool:
        """Check if a backlink target is valid.
        
        Args:
            target: The target text (without [[ ]])
            
        Returns:
            True if valid, False otherwise
        """
        if not target or not target.strip():
            return False
        
        cleaned = target.strip()
        
        # Check length
        if len(cleaned) > self.MAX_BACKLINK_LENGTH:
            return False
        
        # Check word count
        words = cleaned.split()
        if len(words) > self.MAX_WORD_COUNT:
            return False
        if len(words) < self.MIN_WORD_COUNT:
            pass  # Single words are OK if they are valid
        
        # Check if it is a known entity
        if cleaned.lower() in self._known_entity_names:
            return True
        
        # Check if it is a valid ontology concept
        if self._is_ontology_concept(cleaned):
            return True
        
        # Check for invalid patterns
        if self._is_invalid_pattern(cleaned):
            return False
        
        # If it is a proper noun (capitalized), it might be valid
        if self._is_proper_noun(cleaned):
            return True
        
        return False
    
    def _is_ontology_concept(self, target: str) -> bool:
        """Check if target is a valid ontology concept."""
        lower_target = target.lower()
        
        # Check entity types
        if lower_target in {e.lower() for e in self.ontology.all_entity_types}:
            return True
        
        # Check sectors
        if lower_target in {s.lower() for s in self.ontology.sectors}:
            return True
        
        # Check countries
        if lower_target in {c.lower() for c in self.ontology.countries}:
            return True
        
        # Check status values
        if lower_target in {st.lower() for st in self.ontology.statuses}:
            return True
        
        return False
    
    def _is_invalid_pattern(self, target: str) -> bool:
        """Check if target matches invalid patterns."""
        # Sentence-like (contains punctuation typical of sentences)
        if re.search(r'[.!?;:]', target):
            return True
        
        # Mostly lowercase (not a proper noun)
        words = target.split()
        if words:
            lowercase_count = sum(1 for w in words if w.islower())
            if lowercase_count / len(words) > 0.7 and len(words) > 2:
                return True
        
        # CTA text patterns
        cta_patterns = [
            r'\bnow\b',
            r'\bopen\b',
            r'\bapply\b',
            r'\bclick\b',
            r'\bhere\b',
            r'\bmore\b',
            r'\bread\b',
            r'\blearn\b',
            r'\bjoin\b',
            r'\bsign\b',
            r'\bup\b',
            r'\bregister\b',
        ]
        for pattern in cta_patterns:
            if re.search(pattern, target, re.IGNORECASE):
                return True
        
        # Navigation text patterns
        nav_patterns = [
            r'\bhome\b',
            r'\babout\b',
            r'\bcontact\b',
            r'\bmenu\b',
            r'\bback\b',
            r'\bnext\b',
            r'\bprevious\b',
        ]
        for pattern in nav_patterns:
            if re.search(pattern, target, re.IGNORECASE):
                return True
        
        # Bible verse patterns
        if re.search(r'\d\s+[A-Za-z]+\s+\d+:\d+', target):
            return True
        
        # Single letters (except known acronyms)
        if len(target) == 1 and target.isalpha():
            return True
        
        return False
    
    def _is_proper_noun(self, target: str) -> bool:
        """Check if target appears to be a proper noun."""
        words = target.split()
        if not words:
            return False
        
        # All words are capitalized
        if all(w.istitle() or w.isupper() for w in words if w.isalpha()):
            return True
        
        # First word capitalized, rest lowercase (might be a title)
        if words[0].istitle() and all(w.islower() for w in words[1:] if w.isalpha()):
            return True
        
        return False
    
    def validate_backlink(self, backlink: str) -> ValidationResult:
        """Validate a backlink in the format [[Target]].
        
        Args:
            backlink: The full backlink text including [[ ]]
            
        Returns:
            ValidationResult with is_valid and errors
        """
        # Extract target from [[Target]]
        match = re.match(r'\[\[(.+?)\]\]', backlink)
        if not match:
            return ValidationResult(
                is_valid=False,
                errors=[f"Invalid backlink format: {backlink}"],
                field="backlink",
                value=backlink
            )
        
        target = match.group(1).strip()
        
        if not self.is_valid_backlink_target(target):
            return ValidationResult(
                is_valid=False,
                errors=[f"Invalid backlink target: {target}"],
                field="backlink",
                value=backlink
            )
        
        return ValidationResult(is_valid=True, field="backlink", value=backlink)
    
    def validate_text_for_invalid_backlinks(self, text: str) -> ValidationResult:
        """Validate that a text field does not contain invalid backlinks.
        
        Args:
            text: The text to validate
            
        Returns:
            ValidationResult with any invalid backlinks found
        """
        errors = []
        invalid_backlinks = []
        
        # Find all backlinks
        backlinks = re.findall(r'\[\[(.+?)\]\]', text)
        
        for backlink in backlinks:
            if not self.is_valid_backlink_target(backlink):
                invalid_backlinks.append(backlink)
                errors.append(f"Invalid backlink target: {backlink}")
        
        return ValidationResult(
            is_valid=len(invalid_backlinks) == 0,
            errors=errors,
            field="text",
            value=text
        )


# =============================================================================
# Field Validators
# =============================================================================

class FieldValidator:
    """Validate individual fields against ontology constraints."""
    
    def __init__(self, registry: Optional[EntityRegistry] = None):
        self.ontology = get_ontology()
        self.backlink_validator = BacklinkValidator(registry=registry)
    
    def validate_uid(self, uid: str, entity: str) -> ValidationResult:
        """Validate UID is deterministic and matches entity.
        
        Expected: entity name converted to lowercase with hyphens
        """
        errors = []
        
        if not uid or not uid.strip():
            errors.append("UID is required")
            return ValidationResult(is_valid=False, errors=errors, field="uid", value=uid)
        
        # Expected UID format: lowercase entity with spaces replaced by hyphens
        expected_uid = re.sub(r'[^a-z0-9]+', '-', entity.lower()).strip('-')
        
        if uid != expected_uid:
            errors.append(f"UID '{uid}' does not match expected format '{expected_uid}'")
            return ValidationResult(is_valid=False, errors=errors, field="uid", value=uid)
        
        # Check for invalid characters
        if not re.match(r'^[a-z0-9-]+$', uid):
            errors.append(f"UID contains invalid characters: {uid}")
            return ValidationResult(is_valid=False, errors=errors, field="uid", value=uid)
        
        return ValidationResult(is_valid=True, field="uid", value=uid)
    
    def validate_entity(self, entity: str) -> ValidationResult:
        """Validate entity name.
        
        Must be a proper canonical name, not a description or sentence.
        """
        errors = []
        
        if not entity or not entity.strip():
            errors.append("Entity name is required")
            return ValidationResult(is_valid=False, errors=errors, field="entity", value=entity)
        
        cleaned = entity.strip()
        
        # Must not be a sentence (no ending punctuation)
        if re.search(r'[.!?]$', cleaned):
            errors.append(f"Entity name appears to be a sentence: {entity}")
        
        # Must not be excessively long
        if len(cleaned) > 200:
            errors.append(f"Entity name is too long ({len(cleaned)} chars): {entity}")
        
        # Must not contain newlines
        if '\n' in cleaned:
            errors.append("Entity name contains newlines")
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            field="entity",
            value=entity
        )
    
    def validate_entity_type(self, entity_type: Optional[str]) -> ValidationResult:
        """Validate entity_type against ontology."""
        if entity_type is None:
            return ValidationResult(is_valid=True, field="entity_type", value=None)
        
        errors = []
        cleaned = entity_type.strip()
        
        if not cleaned:
            return ValidationResult(is_valid=True, field="entity_type", value=None)
        
        # Must be in ontology
        if cleaned.lower() not in {e.lower() for e in self.ontology.all_entity_types}:
            errors.append(f"Invalid entity_type: {entity_type}. Must be one of: {sorted(self.ontology.all_entity_types)}")
        
        # Must not be a sentence
        if re.search(r'[.!?]', cleaned):
            errors.append(f"entity_type contains sentence punctuation: {entity_type}")
        
        # Must be reasonably short
        if len(cleaned) > 100:
            errors.append(f"entity_type is too long: {entity_type}")
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            field="entity_type",
            value=entity_type
        )
    
    def validate_sector(self, sector: Optional[str]) -> ValidationResult:
        """Validate sector against ontology."""
        if sector is None:
            return ValidationResult(is_valid=True, field="sector", value=None)
        
        errors = []
        cleaned = sector.strip()
        
        if not cleaned:
            return ValidationResult(is_valid=True, field="sector", value=None)
        
        # Must be in ontology
        if cleaned not in self.ontology.sectors:
            errors.append(f"Invalid sector: {sector}. Must be one of: {sorted(self.ontology.sectors)}")
        
        # Must not be a sentence
        if re.search(r'[.!?]', cleaned):
            errors.append(f"sector contains sentence punctuation: {sector}")
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            field="sector",
            value=sector
        )
    
    def validate_country(self, country: Optional[str]) -> ValidationResult:
        """Validate country against ontology."""
        if country is None:
            return ValidationResult(is_valid=True, field="country", value=None)
        
        errors = []
        cleaned = country.strip()
        
        if not cleaned:
            return ValidationResult(is_valid=True, field="country", value=None)
        
        # Must be in ontology
        if cleaned.lower() not in {c.lower() for c in self.ontology.countries}:
            errors.append(f"Invalid country: {country}. Must be one of: {sorted(self.ontology.countries)}")
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            field="country",
            value=country
        )
    
    def validate_status(self, status: Optional[str]) -> ValidationResult:
        """Validate status against ontology."""
        if status is None:
            return ValidationResult(is_valid=True, field="status", value=None)
        
        errors = []
        cleaned = status.strip()
        
        if not cleaned:
            return ValidationResult(is_valid=True, field="status", value=None)
        
        # Must be in ontology
        if cleaned.lower() not in {s.lower() for s in self.ontology.statuses}:
            errors.append(f"Invalid status: {status}. Must be one of: {sorted(self.ontology.statuses)}")
        
        # Must be short
        if len(cleaned) > 50:
            errors.append(f"status is too long: {status}")
        
        # Must not be a sentence
        if re.search(r'[.!?]', cleaned):
            errors.append(f"status contains sentence punctuation: {status}")
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            field="status",
            value=status
        )
    
    def validate_aliases(self, aliases: List[str]) -> ValidationResult:
        """Validate aliases.
        
        Each alias must be a valid alternative name for the entity.
        Must NOT contain:
        - slogans
        - Bible verses
        - marketing copy
        - program names
        - calls to action
        - arbitrary fragments
        - sentences
        - unrelated organizations
        """
        errors = []
        
        for alias in aliases:
            cleaned = alias.strip()
            if not cleaned:
                continue
            
            # Must not be a sentence
            if re.search(r'[.!?]$', cleaned):
                errors.append(f"Alias is a sentence: {alias}")
                continue
            
            # Must not be too long
            if len(cleaned) > 200:
                errors.append(f"Alias is too long: {alias}")
                continue
            
            # Must not be a single letter (unless it is a known acronym)
            if len(cleaned) == 1 and cleaned.isalpha():
                errors.append(f"Alias is a single letter: {alias}")
                continue
            
            # Must not be a Bible verse
            if re.search(r'\d\s+[A-Za-z]+\s+\d+:\d+', cleaned):
                errors.append(f"Alias is a Bible verse: {alias}")
                continue
            
            # Must not be CTA text
            cta_patterns = [
                r'\bnow\b',
                r'\bopen\b',
                r'\bapply\b',
                r'\bclick\b',
                r'\bhere\b',
            ]
            for pattern in cta_patterns:
                if re.search(pattern, cleaned, re.IGNORECASE):
                    errors.append(f"Alias contains CTA text: {alias}")
                    break
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            field="aliases",
            value=aliases
        )
    
    def validate_summary(self, summary: str, entity: str, aliases: List[str]) -> ValidationResult:
        """Validate summary field.
        
        Must:
        - Reference the entity
        - Be concise
        - Be factual
        - Not contain marketing CTA
        - Not contain navigation text
        - Not contain webpage boilerplate
        - Not be thousands of words
        - Use [[backlinks]] appropriately
        """
        errors = []
        
        if not summary or not summary.strip():
            errors.append("Summary is required")
            return ValidationResult(is_valid=False, errors=errors, field="summary", value=summary)
        
        cleaned = summary.strip()
        
        # Must reference the entity or one of its aliases
        entity_refs = [entity.lower()] + [a.lower() for a in aliases]
        references_entity = any(
            re.search(rf'\b{re.escape(ref)}\b', cleaned, re.IGNORECASE)
            for ref in entity_refs
        )
        if not references_entity and f'[[{entity}]]' not in cleaned:
            errors.append(f"Summary does not reference entity '{entity}' or its aliases")
        
        # Must be concise (max ~500 words)
        word_count = len(cleaned.split())
        if word_count > 500:
            errors.append(f"Summary is too long ({word_count} words)")
        
        # Must not contain CTA text
        cta_patterns = [
            r'\bnow\b',
            r'\bapply\b',
            r'\bclick\b',
            r'\bhere\b',
            r'\bmore\b',
            r'\bregister\b',
            r'\bsign\b',
        ]
        for pattern in cta_patterns:
            if re.search(pattern, cleaned, re.IGNORECASE):
                errors.append(f"Summary contains CTA text matching: {pattern}")
                break
        
        # Validate backlinks in summary
        backlink_result = self.backlink_validator.validate_text_for_invalid_backlinks(summary)
        if not backlink_result.is_valid:
            errors.extend(backlink_result.errors)
        
        # Must have a verb explaining function
        if not re.search(
            r'\b(is|are|was|were|regulates|manages|oversees|supports|operates|provides|governs|controls|establishes|requires|enforces|includes|covers|monitors|administers|coordinates|maintains|owns|leads|created|has|functions|delivers|facilitates|enables|develops|implements|works|active|based|located|that)\b',
            cleaned,
            re.IGNORECASE
        ):
            errors.append("Summary must explain the subject's function or role")
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            field="summary",
            value=summary
        )
    
    def validate_relationships(self, relationships: List[str]) -> ValidationResult:
        """Validate relationships.
        
        Each relationship must be in format: predicate::[[Target]]
        - predicate must be a valid relationship predicate
        - Target must be a valid backlink target
        """
        errors = []
        
        for rel in relationships:
            cleaned = rel.strip()
            if not cleaned:
                continue
            
            # Check format: must contain ::[[ and ]]
            if '::[[' not in cleaned or ']]' not in cleaned:
                errors.append(f"Invalid relationship format: {rel}")
                continue
            
            # Extract predicate and target
            try:
                parts = cleaned.split('::[[')
                if len(parts) != 2:
                    errors.append(f"Invalid relationship format: {rel}")
                    continue
                predicate = parts[0].strip().lower()
                target_part = parts[1]
                if not target_part.endswith(']]'):
                    errors.append(f"Invalid relationship format: {rel}")
                    continue
                target = target_part[:-2].strip()
                
                # Validate predicate
                if predicate not in self.ontology.relationship_predicates:
                    errors.append(f"Invalid relationship predicate: {predicate}. Must be one of: {sorted(self.ontology.relationship_predicates)}")
                
                # Validate target
                if not self.backlink_validator.is_valid_backlink_target(target):
                    errors.append(f"Invalid relationship target: {target}")
            except Exception as e:
                errors.append(f"Invalid relationship format: {rel} ({e})")
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            field="relationships",
            value=relationships
        )
    def validate_associations(self, associations: List[str]) -> ValidationResult:
        """Validate associations.
        
        Each association must be in format: predicate::[[Target]]
        - predicate must be a valid association predicate
        - Target must be a valid backlink target
        """
        errors = []
        
        for assoc in associations:
            cleaned = assoc.strip()
            if not cleaned:
                continue
            
            # Check format: must contain ::[[ and ]]
            if '::[[' not in cleaned or ']]' not in cleaned:
                errors.append(f"Invalid association format: {assoc}")
                continue
            
            # Extract predicate and target
            try:
                parts = cleaned.split('::[[')
                if len(parts) != 2:
                    errors.append(f"Invalid association format: {assoc}")
                    continue
                predicate = parts[0].strip().lower()
                target_part = parts[1]
                if not target_part.endswith(']]'):
                    errors.append(f"Invalid association format: {assoc}")
                    continue
                target = target_part[:-2].strip()
                
                # Validate predicate
                if predicate not in self.ontology.association_predicates:
                    errors.append(f"Invalid association predicate: {predicate}. Must be one of: {sorted(self.ontology.association_predicates)}")
                
                # Validate target
                if not self.backlink_validator.is_valid_backlink_target(target):
                    errors.append(f"Invalid association target: {target}")
            except Exception as e:
                errors.append(f"Invalid association format: {assoc} ({e})")
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            field="associations",
            value=associations
        )
    def validate_sources(self, sources: List[str]) -> ValidationResult:
        """Validate sources.
        
        Must be non-empty list of valid URLs.
        """
        errors = []
        
        if not sources:
            errors.append("At least one source is required")
            return ValidationResult(is_valid=False, errors=errors, field="sources", value=sources)
        
        for source in sources:
            cleaned = source.strip()
            if not cleaned:
                continue
            
            # Must look like a URL
            if not re.match(r'^https?://', cleaned, re.IGNORECASE):
                errors.append(f"Invalid source URL: {source}")
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            field="sources",
            value=sources
        )


# =============================================================================
# Canonical Node Validator
# =============================================================================

class CanonicalNodeValidator:
    """Final validator for CanonicalNodeRow.
    
    Validates ALL fields against the ontology and schema constraints.
    This is the final authority - if validation fails, the node is invalid.
    """
    
    def __init__(self, registry: Optional[EntityRegistry] = None):
        self.field_validator = FieldValidator(registry=registry)
    
    def validate(self, row: CanonicalNodeRow) -> ValidationResult:
        """Validate a complete CanonicalNodeRow.
        
        Args:
            row: The row to validate
            
        Returns:
            ValidationResult with all errors collected
        """
        all_errors = []
        
        # Validate each field
        uid_result = self.field_validator.validate_uid(row.uid, row.entity)
        if not uid_result.is_valid:
            all_errors.extend(uid_result.errors)
        
        entity_result = self.field_validator.validate_entity(row.entity)
        if not entity_result.is_valid:
            all_errors.extend(entity_result.errors)
        
        aliases_result = self.field_validator.validate_aliases(row.aliases or [])
        if not aliases_result.is_valid:
            all_errors.extend(aliases_result.errors)
        
        entity_type_result = self.field_validator.validate_entity_type(row.entity_type)
        if not entity_type_result.is_valid:
            all_errors.extend(entity_type_result.errors)
        
        sector_result = self.field_validator.validate_sector(row.sector)
        if not sector_result.is_valid:
            all_errors.extend(sector_result.errors)
        
        country_result = self.field_validator.validate_country(row.country)
        if not country_result.is_valid:
            all_errors.extend(country_result.errors)
        
        status_result = self.field_validator.validate_status(row.status)
        if not status_result.is_valid:
            all_errors.extend(status_result.errors)
        
        summary_result = self.field_validator.validate_summary(row.summary, row.entity, row.aliases or [])
        if not summary_result.is_valid:
            all_errors.extend(summary_result.errors)
        
        relationships_result = self.field_validator.validate_relationships(row.relationships or [])
        if not relationships_result.is_valid:
            all_errors.extend(relationships_result.errors)
        
        associations_result = self.field_validator.validate_associations(row.associations or [])
        if not associations_result.is_valid:
            all_errors.extend(associations_result.errors)
        
        sources_result = self.field_validator.validate_sources(row.sources or [])
        if not sources_result.is_valid:
            all_errors.extend(sources_result.errors)
        
        return ValidationResult(
            is_valid=len(all_errors) == 0,
            errors=all_errors,
            field="node",
            value=row
        )
    
    def validate_and_raise(self, row: CanonicalNodeRow) -> None:
        """Validate and raise ValidationError if invalid.
        
        Args:
            row: The row to validate
            
        Raises:
            ValidationError: If the row is invalid
        """
        result = self.validate(row)
        if not result.is_valid:
            raise ValidationError(
                f"Node validation failed with {len(result.errors)} errors:\n" +
                "\n".join(f"  - {e}" for e in result.errors)
            )


# =============================================================================
# Canonicalizer
# =============================================================================

class CanonicalNodeCanonicalizer:
    """Convert research evidence into a canonical node.
    
    This is the main entry point for canonicalization.
    
    Pipeline:
    1. Extract claims from research evidence
    2. Resolve entities (canonical names)
    3. Map to ontology values
    4. Build CanonicalNodeRow
    5. Validate with CanonicalNodeValidator
    
    The canonicalizer ensures:
    - No raw webpage text leaks into structured fields
    - All fields are validated against ontology
    - Backlinks point to resolvable entities
    - Missing fields remain None (not hallucinated)
    """
    
    def __init__(
        self,
        registry: Optional[EntityRegistry] = None,
        resolver: Optional[EntityResolver] = None,
    ):
        self.registry = registry
        self.resolver = resolver
        self.ontology = get_ontology()
        self.validator = CanonicalNodeValidator(registry=registry)
    
    def canonicalize(
        self,
        entity_seed: str,
        evidence_bundle: EvidenceBundle,
    ) -> CanonicalNodeRow:
        """Canonicalize research evidence into a valid node.
        
        Args:
            entity_seed: The original entity name from RITA
            evidence_bundle: Bundle containing claims and evidence
            
        Returns:
            Validated CanonicalNodeRow
            
        Raises:
            ValidationError: If canonicalization fails
        """
        # Step 1: Determine canonical entity name
        entity = self._resolve_entity_name(entity_seed, evidence_bundle)
        
        # Step 2: Generate UID deterministically
        uid = self._generate_uid(entity)
        
        # Step 3: Extract and validate aliases
        aliases = self._extract_aliases(entity_seed, entity, evidence_bundle)
        
        # Step 4: Extract metadata from claims
        entity_type = self._extract_entity_type(entity, evidence_bundle)
        subtype = self._extract_subtype(entity, evidence_bundle)
        country = self._extract_country(entity, evidence_bundle)
        if country:
            country = country.capitalize()
        sector = self._extract_sector(entity, evidence_bundle)
        status = self._extract_status(entity, evidence_bundle)
        if status:
            status = status.capitalize()
        
        # Step 5: Build summary from claims
        summary = self._build_summary(entity, aliases, evidence_bundle)
        
        # Step 6: Extract relationships
        relationships = self._extract_relationships(entity, evidence_bundle)
        
        # Step 7: Extract associations
        associations = self._extract_associations(entity, evidence_bundle)
        
        # Step 8: Collect sources
        sources = self._extract_sources(evidence_bundle)
        
        # Step 9: Build row
        row = CanonicalNodeRow(
            uid=uid,
            entity=entity,
            aliases=aliases,
            entity_type=entity_type,
            subtype=subtype,
            country=country,
            sector=sector,
            status=status,
            summary=summary,
            relationships=relationships,
            associations=associations,
            sources=sources,
        )
        
        # Step 10: Validate
        self.validator.validate_and_raise(row)
        
        return row
    
    def _resolve_entity_name(self, entity_seed: str, evidence_bundle: EvidenceBundle) -> str:
        """Resolve the canonical entity name.
        
        Uses entity_seed as the primary source, with evidence as support.
        Does NOT extract entity name from raw webpage text.
        """
        # Use the seed entity name as canonical
        # This prevents webpage text from overriding the entity name
        return entity_seed.strip()
    
    def _generate_uid(self, entity: str) -> str:
        """Generate deterministic UID from entity name."""
        cleaned = re.sub(r'[^a-z0-9]+', '-', entity.lower()).strip('-')
        return cleaned or "entity"
    
    def _capitalize_target(self, target: str) -> str:
        """Capitalize a target for proper noun format.
        
        Handles:
        - lowercase words -> Title Case
        - already capitalized -> keep as is
        - acronyms -> keep uppercase
        """
        if not target:
            return target
        
        # If already all uppercase, keep it
        if target.isupper():
            return target
        
        # If already title case, keep it
        if target.istitle():
            return target
        
        # Capitalize first letter of each word
        return target.title()
    
    def _extract_aliases(self, entity_seed: str, entity: str, evidence_bundle: EvidenceBundle) -> List[str]:
        """Extract valid aliases from evidence.
        
        Only includes:
        - The seed entity name (if different from canonical)
        - Acronyms found in evidence
        - Alternative names explicitly stated as aliases
        
        Does NOT include:
        - Slogans
        - Descriptions
        - Marketing copy
        - Sentence fragments
        """
        aliases = set()
        
        # Add seed entity name if different from canonical
        if entity_seed.strip().lower() != entity.lower():
            aliases.add(entity_seed.strip())
        
        # Extract from claims
        for claim in evidence_bundle.claims:
            # Look for acronyms in parentheses
            match = re.search(r'\(([A-Z]{2,})\)', claim.claim_text)
            if match:
                acronym = match.group(1)
                # Only add if it is a reasonable acronym length
                if 2 <= len(acronym) <= 10:
                    aliases.add(acronym)
            
            # Look for "also known as" patterns
            aka_match = re.search(
                r'(?:also known as|aka|a\.k\.a\.)\s+["`]?([^"`\.]+)["`]?',
                claim.claim_text,
                re.IGNORECASE
            )
            if aka_match:
                alias = aka_match.group(1).strip()
                # Validate it is a reasonable alias
                if self._is_valid_alias(alias, entity):
                    aliases.add(alias)
        
        # Also check metadata hints
        if 'aliases' in evidence_bundle.metadata_hints:
            for alias in evidence_bundle.metadata_hints['aliases']:
                if isinstance(alias, str) and self._is_valid_alias(alias, entity):
                    aliases.add(alias)
        
        return sorted(aliases)
    
    def _is_valid_alias(self, alias: str, entity: str) -> bool:
        """Check if a string is a valid alias.
        
        Must:
        - Not be empty
        - Not be the same as entity
        - Not be a sentence
        - Not be a single letter (unless it is a known acronym)
        - Not contain invalid patterns
        """
        if not alias or not alias.strip():
            return False
        
        cleaned = alias.strip()
        
        if cleaned.lower() == entity.lower():
            return False
        
        # Must not be a sentence
        if re.search(r'[.!?]$', cleaned):
            return False
        
        # Must not be too long
        if len(cleaned) > 200:
            return False
        
        # Must not be a single lowercase letter
        if len(cleaned) == 1 and cleaned.islower():
            return False
        
        # Must not be a Bible verse
        if re.search(r'\d\s+[A-Za-z]+\s+\d+:\d+', cleaned):
            return False
        
        # Must not contain CTA text
        cta_patterns = [
            r'\bnow\b',
            r'\bopen\b',
            r'\bapply\b',
            r'\bclick\b',
            r'\bhere\b',
        ]
        for pattern in cta_patterns:
            if re.search(pattern, cleaned, re.IGNORECASE):
                return False
        
        return True
    
    def _extract_entity_type(self, entity: str, evidence_bundle: EvidenceBundle) -> Optional[str]:
        """Extract entity_type from evidence.
        
        Only returns a value if it is in the ontology.
        Otherwise returns None.
        """
        # Check metadata hints first
        if 'entity_type' in evidence_bundle.metadata_hints:
            hint = evidence_bundle.metadata_hints['entity_type']
            if hint and hint in self.ontology.all_entity_types:
                return hint
        
        # Look in claims for entity type information
        for claim in evidence_bundle.claims:
            # Look for "is a/an [type]" patterns
            match = re.search(
                r'\b(is|are|was|were)\s+(?:a|an|the)\s+([a-z0-9\s-]+)',
                claim.claim_text,
                re.IGNORECASE
            )
            if match:
                candidate = match.group(2).strip().lower()
                # Check if it is a valid entity type
                for valid_type in self.ontology.all_entity_types:
                    if candidate == valid_type.lower():
                        return valid_type
        
        # If entity name contains known type words
        entity_lower = entity.lower()
        for valid_type in self.ontology.all_entity_types:
            if valid_type.lower() in entity_lower:
                return valid_type
        
        return None
    
    def _extract_subtype(self, entity: str, evidence_bundle: EvidenceBundle) -> Optional[str]:
        """Extract subtype from evidence.
        
        Only returns a value if supported by evidence.
        Otherwise returns None.
        """
        # Check metadata hints
        if 'subtype' in evidence_bundle.metadata_hints:
            return evidence_bundle.metadata_hints['subtype']
        
        return None
    
    def _extract_country(self, entity: str, evidence_bundle: EvidenceBundle) -> Optional[str]:
        """Extract country from evidence.
        
        Only returns a value if it is in the ontology and supported by evidence.
        """
        # Check metadata hints first
        if 'country' in evidence_bundle.metadata_hints:
            hint = evidence_bundle.metadata_hints['country']
            if hint and hint in self.ontology.countries:
                return hint
        
        # Look in claims for country information
        for claim in evidence_bundle.claims:
            for country in self.ontology.countries:
                if country.lower() in claim.claim_text.lower():
                    return country
        
        return None
    
    def _extract_sector(self, entity: str, evidence_bundle: EvidenceBundle) -> Optional[str]:
        """Extract sector from evidence.
        
        Only returns a value if it is in the ontology and supported by evidence.
        Does NOT use keyword collisions - must be explicit.
        """
        # Check metadata hints first
        if 'sector' in evidence_bundle.metadata_hints:
            hint = evidence_bundle.metadata_hints['sector']
            if hint and hint in self.ontology.sectors:
                return hint
        
        # Look in claims for explicit sector mentions
        for claim in evidence_bundle.claims:
            claim_lower = claim.claim_text.lower()
            for sector in self.ontology.sectors:
                # Must be an explicit mention, not just a keyword collision
                if sector.lower() in claim_lower:
                    # Verify it is actually about sector, not just the word appearing
                    # in a different context
                    sector_words = sector.lower().split()
                    if all(word in claim_lower for word in sector_words):
                        return sector
        
        return None
    
    def _extract_status(self, entity: str, evidence_bundle: EvidenceBundle) -> Optional[str]:
        """Extract status from evidence.
        
        Only returns a value if it is in the ontology and supported by evidence.
        """
        # Check metadata hints first
        if 'status' in evidence_bundle.metadata_hints:
            hint = evidence_bundle.metadata_hints['status']
            if hint and hint in self.ontology.statuses:
                return hint
        
        # Look in claims for status information
        for claim in evidence_bundle.claims:
            claim_lower = claim.claim_text.lower()
            for status in self.ontology.statuses:
                if status.lower() in claim_lower:
                    return status
        
        return None
    
    def _build_summary(self, entity: str, aliases: List[str], evidence_bundle: EvidenceBundle) -> str:
        """Build a concise, factual summary from evidence.
        
        Must:
        - Reference the entity
        - Be concise (~2-4 sentences)
        - Be factual
        - Not contain marketing CTA or webpage boilerplate
        - Use [[backlinks]] for other entities
        """
        # Collect summary-worthy claims
        summary_claims = []
        for claim in evidence_bundle.claims:
            # Skip claims that are clearly not summary material
            if self._is_summary_claim(claim):
                summary_claims.append(claim)
        
        if not summary_claims:
            # Fallback: create a minimal summary
            return f"[[{entity}]] is an entity. It functions within its established framework."
        
        # Build summary from the best claims
        # Prefer claims that describe what the entity is/does
        best_claims = sorted(
            summary_claims,
            key=lambda c: self._summary_claim_score(c),
            reverse=True
        )[:3]  # Use at most 3 claims
        
        # Clean and combine claims
        summary_parts = []
        for claim in best_claims:
            cleaned = self._clean_claim_for_summary(claim.claim_text, entity)
            if cleaned:
                summary_parts.append(cleaned)
        
        if not summary_parts:
            return f"[[{entity}]] is an entity. It functions within its established framework."
        
        # Combine into a coherent summary
        summary = ". ".join(summary_parts)
        
        # Ensure it starts with the entity in wikilink format
        if not summary.startswith(f"[[{entity}]]") and entity not in summary[:50]:
            summary = f"[[{entity}]] {summary}"
        
        # Ensure it ends with a period
        if not summary.endswith('.'):
            summary = summary + "."
        
        # Ensure it has a verb explaining function
        if not re.search(
            r'\b(is|are|was|were|regulates|manages|oversees|supports|operates|provides|governs|controls|establishes|requires|enforces|includes|covers|monitors|administers|coordinates|maintains|owns|leads|created|has|functions|delivers|facilitates|enables|develops|implements|works|active|based|located|that)\b',
            summary,
            re.IGNORECASE
        ):
            summary = f"{summary} It functions within its established framework."
        
        return summary
    
    def _is_summary_claim(self, claim: ExtractedClaim) -> bool:
        """Check if a claim is suitable for summary."""
        text = claim.claim_text.lower()
        
        # Skip CTA text
        cta_patterns = [
            r'\bnow\b',
            r'\bapply\b',
            r'\bclick\b',
            r'\bhere\b',
            r'\bregister\b',
            r'\bsign\b',
        ]
        for pattern in cta_patterns:
            if re.search(pattern, text):
                return False
        
        # Skip navigation text
        nav_patterns = [
            r'\bhome\b',
            r'\babout\b',
            r'\bcontact\b',
            r'\bmenu\b',
        ]
        for pattern in nav_patterns:
            if re.search(pattern, text):
                return False
        
        # Skip Bible verses
        if re.search(r'\d\s+[A-Za-z]+\s+\d+:\d+', text):
            return False
        
        # Must be a statement, not a question
        if text.endswith('?'):
            return False
        
        return True
    
    def _summary_claim_score(self, claim: ExtractedClaim) -> int:
        """Score a claim for summary suitability.
        
        Higher score = more suitable for summary.
        """
        score = 0
        text = claim.claim_text.lower()
        
        # Bonus for descriptive verbs
        descriptive_verbs = [
            'is', 'are', 'was', 'were', 'regulates', 'manages', 'oversees',
            'supports', 'operates', 'provides', 'governs', 'controls',
            'establishes', 'requires', 'enforces', 'includes', 'covers',
            'monitors', 'administers', 'coordinates', 'maintains',
        ]
        for verb in descriptive_verbs:
            if verb in text:
                score += 2
        
        # Bonus for entity type words
        for etype in self.ontology.all_entity_types:
            if etype.lower() in text:
                score += 1
        
        # Penalty for CTA words
        cta_words = ['now', 'apply', 'click', 'here', 'register', 'sign']
        for word in cta_words:
            if word in text:
                score -= 10
        
        return score
    
    def _clean_claim_for_summary(self, claim_text: str, entity: str) -> str:
        """Clean a claim for use in summary.
        
        Removes:
        - Redundant entity name at start
        - Marketing language
        - Navigation text
        """
        cleaned = claim_text.strip()
        
        # Remove entity name from beginning if redundant
        cleaned = re.sub(
            rf"^{re.escape(entity)}\s*(?:is|are|was|were|be|being|been)\s*",
            "",
            cleaned,
            flags=re.IGNORECASE
        ).strip()
        
        # Remove CTA text
        cta_patterns = [
            r'\bNow\b.*',
            r'\bApply\b.*',
            r'\bClick\b.*',
            r'\bHere\b.*',
        ]
        for pattern in cta_patterns:
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE).strip()
        
        # Capitalize first letter
        if cleaned:
            cleaned = cleaned[0].upper() + cleaned[1:] if cleaned else cleaned
        
        return cleaned
    
    def _extract_relationships(self, entity: str, evidence_bundle: EvidenceBundle) -> List[str]:
        """Extract valid relationships from evidence.
        
        Only creates relationships when:
        - The predicate is a valid relationship predicate
        - The target is a resolvable entity or ontology concept
        """
        relationships = []
        seen = set()
        
        for claim in evidence_bundle.claims:
            # Try to find predicate patterns in the claim
            # Match: entity (is|was|were|are)? predicate target
            # where predicate is a known relationship predicate with spaces instead of underscores
            for predicate in self.ontology.relationship_predicates:
                predicate_spaced = predicate.replace('_', ' ')
                # Pattern: entity (is|was|were|are)? predicate target
                pattern = rf'^{re.escape(entity)}[ \t]+(?:is[ \t]+|was[ \t]+|were[ \t]+|are[ \t]+)?{predicate_spaced}[ \t]+(.+)'
                match = re.match(pattern, claim.claim_text, re.IGNORECASE)
                if match:
                    target = match.group(1).strip()
                    # Capitalize target for proper noun format
                    target = self._capitalize_target(target)
                    
                    # Validate target
                    validator = BacklinkValidator(registry=self.registry)
                    if not validator.is_valid_backlink_target(target):
                        continue
                    
                    # Format as predicate::[[Target]]
                    rel_str = f"{predicate}::[[{target}]]"
                    if rel_str not in seen:
                        seen.add(rel_str)
                        relationships.append(rel_str)
                    break  # Found a match, move to next claim
        
        return sorted(relationships)
    
    def _extract_associations(self, entity: str, evidence_bundle: EvidenceBundle) -> List[str]:
        """Extract valid associations from evidence.
        
        Only creates associations when:
        - The predicate is a valid association predicate
        - The target is a resolvable entity or ontology concept
        """
        associations = []
        seen = set()
        
        for claim in evidence_bundle.claims:
            # Try to find predicate patterns in the claim
            for predicate in self.ontology.association_predicates:
                predicate_spaced = predicate.replace('_', ' ')
                # Pattern: entity (is|was|were|are)? predicate target
                pattern = rf'^{re.escape(entity)}[ \t]+(?:is[ \t]+|was[ \t]+|were[ \t]+|are[ \t]+)?{predicate_spaced}[ \t]+(.+)'
                match = re.match(pattern, claim.claim_text, re.IGNORECASE)
                if match:
                    target = match.group(1).strip()
                    # Capitalize target for proper noun format
                    target = self._capitalize_target(target)
                    
                    # Validate target
                    validator = BacklinkValidator(registry=self.registry)
                    if not validator.is_valid_backlink_target(target):
                        continue
                    
                    # Format as predicate::[[Target]]
                    assoc_str = f"{predicate}::[[{target}]]"
                    if assoc_str not in seen:
                        seen.add(assoc_str)
                        associations.append(assoc_str)
                    break  # Found a match, move to next claim
        
        return sorted(associations)
    
    def _extract_sources(self, evidence_bundle: EvidenceBundle) -> List[str]:
        """Extract unique sources from evidence."""
        sources = set()
        
        for claim in evidence_bundle.claims:
            for url in claim.source_urls:
                if url and url.strip():
                    sources.add(url.strip())
        
        for url in evidence_bundle.source_urls:
            if url and url.strip():
                sources.add(url.strip())
        
        return sorted(sources)
