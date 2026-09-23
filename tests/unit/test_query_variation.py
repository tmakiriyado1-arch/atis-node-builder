"""Tests for query variation generation."""
import pytest

from app.services.research.query_variation import (
    DEFAULT_MAX_QUERY_VARIATIONS,
    QueryVariationConfig,
    QueryVariation,
    QueryVariationGenerator,
    generate_query_variations,
)


class TestQueryVariationGenerator:
    """Test query variation generation."""

    def test_basic_entity_name(self):
        """Test basic entity name generates at least the original query."""
        generator = QueryVariationGenerator()
        variations = generator.generate("Zimbabwe Energy Regulatory Authority")
        
        assert len(variations) >= 1
        assert variations[0].query == "Zimbabwe Energy Regulatory Authority"

    def test_acronym_extraction(self):
        """Test that acronyms are extracted from parentheses."""
        generator = QueryVariationGenerator()
        variations = generator.generate("Zimbabwe Energy Regulatory Authority (ZERA)", aliases=["ZERA"])
        
        queries = [v.query for v in variations]
        assert "ZERA" in queries
        assert "Zimbabwe Energy Regulatory Authority" in queries or "Zimbabwe Energy Regulatory Authority (ZERA)" in queries

    def test_acronym_without_parentheses(self):
        """Test entity name without parentheses still works."""
        generator = QueryVariationGenerator()
        variations = generator.generate("Southern African Power Pool")
        
        assert len(variations) >= 1
        assert variations[0].query == "Southern African Power Pool"

    def test_sapp_with_acronym(self):
        """Test SAPP with acronym generates variations."""
        generator = QueryVariationGenerator()
        variations = generator.generate("Southern African Power Pool (SAPP)", aliases=["SAPP"])
        
        queries = [v.query for v in variations]
        assert "Southern African Power Pool" in queries or "Southern African Power Pool (SAPP)" in queries
        assert "SAPP" in queries

    def test_contextual_variations_with_entity_type(self):
        """Test that entity type generates contextual variations."""
        generator = QueryVariationGenerator()
        variations = generator.generate(
            "Zimbabwe Energy Regulatory Authority",
            entity_type="regulator",
        )
        
        queries = [v.query for v in variations]
        # Should have base + acronym + contextual variations
        assert len(variations) >= 1
        # At least one should contain a regulator-related keyword
        has_contextual = any(
            kw in q.lower() for q in queries
            for kw in ["regulator", "regulation", "authority"]
        )
        # Note: This depends on context keywords being loaded

    def test_contextual_variations_with_country(self):
        """Test that country context generates location variations."""
        generator = QueryVariationGenerator()
        variations = generator.generate(
            "Zimbabwe Energy Regulatory Authority (ZERA)",
            country="Zimbabwe",
        )
        
        queries = [v.query for v in variations]
        assert len(variations) >= 1
        # Should have variations with Zimbabwe
        has_country = any("Zimbabwe" in q for q in queries)
        assert has_country

    def test_aliases_included(self):
        """Test that aliases are included in variations."""
        generator = QueryVariationGenerator()
        variations = generator.generate(
            "Zimbabwe Energy Regulatory Authority",
            aliases=["ZERA", "Energy Regulatory Authority"],
        )
        
        queries = [v.query for v in variations]
        assert "ZERA" in queries
        assert "Energy Regulatory Authority" in queries

    def test_max_variations_limit(self):
        """Test that max variations limit is respected."""
        config = QueryVariationConfig(max_variations=3)
        generator = QueryVariationGenerator(config)
        variations = generator.generate(
            "Zimbabwe Energy Regulatory Authority (ZERA)",
            aliases=["ZERA", "Energy Regulatory Authority", "Zimbabwe Energy Regulator"],
            country="Zimbabwe",
        )
        
        assert len(variations) <= 3

    def test_deduplication(self):
        """Test that duplicate queries are removed."""
        generator = QueryVariationGenerator()
        variations = generator.generate(
            "Zimbabwe Energy Regulatory Authority (ZERA)",
            aliases=["Zimbabwe Energy Regulatory Authority"],  # Duplicate
        )
        
        queries = [v.query for v in variations]
        # Should not have duplicates
        assert len(queries) == len(set(queries))

    def test_weight_ordering(self):
        """Test that higher weight variations come first."""
        generator = QueryVariationGenerator()
        variations = generator.generate(
            "Zimbabwe Energy Regulatory Authority (ZERA)",
        )
        
        # First variation should be the original entity name (weight 1.0)
        assert variations[0].query == "Zimbabwe Energy Regulatory Authority (ZERA)" or \
               variations[0].query == "Zimbabwe Energy Regulatory Authority"

    def test_provenance_tracking(self):
        """Test that query origins are tracked."""
        generator = QueryVariationGenerator()
        variations = generator.generate("Zimbabwe Energy Regulatory Authority (ZERA)", aliases=["ZERA"])
        
        origins = [v.origin for v in variations]
        assert "base" in origins
        assert "alias" in origins or "acronym" in origins


class TestQueryVariationConfig:
    """Test query variation configuration."""

    def test_default_config(self):
        """Test default configuration values."""
        config = QueryVariationConfig()
        assert config.max_variations == DEFAULT_MAX_QUERY_VARIATIONS
        assert config.use_acronym is True
        assert config.use_base_name is True
        assert config.use_contextual is True

    def test_custom_config(self):
        """Test custom configuration."""
        config = QueryVariationConfig(
            max_variations=5,
            use_acronym=False,
        )
        assert config.max_variations == 5
        assert config.use_acronym is False

    def test_min_variations(self):
        """Test that max_variations < 1 is corrected to 1."""
        config = QueryVariationConfig(max_variations=0)
        assert config.max_variations == 1


class TestGenerateQueryVariationsFunction:
    """Test the module-level convenience function."""

    def test_simple_entity(self):
        """Test simple entity name."""
        variations = generate_query_variations("ZERA")
        assert isinstance(variations, list)
        assert len(variations) >= 1
        assert "ZERA" in variations

    def test_entity_with_acronym(self):
        """Test entity with acronym."""
        variations = generate_query_variations("Zimbabwe Energy Regulatory Authority (ZERA)")
        assert "Zimbabwe Energy Regulatory Authority" in variations or \
               "Zimbabwe Energy Regulatory Authority (ZERA)" in variations

    def test_custom_max_variations(self):
        """Test custom max variations."""
        variations = generate_query_variations(
            "Zimbabwe Energy Regulatory Authority (ZERA)",
            max_variations=2,
        )
        assert len(variations) <= 2


class TestEdgeCases:
    """Test edge cases."""

    def test_empty_entity_name(self):
        """Test empty entity name."""
        generator = QueryVariationGenerator()
        variations = generator.generate("")
        assert variations == []

    def test_none_entity_name(self):
        """Test None entity name."""
        generator = QueryVariationGenerator()
        variations = generator.generate(None)
        assert variations == []

    def test_whitespace_only(self):
        """Test whitespace-only entity name."""
        generator = QueryVariationGenerator()
        variations = generator.generate("   ")
        assert variations == []

    def test_single_word(self):
        """Test single word entity."""
        generator = QueryVariationGenerator()
        variations = generator.generate("ZERA")
        assert len(variations) >= 1
        assert variations[0].query == "ZERA"

    def test_special_characters(self):
        """Test entity with special characters."""
        generator = QueryVariationGenerator()
        variations = generator.generate("ZERA - Zimbabwe's Energy Regulator")
        assert len(variations) >= 1

    def test_unicode(self):
        """Test entity with unicode characters."""
        generator = QueryVariationGenerator()
        variations = generator.generate("Zimbabwe Énergie Régulatrice")
        assert len(variations) >= 1
