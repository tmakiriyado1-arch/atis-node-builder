"""Focused tests for Wikipedia entity matching and acronym filtering."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.services.research.wikipedia_provider import WikipediaProvider


class TestEntityMatching:
    """Test entity matching logic for Wikipedia results."""

    def test_zera_personal_names_rejected(self):
        """Test that personal names containing ZERA are rejected."""
        provider = WikipediaProvider()
        
        # These should all be rejected
        assert not provider._is_entity_match(
            title="Zerelda James",
            snippet="American outlaw",
            entity_name="Zimbabwe Energy Regulatory Authority",
            acronym="ZERA",
        )
        
        assert not provider._is_entity_match(
            title="Zerai Deres",
            snippet="Ethiopian runner",
            entity_name="Zimbabwe Energy Regulatory Authority",
            acronym="ZERA",
        )
        
        assert not provider._is_entity_match(
            title="Zera Yacob",
            snippet="Ethiopian philosopher",
            entity_name="Zimbabwe Energy Regulatory Authority",
            acronym="ZERA",
        )

    def test_zera_organization_accepted(self):
        """Test that actual ZERA organization page is accepted."""
        provider = WikipediaProvider()
        
        # Simulate a result where the page is about ZERA with proper context
        assert provider._is_entity_match(
            title="Zimbabwe Energy Regulatory Authority",
            snippet="The Zimbabwe Energy Regulatory Authority (ZERA) is a regulatory body",
            entity_name="Zimbabwe Energy Regulatory Authority",
            acronym="ZERA",
        )
        
        # Also accept if snippet contains the full name
        assert provider._is_entity_match(
            title="ZERA",
            snippet="The Zimbabwe Energy Regulatory Authority (ZERA) regulates energy in Zimbabwe",
            entity_name="Zimbabwe Energy Regulatory Authority",
            acronym="ZERA",
        )

    def test_sapp_acronym_handling(self):
        """Test that SAPP acronym doesn't match unrelated pages."""
        provider = WikipediaProvider()
        
        # SAPP as personal name should be rejected
        assert not provider._is_entity_match(
            title="Sapp",
            snippet="American surname",
            entity_name="Southern African Power Pool",
            acronym="SAPP",
        )
        
        # SAPP organization should be accepted
        assert provider._is_entity_match(
            title="Southern African Power Pool",
            snippet="The Southern African Power Pool (SAPP) is an energy organization",
            entity_name="Southern African Power Pool",
            acronym="SAPP",
        )

    def test_partial_entity_name_match(self):
        """Test that partial entity name matches work when context is strong."""
        provider = WikipediaProvider()
        
        # Should accept if there's strong token overlap
        assert provider._is_entity_match(
            title="Energy Regulatory Authority of Zimbabwe",
            snippet="Regulatory body for energy in Zimbabwe",
            entity_name="Zimbabwe Energy Regulatory Authority",
            acronym="ZERA",
        )

    def test_no_entity_name_no_match(self):
        """Test that results with no entity name overlap are rejected."""
        provider = WikipediaProvider()
        
        assert not provider._is_entity_match(
            title="Some Random Organization",
            snippet="Completely unrelated content",
            entity_name="Zimbabwe Energy Regulatory Authority",
            acronym="ZERA",
        )


class TestAcronymExtraction:
    """Test acronym extraction from entity names."""

    def test_extract_acronym_with_parentheses(self):
        """Test extracting acronym from parentheses."""
        provider = WikipediaProvider()
        
        assert provider._extract_acronym("Zimbabwe Energy Regulatory Authority (ZERA)") == "ZERA"
        assert provider._extract_acronym("Southern African Power Pool (SAPP)") == "SAPP"
        assert provider._extract_acronym("Company Name (ABC)") == "ABC"

    def test_extract_acronym_no_parentheses(self):
        """Test that no acronym is extracted when there are no parentheses."""
        provider = WikipediaProvider()
        
        assert provider._extract_acronym("Zimbabwe Energy Regulatory Authority") is None
        assert provider._extract_acronym("Some Organization") is None

    def test_remove_acronym(self):
        """Test removing acronym from entity name."""
        provider = WikipediaProvider()
        
        assert provider._remove_acronym("Zimbabwe Energy Regulatory Authority (ZERA)") == "Zimbabwe Energy Regulatory Authority"
        assert provider._remove_acronym("Company Name (ABC)") == "Company Name"
        assert provider._remove_acronym("No Acronym Here") == "No Acronym Here"


class TestPersonalNameDetection:
    """Test personal name detection."""

    def test_personal_names_detected(self):
        """Test that personal names are correctly identified."""
        provider = WikipediaProvider()
        
        assert provider._is_personal_name("Zerelda James")
        assert provider._is_personal_name("Michael Zerafa")
        assert provider._is_personal_name("Zerai Deres")
        assert provider._is_personal_name("Zera Yacob")

    def test_organizations_not_personal_names(self):
        """Test that organizations are not identified as personal names."""
        provider = WikipediaProvider()
        
        assert not provider._is_personal_name("Zimbabwe Energy Regulatory Authority")
        assert not provider._is_personal_name("Southern African Power Pool")
        assert not provider._is_personal_name("Energy Regulatory Commission")


class TestWikipediaProviderIntegration:
    """Integration tests for Wikipedia provider with real-like data."""

    def test_zera_search_filters_personal_names_sync(self):
        """Test that _is_entity_match filters out personal names for ZERA."""
        provider = WikipediaProvider()
        
        # These results should all be rejected by _is_entity_match
        rejected_results = [
            {"title": "Zerelda James", "url": "http://en.wikipedia.org/wiki/Zerelda_James", "snippet": "American outlaw"},
            {"title": "Michael Zerafa", "url": "http://en.wikipedia.org/wiki/Michael_Zerafa", "snippet": "Boxer"},
            {"title": "Zerai Deres", "url": "http://en.wikipedia.org/wiki/Zerai_Deres", "snippet": "Runner"},
        ]
        
        for result in rejected_results:
            is_match = provider._is_entity_match(
                result["title"],
                result["snippet"],
                "Zimbabwe Energy Regulatory Authority",
                "ZERA",
            )
            assert not is_match, f"Should reject: {result['title']}"

    def test_zera_search_accepts_valid_result_sync(self):
        """Test that _is_entity_match accepts valid organization result."""
        provider = WikipediaProvider()
        
        # This result should be accepted
        result = {
            "title": "Zimbabwe Energy Regulatory Authority",
            "url": "http://en.wikipedia.org/wiki/Zimbabwe_Energy_Regulatory_Authority",
            "snippet": "The Zimbabwe Energy Regulatory Authority (ZERA) is a regulatory body in Zimbabwe",
        }
        
        is_match = provider._is_entity_match(
            result["title"],
            result["snippet"],
            "Zimbabwe Energy Regulatory Authority",
            "ZERA",
        )
        assert is_match

    def test_empty_results_when_no_match_sync(self):
        """Test that _is_entity_match rejects invalid results."""
        provider = WikipediaProvider()
        
        # These results should be rejected
        rejected_results = [
            {"title": "Zerelda James", "url": "http://en.wikipedia.org/wiki/Zerelda_James", "snippet": ""},
            {"title": "Michael Zerafa", "url": "http://en.wikipedia.org/wiki/Michael_Zerafa", "snippet": ""},
        ]
        
        for result in rejected_results:
            is_match = provider._is_entity_match(
                result["title"],
                result["snippet"],
                "Zimbabwe Energy Regulatory Authority",
                "ZERA",
            )
            assert not is_match
