"""ATIS Ontology: Classification paths, metadata fields, and controlled vocabularies.

This module provides the canonical ontology consumed by classification and row-building services.
It defines the authoritative classification paths, metadata fields, entity types,
relationship predicates, association predicates, and sector/country taxonomies.

The ontology is designed to be the single source of truth for:
- Classification categories and their routing logic
- Metadata field definitions and valid values
- Entity type taxonomies
- Relationship and association predicate vocabularies
- Geographic and sector classifications
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, FrozenSet, List, Optional, Set, Tuple


# =============================================================================
# Classification Categories
# =============================================================================

class ClaimCategory(str, Enum):
    """Deterministic routing categories for a research claim."""

    SUMMARY = "SUMMARY"
    RELATIONSHIP = "RELATIONSHIP"
    ASSOCIATION = "ASSOCIATION"
    METADATA = "METADATA"
    SOURCE = "SOURCE"
    UNCLASSIFIED = "UNCLASSIFIED"


# =============================================================================
# Metadata Fields
# =============================================================================

class MetadataField(str, Enum):
    """Canonical metadata field names for ATIS nodes."""

    ENTITY_TYPE = "entity_type"
    SUBTYPE = "subtype"
    COUNTRY = "country"
    SECTOR = "sector"
    STATUS = "status"


# =============================================================================
# Entity Types
# =============================================================================

# Organization types
ORGANIZATION_TYPES: FrozenSet[str] = frozenset([
    # Government and public sector
    "government agency",
    "government body",
    "public authority",
    "state-owned enterprise",
    "regulatory authority",
    "ministry",
    "department",
    "bureau",
    "office",
    "commission",
    "council",
    "committee",
    "board",
    # International and regional
    "international organization",
    "regional organization",
    "development bank",
    "multilateral institution",
    # Private sector
    "private company",
    "non-profit",
    "organization",
    "authority",
    "agency",
    "company",
    "institution",
    "corporation",
    "enterprise",
    "firm",
    "utility",
    "station",
    "plant",
    # Collective structures
    "consortium",
    "alliance",
    "pool",
    "cooperation",
    "cooperative",
    "network",
    "association",
    "foundation",
    "institute",
    "center",
    "service",
    "program",
    "initiative",
    "project",
    "task force",
    "working group",
])

# Concept types
CONCEPT_TYPES: FrozenSet[str] = frozenset([
    "concept",
    "economic policy approach",
    "policy approach",
    "ideological framework",
    "economic framework",
    "political concept",
    "strategy",
    "approach",
    "methodology",
    "framework",
    "doctrine",
    "principle",
    "theory",
])

# Concept subtype mapping: descriptive text -> canonical subtype
CONCEPT_SUBTYPE_MAPPING: FrozenSet[Tuple[str, Optional[str]]] = frozenset([
    ("economic policy approach", "economic_policy"),
    ("policy approach", "policy"),
    ("ideological framework", "ideological_framework"),
    ("economic framework", "economic_framework"),
    ("political concept", "political_concept"),
    ("concept", None),
])

# Document types
DOCUMENT_TYPES: FrozenSet[str] = frozenset([
    "document",
    "memorandum of understanding",
    "mou",
    "agreement",
    "treaty",
    "contract",
    "report",
    "white paper",
    "policy document",
    "legislation",
    "regulation",
    "directive",
])

# All valid entity types
ALL_ENTITY_TYPES: FrozenSet[str] = ORGANIZATION_TYPES | CONCEPT_TYPES | DOCUMENT_TYPES


# =============================================================================
# Relationship Predicates
# =============================================================================

RELATIONSHIP_PREDICATES: FrozenSet[str] = frozenset([
    "regulates",
    "manages",
    "oversees",
    "supports",
    "supported_by",
    "operates",
    "provides",
    "governs",
    "controls",
    "establishes",
    "requires",
    "enforces",
    "includes",
    "covers",
    "monitors",
    "administers",
    "coordinates",
    "maintains",
    "owns",
    "leads",
    "founded_in",  # PHASE 13: Use founded_in instead of founded to avoid "In" being extracted
    "created",
    "funds",
    "licenses",
    "authorizes",
    "approved",
    "signed",
    "built",
    "develops",
    "implements",
    "executes",
    "advises",
    "consults",
    "represents",
    "participates",
    "collaborates",
    "partners",
    "has",
])


# =============================================================================
# Association Predicates
# =============================================================================

ASSOCIATION_PREDICATES: FrozenSet[str] = frozenset([
    "connected_to",
    "relevant_to",
    "related_to",
    "associated_with",
    "linked_to",
    "relevant to",
    "connected to",
    "associated with",
    "affiliated_with",
    "partnered_with",
    "collaborates_with",
    "works_with",
    "member_of",
    "part_of",
])


# =============================================================================
# Metadata Keywords
# =============================================================================

# Keywords that trigger entity_type metadata extraction
ENTITY_TYPE_KEYWORDS: FrozenSet[str] = ORGANIZATION_TYPES | CONCEPT_TYPES | DOCUMENT_TYPES

# Keywords that trigger country/location metadata extraction
COUNTRY_KEYWORDS: FrozenSet[str] = frozenset([
    "located in",
    "based in",
    "situated in",
    "operates in",
    "headquartered in",
    "registered in",
    "incorporated in",
    "in africa",
    "southern africa",
    "sadc",
    "southern african development community",
    "eastern africa",
    "western africa",
    "north africa",
])

# African countries and regions
AFRICAN_REGIONS: FrozenSet[str] = frozenset([
    "southern africa",
    "sadc",
    "southern african development community",
    "eastern africa",
    "western africa",
    "north africa",
    "africa",
])

AFRICAN_COUNTRIES: FrozenSet[str] = frozenset([
    "zimbabwe",
    "south africa",
    "mozambique",
    "kenya",
    "nigeria",
    "ghana",
    "uganda",
    "tanzania",
    "zambia",
    "malawi",
    "botswana",
    "namibia",
    "angola",
])

ALL_COUNTRIES: FrozenSet[str] = AFRICAN_REGIONS | AFRICAN_COUNTRIES

# Keywords that trigger sector metadata extraction
SECTOR_KEYWORDS: FrozenSet[str] = frozenset([
    "energy sector",
    "power sector",
    "electricity sector",
    "water sector",
    "transport sector",
    "telecommunications sector",
    "mining sector",
    "agriculture sector",
    "technology sector",
    "financial sector",
    "health sector",
    "education sector",
    "infrastructure",
    "energy",
    "power",
    "electricity",
    "renewable energy",
    "sustainable energy",
])

# Valid sector values
SECTOR_VALUES: FrozenSet[str] = frozenset([
    "Energy Sector",
    "Power Sector",
    "Electricity Sector",
    "Water Sector",
    "Transport Sector",
    "Telecommunications Sector",
    "Mining Sector",
    "Agriculture Sector",
    "Technology Sector",
    "Financial Sector",
    "Health Sector",
    "Education Sector",
    "Infrastructure",
    "Energy",
    "Power",
    "Electricity",
    "Renewable Energy",
    "Sustainable Energy",
])

# Keywords that trigger status metadata extraction
STATUS_KEYWORDS: FrozenSet[str] = frozenset([
    "active",
    "inactive",
    "proposed",
    "approved",
    "operational",
    "closed",
    "pending",
    "draft",
    "published",
    "implemented",
    "established",
    "founded",
    "launched",
    "running",
    "functional",
])

# Valid status values
STATUS_VALUES: FrozenSet[str] = frozenset([
    "active",
    "inactive",
    "proposed",
    "approved",
    "operational",
    "closed",
    "pending",
    "draft",
    "published",
    "implemented",
    "established",
    "founded",
    "launched",
    "running",
    "functional",
])


# =============================================================================
# Summary Patterns
# =============================================================================

SUMMARY_PATTERNS: FrozenSet[str] = frozenset([
    "is used in",
    "used in",
    "generates",
    "produces",
    "supplies",
    "powers",
    "operates",
    "functions",
    "delivers",
    "supports",
    "responsible for",
    "facilitates",
    "enables",
    "provides",
    "is designed to",
    "aims to",
    "seeks to",
    "works to",
    "strives to",
    "helps",
    "promotes",
    "encourages",
    "coordinates",
    "manages",
    "oversees",
])

# Patterns that indicate sector/industry regulation (should be summary, not relationship)
SECTOR_REGULATION_PATTERNS: FrozenSet[str] = frozenset([
    "sector",
    "industry",
    "market",
    "activity",
    "supply chain",
    "system",
    "policy",
    "licensing",
])


# =============================================================================
# Descriptive Verbs
# =============================================================================

DESCRIPTIVE_VERBS: FrozenSet[str] = frozenset([
    "is",
    "are",
    "was",
    "were",
    "be",
    "being",
    "been",
    "has",
    "have",
    "had",
    "having",
    "was founded",
    "was established",
    "was created",
    "functions",
    "operates",
    "works",
    "provides",
    "supports",
    "coordinates",
    "manages",
    "oversees",
    "creates",
    "maintains",
    "develops",
    "facilitates",
])


# =============================================================================
# Ontology Dataclass
# =============================================================================

@dataclass(frozen=True)
class ATISOntology:
    """Frozen ontology container providing all classification paths and vocabularies.
    
    This class serves as the single access point for all ontology data.
    It is immutable (frozen) to ensure consistency across the application.
    """
    
    # Classification categories
    claim_categories: FrozenSet[ClaimCategory] = field(default_factory=lambda: frozenset(ClaimCategory))
    
    # Metadata fields
    metadata_fields: FrozenSet[MetadataField] = field(default_factory=lambda: frozenset(MetadataField))
    
    # Entity types
    organization_types: FrozenSet[str] = ORGANIZATION_TYPES
    concept_types: FrozenSet[str] = CONCEPT_TYPES
    document_types: FrozenSet[str] = DOCUMENT_TYPES
    all_entity_types: FrozenSet[str] = ALL_ENTITY_TYPES
    concept_subtype_mapping: Dict[str, Optional[str]] = field(default_factory=lambda: dict(CONCEPT_SUBTYPE_MAPPING))
    
    # Subtypes for ontology prompt - derived from organization_types and concept_subtype_mapping
    # These are computed properties for convenience in enrichment prompts
    @property
    def organization_subtypes(self) -> FrozenSet[str]:
        """Get organization subtypes (same as organization_types for now)."""
        return self.organization_types
    
    @property
    def concept_subtypes(self) -> FrozenSet[str]:
        """Get concept subtypes from the mapping values."""
        # Extract non-None values from concept_subtype_mapping
        subtypes = {v for v in self.concept_subtype_mapping.values() if v is not None}
        return frozenset(subtypes)
    
    # Predicates
    relationship_predicates: FrozenSet[str] = RELATIONSHIP_PREDICATES
    association_predicates: FrozenSet[str] = ASSOCIATION_PREDICATES
    
    # Metadata keywords
    entity_type_keywords: FrozenSet[str] = ENTITY_TYPE_KEYWORDS
    country_keywords: FrozenSet[str] = COUNTRY_KEYWORDS
    sector_keywords: FrozenSet[str] = SECTOR_KEYWORDS
    status_keywords: FrozenSet[str] = STATUS_KEYWORDS
    
    # Valid values
    countries: FrozenSet[str] = ALL_COUNTRIES
    sectors: FrozenSet[str] = SECTOR_VALUES
    statuses: FrozenSet[str] = STATUS_VALUES
    
    # Patterns
    summary_patterns: FrozenSet[str] = SUMMARY_PATTERNS
    sector_regulation_patterns: FrozenSet[str] = SECTOR_REGULATION_PATTERNS
    descriptive_verbs: FrozenSet[str] = DESCRIPTIVE_VERBS
    
    def get_entity_type_keywords(self) -> FrozenSet[str]:
        """Get all entity type keywords."""
        return self.all_entity_types
    
    def get_concept_subtype(self, concept_description: str) -> Optional[str]:
        """Get the canonical subtype for a concept description.
        
        Args:
            concept_description: The concept description to look up
            
        Returns:
            The canonical subtype if found, else None
        """
        return self.concept_subtype_mapping.get(concept_description.lower(), None)
    
    def is_relationship_predicate(self, predicate: str) -> bool:
        """Check if a predicate is a relationship predicate.
        
        Args:
            predicate: The predicate to check
            
        Returns:
            True if it's a relationship predicate
        """
        return predicate.lower() in self.relationship_predicates
    
    def is_association_predicate(self, predicate: str) -> bool:
        """Check if a predicate is an association predicate.
        
        Args:
            predicate: The predicate to check
            
        Returns:
            True if it's an association predicate
        """
        return predicate.lower() in self.association_predicates
    
    def is_metadata_keyword(self, keyword: str, field: Optional[str] = None) -> bool:
        """Check if a keyword triggers metadata extraction.
        
        Args:
            keyword: The keyword to check
            field: Optional specific field to check against
            
        Returns:
            True if the keyword triggers metadata extraction
        """
        if field == MetadataField.ENTITY_TYPE.value:
            return keyword.lower() in self.entity_type_keywords
        elif field == MetadataField.COUNTRY.value:
            return keyword.lower() in self.country_keywords
        elif field == MetadataField.SECTOR.value:
            return keyword.lower() in self.sector_keywords
        elif field == MetadataField.STATUS.value:
            return keyword.lower() in self.status_keywords
        return keyword.lower() in (self.entity_type_keywords | self.country_keywords | self.sector_keywords | self.status_keywords)
    
    def get_metadata_field_for_keyword(self, keyword: str) -> Optional[MetadataField]:
        """Get the metadata field that a keyword belongs to.
        
        Args:
            keyword: The keyword to check
            
        Returns:
            The MetadataField if the keyword belongs to a field, else None
        """
        lower_keyword = keyword.lower()
        
        if lower_keyword in self.entity_type_keywords:
            return MetadataField.ENTITY_TYPE
        elif lower_keyword in self.country_keywords:
            return MetadataField.COUNTRY
        elif lower_keyword in self.sector_keywords:
            return MetadataField.SECTOR
        elif lower_keyword in self.status_keywords:
            return MetadataField.STATUS
        
        return None


# =============================================================================
# Module-level singleton
# =============================================================================

# Create the canonical ontology instance
ontology = ATISOntology()


def get_ontology() -> ATISOntology:
    """Get the canonical ontology instance.
    
    Returns:
        The singleton ATISOntology instance
    """
    return ontology
