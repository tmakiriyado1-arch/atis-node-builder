"""
Entity Resolution Logic.

Resolves textual variants to canonical entities using:
1. Deterministic normalization
2. Exact matching
3. Fuzzy/semantic matching (secondary)
4. Contextual clues
"""
from typing import Optional, List, Tuple
from difflib import SequenceMatcher
from app.services.entity_resolution.normalizer import Normalizer
from app.services.entity_resolution.registry import (
    EntityRegistry,
    ResolutionResult,
    ResolutionState,
    CanonicalEntity,
)


class EntityResolver:
    """Resolve entity name variants to canonical entities."""

    def __init__(
        self,
        registry: EntityRegistry,
        fuzzy_threshold: float = 0.85,
    ):
        """Initialize resolver.
        
        Args:
            registry: Entity registry to resolve against
            fuzzy_threshold: Minimum similarity for fuzzy matches (0-1)
        """
        self.registry = registry
        self.normalizer = Normalizer()
        self.fuzzy_threshold = fuzzy_threshold

    def resolve(
        self,
        text: str,
        entity_type: Optional[str] = None,
        context: Optional[str] = None,
    ) -> ResolutionResult:
        """Resolve entity name to canonical entity.
        
        Attempts resolution in this order:
        1. Exact normalized match
        2. Acronym match
        3. Split name/acronym and retry
        4. Fuzzy matching
        5. Return NEW_ENTITY if no match
        
        Args:
            text: Text to resolve
            entity_type: Optional entity type hint
            context: Optional context for disambiguation
            
        Returns:
            ResolutionResult with decision state and candidates
        """
        if not text or not isinstance(text, str):
            return ResolutionResult(
                state=ResolutionState.NEW_ENTITY,
                reasoning="Empty or invalid input",
            )

        # Step 1: Normalize and try exact match
        normalized = self.normalizer.normalize(text)
        entity_id = self.registry.find_by_normalized(normalized)

        if entity_id:
            entity = self.registry.get_entity(entity_id)
            return ResolutionResult(
                state=ResolutionState.RESOLVED,
                entity_id=entity_id,
                canonical_name=entity.canonical_name if entity else None,
                confidence=1.0,
                reasoning="Exact normalized match",
            )

        # Step 2: Try acronym matching
        acronym = self.normalizer.extract_acronym(text)
        if acronym:
            entity_ids = self.registry.find_by_acronym(acronym)
            if entity_ids and len(entity_ids) == 1:
                entity_id = list(entity_ids)[0]
                entity = self.registry.get_entity(entity_id)
                return ResolutionResult(
                    state=ResolutionState.RESOLVED,
                    entity_id=entity_id,
                    canonical_name=entity.canonical_name if entity else None,
                    confidence=0.95,
                    reasoning=f"Resolved via acronym: {acronym}",
                )
            elif entity_ids and len(entity_ids) > 1:
                # Ambiguous acronym
                candidates = [
                    (eid, 0.9) for eid in entity_ids
                ]
                return ResolutionResult(
                    state=ResolutionState.AMBIGUOUS,
                    candidates=candidates,
                    reasoning=f"Acronym {acronym} matches {len(entity_ids)} entities",
                )

        # Step 3: Try splitting name and acronym
        name, acro = self.normalizer.split_name_and_acronym(text)
        if name and name != normalized:
            # Retry with just the name part
            entity_id = self.registry.find_by_normalized(name)
            if entity_id:
                entity = self.registry.get_entity(entity_id)
                return ResolutionResult(
                    state=ResolutionState.RESOLVED,
                    entity_id=entity_id,
                    canonical_name=entity.canonical_name if entity else None,
                    confidence=0.9,
                    reasoning="Resolved via extracted name component",
                )

        # Step 4: Fuzzy matching
        fuzzy_candidates = self._fuzzy_match(normalized)
        if fuzzy_candidates:
            if len(fuzzy_candidates) == 1 and fuzzy_candidates[0][1] >= self.fuzzy_threshold:
                # Strong single match
                entity_id, confidence = fuzzy_candidates[0]
                entity = self.registry.get_entity(entity_id)
                return ResolutionResult(
                    state=ResolutionState.RESOLVED,
                    entity_id=entity_id,
                    canonical_name=entity.canonical_name if entity else None,
                    confidence=confidence,
                    reasoning="Fuzzy match",
                )
            else:
                # Multiple candidates or low confidence
                return ResolutionResult(
                    state=ResolutionState.POSSIBLE_MATCH,
                    candidates=fuzzy_candidates[:3],  # Top 3 candidates
                    confidence=fuzzy_candidates[0][1] if fuzzy_candidates else 0,
                    reasoning="Possible fuzzy matches found",
                )

        # Step 5: No match found
        return ResolutionResult(
            state=ResolutionState.NEW_ENTITY,
            confidence=0.0,
            reasoning="No matching entity found",
        )

    def _fuzzy_match(self, normalized: str) -> List[Tuple[str, float]]:
        """Find similar entities using fuzzy matching.
        
        Args:
            normalized: Normalized text to match
            
        Returns:
            List of (entity_id, confidence) tuples sorted by confidence
        """
        candidates = []
        normalized_lower = normalized.lower()
        
        # For matching purposes, also normalize the query more aggressively
        normalized_matching = self.normalizer.normalize_for_matching(normalized)

        for entity in self.registry.list_all():
            # Compare against canonical name
            canonical_score = SequenceMatcher(
                None,
                normalized_matching,
                self.normalizer.normalize_for_matching(entity.canonical_name),
            ).ratio()

            best_score = canonical_score

            # Also check aliases
            for alias in entity.aliases:
                alias_score = SequenceMatcher(
                    None,
                    normalized_matching,
                    self.normalizer.normalize_for_matching(alias.normalized),
                ).ratio()
                best_score = max(best_score, alias_score)

            if best_score >= self.fuzzy_threshold:
                candidates.append((entity.entity_id, best_score))

        # Sort by confidence descending
        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates
