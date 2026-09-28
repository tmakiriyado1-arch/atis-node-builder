"""Unit tests for the ATISOntology."""
from __future__ import annotations

import pytest

from app.services.ontology import ATISOntology, get_ontology


class TestATISOntology:
    """Tests for ATISOntology class."""

    def test_ontology_singleton(self):
        """Test get_ontology returns a singleton instance."""
        ontology1 = get_ontology()
        ontology2 = get_ontology()
        assert ontology1 is ontology2

    def test_ontology_frozen(self):
        """Test ATISOntology is frozen (immutable)."""
        ontology = get_ontology()
        with pytest.raises(AttributeError):
            ontology.new_attribute = "test"

    def test_organization_subtypes_property(self):
        """Test organization_subtypes property returns organization_types."""
        ontology = get_ontology()
        
        # organization_subtypes should be a property that returns organization_types
        assert hasattr(ontology, 'organization_subtypes')
        
        # Should be a FrozenSet
        subtypes = ontology.organization_subtypes
        assert isinstance(subtypes, frozenset)
        
        # Should contain organization types
        assert "international organization" in subtypes
        assert "development bank" in subtypes
        assert "government agency" in subtypes

    def test_concept_subtypes_property(self):
        """Test concept_subtypes property returns non-None concept subtype values."""
        ontology = get_ontology()
        
        # concept_subtypes should be a property
        assert hasattr(ontology, 'concept_subtypes')
        
        # Should be a FrozenSet
        subtypes = ontology.concept_subtypes
        assert isinstance(subtypes, frozenset)
        
        # Should contain the mapped subtype values (not None)
        assert "economic_policy" in subtypes
        assert "policy" in subtypes
        assert "ideological_framework" in subtypes

    def test_concept_subtype_mapping(self):
        """Test concept_subtype_mapping contains expected mappings."""
        ontology = get_ontology()
        
        mapping = ontology.concept_subtype_mapping
        assert isinstance(mapping, dict)
        
        # Check specific mappings
        assert mapping.get("economic policy approach") == "economic_policy"
        assert mapping.get("policy approach") == "policy"
        assert mapping.get("concept") is None

    def test_organization_types_available(self):
        """Test organization_types contains expected types."""
        ontology = get_ontology()
        
        org_types = ontology.organization_types
        assert isinstance(org_types, frozenset)
        
        expected_types = [
            "international organization",
            "development bank",
            "government agency",
            "regional organization",
        ]
        for t in expected_types:
            assert t in org_types

    def test_all_entity_types_includes_organizations(self):
        """Test all_entity_types includes organization types."""
        ontology = get_ontology()
        
        all_types = ontology.all_entity_types
        org_types = ontology.organization_types
        
        # All organization types should be in all_entity_types
        for org_type in org_types:
            assert org_type in all_types

    def test_relationship_predicates_available(self):
        """Test relationship_predicates contains expected predicates."""
        ontology = get_ontology()
        
        predicates = ontology.relationship_predicates
        assert isinstance(predicates, frozenset)
        
        expected = ["regulates", "manages", "oversees", "supports"]
        for p in expected:
            assert p in predicates

    def test_association_predicates_available(self):
        """Test association_predicates contains expected predicates."""
        ontology = get_ontology()
        
        predicates = ontology.association_predicates
        assert isinstance(predicates, frozenset)
        
        expected = ["connected_to", "relevant_to", "related_to"]
        for p in expected:
            assert p in predicates

    def test_is_relationship_predicate(self):
        """Test is_relationship_predicate method."""
        ontology = get_ontology()
        
        assert ontology.is_relationship_predicate("regulates") is True
        assert ontology.is_relationship_predicate("REGULATES") is True
        assert ontology.is_relationship_predicate("connected_to") is False
        assert ontology.is_relationship_predicate("unknown") is False

    def test_is_association_predicate(self):
        """Test is_association_predicate method."""
        ontology = get_ontology()
        
        assert ontology.is_association_predicate("connected_to") is True
        assert ontology.is_association_predicate("CONNECTED_TO") is True
        assert ontology.is_association_predicate("regulates") is False
        assert ontology.is_association_predicate("unknown") is False

    def test_get_concept_subtype(self):
        """Test get_concept_subtype method."""
        ontology = get_ontology()
        
        assert ontology.get_concept_subtype("economic policy approach") == "economic_policy"
        assert ontology.get_concept_subtype("ECONOMIC POLICY APPROACH") == "economic_policy"
        assert ontology.get_concept_subtype("concept") is None
        assert ontology.get_concept_subtype("unknown") is None

    def test_countries_available(self):
        """Test countries contains expected values."""
        ontology = get_ontology()
        
        countries = ontology.countries
        assert isinstance(countries, frozenset)
        
        expected = ["zimbabwe", "south africa", "africa"]
        for c in expected:
            assert c in countries

    def test_sectors_available(self):
        """Test sectors contains expected values."""
        ontology = get_ontology()
        
        sectors = ontology.sectors
        assert isinstance(sectors, frozenset)
        
        expected = ["Energy Sector", "Power Sector", "Infrastructure"]
        for s in expected:
            assert s in sectors

    def test_statuses_available(self):
        """Test statuses contains expected values."""
        ontology = get_ontology()
        
        statuses = ontology.statuses
        assert isinstance(statuses, frozenset)
        
        expected = ["active", "operational", "established"]
        for s in expected:
            assert s in statuses

    def test_organization_subtypes_union_concept_subtypes(self):
        """Test that organization_subtypes | concept_subtypes works for enrichment."""
        ontology = get_ontology()
        
        # This is the pattern used in mistral_enrichment.py
        all_subtypes = ontology.organization_subtypes | ontology.concept_subtypes
        
        # Should be a FrozenSet
        assert isinstance(all_subtypes, frozenset)
        
        # Should contain both org and concept subtypes
        assert "development bank" in all_subtypes
        assert "economic_policy" in all_subtypes

    def test_no_attribute_error_for_organization_subtypes(self):
        """Test that accessing organization_subtypes does not raise AttributeError."""
        ontology = get_ontology()
        
        # This was the bug: 'ATISOntology' object has no attribute 'organization_subtypes'
        # Now it should work as a property
        try:
            subtypes = ontology.organization_subtypes
            assert subtypes is not None
            assert isinstance(subtypes, frozenset)
        except AttributeError as e:
            pytest.fail(f"organization_subtypes property not found: {e}")

    def test_no_attribute_error_for_concept_subtypes(self):
        """Test that accessing concept_subtypes does not raise AttributeError."""
        ontology = get_ontology()
        
        try:
            subtypes = ontology.concept_subtypes
            assert subtypes is not None
            assert isinstance(subtypes, frozenset)
        except AttributeError as e:
            pytest.fail(f"concept_subtypes property not found: {e}")
