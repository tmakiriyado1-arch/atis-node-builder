"""
Canonical Entity Registry.

Maintains the authoritative list of entities, their canonical forms,
aliases, and resolution metadata.
"""
from typing import Optional, Set, Dict, List, Tuple
from dataclasses import dataclass, field
from enum import Enum
import uuid
from datetime import datetime
from app.services.entity_resolution.normalizer import Normalizer


class ResolutionState(str, Enum):
    """Entity resolution decision state."""
    RESOLVED = "RESOLVED"
    POSSIBLE_MATCH = "POSSIBLE_MATCH"
    NEW_ENTITY = "NEW_ENTITY"
    AMBIGUOUS = "AMBIGUOUS"
    CONFLICT = "CONFLICT"


@dataclass
class EntityAlias:
    """Alternative name for an entity."""
    text: str  # Original text variant
    normalized: str  # Normalized form
    source: str  # Where this alias came from
    discovered_at: datetime = field(default_factory=datetime.now)
    confidence: float = 1.0  # Confidence this is a valid alias


@dataclass
class CanonicalEntity:
    """Authoritative entity record."""
    entity_id: str  # Stable canonical ID (e.g., ENTITY-000001)
    canonical_name: str  # Authoritative name
    entity_type: Optional[str] = None  # e.g., "organization", "government_entity"
    aliases: List[EntityAlias] = field(default_factory=list)
    acronyms: List[str] = field(default_factory=list)
    raw_variants: Set[str] = field(default_factory=set)
    resolution_confidence: float = 1.0
    notes: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def add_alias(self, text: str, normalized: str, source: str, confidence: float = 1.0):
        """Register an alias for this entity.
        
        Args:
            text: Original text variant
            normalized: Normalized form
            source: Where this was discovered
            confidence: Confidence level (0-1)
        """
        alias = EntityAlias(text, normalized, source, confidence=confidence)
        self.aliases.append(alias)
        self.raw_variants.add(text)
        self.updated_at = datetime.now()

    def add_acronym(self, acronym: str):
        """Register an acronym for this entity.
        
        Args:
            acronym: Acronym text
        """
        if acronym and acronym.upper() not in self.acronyms:
            self.acronyms.append(acronym.upper())
            self.updated_at = datetime.now()

    def matches_normalized(self, normalized: str) -> bool:
        """Check if entity matches a normalized form.
        
        Args:
            normalized: Normalized text to check
            
        Returns:
            True if this entity matches the normalized form
        """
        # Check canonical name
        if self.canonical_name.lower() == normalized.lower():
            return True
        # Check aliases
        for alias in self.aliases:
            if alias.normalized.lower() == normalized.lower():
                return True
        return False


@dataclass
class ResolutionResult:
    """Result of an entity resolution attempt."""
    state: ResolutionState
    entity_id: Optional[str] = None  # Resolved entity ID if found
    canonical_name: Optional[str] = None  # Canonical name if resolved
    confidence: float = 0.0  # Confidence of resolution (0-1)
    candidates: List[Tuple[str, float]] = field(default_factory=list)  # (entity_id, confidence) tuples
    reasoning: str = ""  # Explanation of resolution decision


class EntityRegistry:
    """In-memory canonical entity registry.
    
    TODO: Migrate to persistent storage (PostgreSQL).
    """

    def __init__(self):
        """Initialize empty registry."""
        self.entities: Dict[str, CanonicalEntity] = {}  # entity_id -> CanonicalEntity
        self.normalized_index: Dict[str, str] = {}  # normalized_name -> entity_id
        self.acronym_index: Dict[str, Set[str]] = {}  # acronym -> set of entity_ids
        self.next_id = 1
        self.normalizer = Normalizer()

    def create_entity(
        self,
        canonical_name: str,
        entity_type: Optional[str] = None,
        acronyms: Optional[List[str]] = None,
        notes: str = "",
    ) -> CanonicalEntity:
        """Create new canonical entity.
        
        Args:
            canonical_name: Authoritative entity name
            entity_type: Type of entity
            acronyms: Associated acronyms
            notes: Additional notes
            
        Returns:
            New CanonicalEntity
        """
        normalized_name = self.normalizer.normalize(canonical_name)
        existing_id = self.normalized_index.get(normalized_name)
        if existing_id:
            return self.entities[existing_id]

        entity_id = f"ENTITY-{self.next_id:06d}"
        self.next_id += 1

        entity = CanonicalEntity(
            entity_id=entity_id,
            canonical_name=canonical_name,
            entity_type=entity_type,
            acronyms=[acronym.upper() for acronym in (acronyms or []) if acronym],
            notes=notes,
        )

        self.register_entity(entity)
        return entity

    def register_entity(self, entity: CanonicalEntity):
        """Register entity in all indices.
        
        Args:
            entity: Entity to register
        """
        self.entities[entity.entity_id] = entity
        
        # Index canonical name
        normalized_name = self.normalizer.normalize(entity.canonical_name)
        self.normalized_index[normalized_name] = entity.entity_id
        
        # Index all aliases
        for alias in entity.aliases:
            self.normalized_index[self.normalizer.normalize(alias.normalized)] = entity.entity_id
        
        # Index acronyms
        for acronym in entity.acronyms:
            normalized_acronym = acronym.upper()
            if normalized_acronym not in self.acronym_index:
                self.acronym_index[normalized_acronym] = set()
            self.acronym_index[normalized_acronym].add(entity.entity_id)

    def get_entity(self, entity_id: str) -> Optional[CanonicalEntity]:
        """Retrieve entity by ID.
        
        Args:
            entity_id: Entity ID to retrieve
            
        Returns:
            CanonicalEntity or None
        """
        return self.entities.get(entity_id)

    def find_by_normalized(self, normalized: str) -> Optional[str]:
        """Find entity ID by normalized name.
        
        Args:
            normalized: Normalized text to search for
            
        Returns:
            Entity ID if found, else None
        """
        return self.normalized_index.get(self.normalizer.normalize(normalized))

    def find_by_acronym(self, acronym: str) -> Optional[Set[str]]:
        """Find entity IDs by acronym.
        
        Args:
            acronym: Acronym to search for
            
        Returns:
            Set of entity IDs or None
        """
        return self.acronym_index.get(acronym.upper())

    def add_alias_to_entity(
        self,
        entity_id: str,
        text: str,
        normalized: str,
        source: str,
        confidence: float = 1.0,
    ) -> bool:
        """Add alias to existing entity.
        
        Args:
            entity_id: Entity to add alias to
            text: Original text
            normalized: Normalized form
            source: Where discovered
            confidence: Confidence level
            
        Returns:
            True if successful
        """
        entity = self.get_entity(entity_id)
        if not entity:
            return False
        
        entity.add_alias(text, normalized, source, confidence)
        self.normalized_index[self.normalizer.normalize(normalized)] = entity_id
        return True

    def add_acronym_to_entity(self, entity_id: str, acronym: str) -> bool:
        """Add acronym to existing entity.
        
        Args:
            entity_id: Entity to add acronym to
            acronym: Acronym text
            
        Returns:
            True if successful
        """
        entity = self.get_entity(entity_id)
        if not entity:
            return False
        
        entity.add_acronym(acronym)
        normalized_acronym = acronym.upper()
        if normalized_acronym not in self.acronym_index:
            self.acronym_index[normalized_acronym] = set()
        self.acronym_index[normalized_acronym].add(entity_id)
        return True

    def list_all(self) -> List[CanonicalEntity]:
        """List all registered entities.
        
        Returns:
            List of all CanonicalEntity objects
        """
        return list(self.entities.values())

    def count(self) -> int:
        """Count registered entities.
        
        Returns:
            Number of entities
        """
        return len(self.entities)
