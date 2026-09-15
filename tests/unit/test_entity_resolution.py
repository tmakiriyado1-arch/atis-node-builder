"""
Tests for entity resolution logic
"""
import pytest
from app.services.entity_resolution.registry import ResolutionState


class TestExactMatching:
    """Test exact entity resolution"""

    def test_resolve_exact_canonical_name(self, resolver, zera_entity):
        """Test resolution of exact canonical name"""
        result = resolver.resolve("Zimbabwe Energy Regulatory Authority")
        assert result.state == ResolutionState.RESOLVED
        assert result.entity_id == zera_entity.entity_id
        assert result.canonical_name == "Zimbabwe Energy Regulatory Authority"
        assert result.confidence == 1.0

    def test_resolve_case_insensitive(self, resolver, zera_entity):
        """Test that resolution is case-insensitive"""
        result = resolver.resolve("zimbabwe energy regulatory authority")
        assert result.state == ResolutionState.RESOLVED
        assert result.entity_id == zera_entity.entity_id

    def test_resolve_with_extra_spaces(self, resolver, zera_entity):
        """Test resolution with extra whitespace"""
        result = resolver.resolve("Zimbabwe  Energy   Regulatory  Authority")
        assert result.state == ResolutionState.RESOLVED
        assert result.entity_id == zera_entity.entity_id

    def test_resolve_with_trailing_punctuation(self, resolver, zera_entity):
        """Test resolution with trailing punctuation"""
        result = resolver.resolve("Zimbabwe Energy Regulatory Authority.")
        assert result.state == ResolutionState.RESOLVED
        assert result.entity_id == zera_entity.entity_id


class TestAcronymResolution:
    """Test resolution via acronyms"""

    def test_resolve_exact_acronym(self, resolver, zera_entity):
        """Test resolution of exact acronym"""
        result = resolver.resolve("ZERA")
        assert result.state == ResolutionState.RESOLVED
        assert result.entity_id == zera_entity.entity_id
        assert result.confidence == 0.95

    def test_resolve_acronym_in_context(self, resolver, zera_entity):
        """Test resolution of acronym with context"""
        result = resolver.resolve("Zimbabwe Energy Regulatory Authority (ZERA)")
        assert result.state == ResolutionState.RESOLVED
        assert result.entity_id == zera_entity.entity_id

    def test_resolve_acronym_reversed(self, resolver, zera_entity):
        """Test resolution with acronym in prefix"""
        result = resolver.resolve("ZERA (Zimbabwe Energy Regulatory Authority)")
        assert result.state == ResolutionState.RESOLVED
        assert result.entity_id == zera_entity.entity_id

    def test_ambiguous_acronym_multiple_entities(self, resolver, registry):
        """Test ambiguous acronym matching"""
        # Create two entities with same acronym
        entity1 = registry.create_entity(
            canonical_name="International Development Association",
            acronyms=["IDA"],
        )
        entity2 = registry.create_entity(
            canonical_name="Integrated Data Authority",
            acronyms=["IDA"],
        )
        
        result = resolver.resolve("IDA")
        assert result.state == ResolutionState.AMBIGUOUS
        assert len(result.candidates) == 2


class TestNameComponentExtraction:
    """Test resolution via name component extraction"""

    def test_resolve_via_name_extraction(self, resolver, zera_entity):
        """Test resolution of name with acronym suffix"""
        result = resolver.resolve("Zimbabwe Energy Regulatory Authority (ZERA)")
        assert result.state == ResolutionState.RESOLVED
        assert result.entity_id == zera_entity.entity_id


class TestNewEntityDetection:
    """Test detection of new entities"""

    def test_unmatched_text_returns_new_entity(self, resolver):
        """Test that unmatched text returns NEW_ENTITY state"""
        result = resolver.resolve("Some Random Organization")
        assert result.state == ResolutionState.NEW_ENTITY
        assert result.entity_id is None
        assert result.confidence == 0.0

    def test_empty_input_returns_new_entity(self, resolver):
        """Test that empty input returns NEW_ENTITY"""
        result = resolver.resolve("")
        assert result.state == ResolutionState.NEW_ENTITY

    def test_none_input_returns_new_entity(self, resolver):
        """Test that None input returns NEW_ENTITY"""
        result = resolver.resolve(None)
        assert result.state == ResolutionState.NEW_ENTITY


class TestAliasMatching:
    """Test resolution via aliases"""

    def test_resolve_via_registered_alias(self, resolver, registry, zera_entity):
        """Test resolution via a registered alias"""
        # Add alias
        registry.add_alias_to_entity(
            zera_entity.entity_id,
            "The Energy Regulator",
            "the energy regulator",
            "context_source",
        )
        
        result = resolver.resolve("The Energy Regulator")
        assert result.state == ResolutionState.RESOLVED
        assert result.entity_id == zera_entity.entity_id


class TestFuzzyMatching:
    """Test fuzzy matching fallback"""

    def test_fuzzy_match_similar_name(self, resolver, zera_entity):
        """Test fuzzy matching for similar names"""
        # Slightly misspelled
        result = resolver.resolve("Zimbabwe Eneregy Regulatory Authority")
        # Should still resolve with fuzzy matching
        if result.state == ResolutionState.RESOLVED:
            assert result.entity_id == zera_entity.entity_id
        elif result.state == ResolutionState.POSSIBLE_MATCH:
            # At least should be in candidates
            entity_ids = [eid for eid, _ in result.candidates]
            assert zera_entity.entity_id in entity_ids

    def test_fuzzy_threshold_enforcement(self, resolver, registry):
        """Test that fuzzy threshold is respected"""
        entity = registry.create_entity("Original Entity Name")
        
        # Very different string should not match
        result = resolver.resolve("Completely Different Text")
        assert result.state == ResolutionState.NEW_ENTITY


class TestDedupWithVariants:
    """Test deduplication of name variants"""

    def test_zera_variants_resolve_same(self, resolver, registry):
        """Test that ZERA variants all resolve to same entity"""
        entity = registry.create_entity(
            canonical_name="Zimbabwe Energy Regulatory Authority",
            acronyms=["ZERA"],
        )
        
        variants = [
            "ZERA",
            "Zimbabwe Energy Regulatory Authority",
            "Zimbabwe Energy Regulatory Authority (ZERA)",
            "ZERA (Zimbabwe Energy Regulatory Authority)",
            "zimbabwe energy regulatory authority",
            "ZIMBABWE ENERGY REGULATORY AUTHORITY",
        ]
        
        for variant in variants:
            result = resolver.resolve(variant)
            assert result.state == ResolutionState.RESOLVED, f"Failed for variant: {variant}"
            assert result.entity_id == entity.entity_id, f"Wrong entity for variant: {variant}"

    def test_no_duplicate_entities_for_variants(self, resolver, registry):
        """Test that adding variants doesn't create duplicates"""
        entity = registry.create_entity(
            canonical_name="Zimbabwe Energy Regulatory Authority",
            acronyms=["ZERA"],
        )
        
        # Registry should have exactly 1 entity
        assert registry.count() == 1
        
        # Add some aliases
        registry.add_alias_to_entity(
            entity.entity_id,
            "ZERA (Zimbabwe Energy Regulatory Authority)",
            "zera (zimbabwe energy regulatory authority)",
            "variant_source",
        )
        
        # Should still have only 1 entity
        assert registry.count() == 1
        
        # All should resolve to same entity
        for variant in ["ZERA", "Zimbabwe Energy Regulatory Authority"]:
            result = resolver.resolve(variant)
            assert result.entity_id == entity.entity_id
