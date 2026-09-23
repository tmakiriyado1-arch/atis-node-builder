"""Focused tests for Wikidata authoritative URL discovery and DirectSiteCrawler integration."""
from __future__ import annotations

from typing import Any, Dict
from unittest.mock import AsyncMock, patch

import pytest

from app.services.research.direct_site_crawler import DirectSiteCrawler
from app.services.research.wikidata_provider import WikidataProvider


class TestWikidataStructuredMetadata:
    """Test that Wikidata returns structured metadata including official website."""

    @pytest.mark.asyncio
    async def test_wikidata_returns_official_website_in_metadata(self):
        """Test that Wikidata provider returns official_website in metadata."""
        provider = WikidataProvider()
        
        # Mock _get_entity_info to return data with official website
        mock_entity_data = {
            "id": "Q7569582",
            "labels": {"en": {"value": "Southern African Power Pool"}},
            "descriptions": {"en": {"value": "A power pool in Southern Africa"}},
            "claims": {
                "P856": [{"mainsnak": {"datavalue": {"value": "https://www.sapp.co.zw/"}}}],
                "P31": [{"mainsnak": {"datavalue": {"value": "Q7236594"}}}],
            },
            "sitelinks": {"enwiki": {"title": "Southern African Power Pool"}},
            "aliases": {"en": [{"value": "SAPP"}]},
        }
        
        with patch.object(provider, '_get_entity_info', new_callable=AsyncMock) as mock_get_info:
            mock_get_info.return_value = mock_entity_data
            
            with patch.object(provider, '_find_entity_by_label', new_callable=AsyncMock) as mock_find:
                mock_find.return_value = "Q7569582"
                
                results = await provider.search("Southern African Power Pool", max_results=5)
                
                assert len(results) > 0
                result = results[0]
                
                # Check that metadata contains official_website
                assert hasattr(result, "metadata")
                assert "official_website" in result.metadata
                assert result.metadata["official_website"] == "https://www.sapp.co.zw/"
                
                # Check that entity_id is preserved
                assert result.metadata["entity_id"] == "Q7569582"
                
                # Check that aliases are in metadata
                assert "aliases" in result.metadata
                assert "SAPP" in result.metadata["aliases"]

    @pytest.mark.asyncio
    async def test_wikidata_returns_entity_id(self):
        """Test that Wikidata provider preserves entity_id."""
        provider = WikidataProvider()
        
        mock_entity_data = {
            "id": "Q12345",
            "labels": {"en": {"value": "Test Entity"}},
            "descriptions": {"en": {"value": "Test description"}},
            "claims": {},
        }
        
        with patch.object(provider, '_get_entity_info', new_callable=AsyncMock) as mock_get_info:
            mock_get_info.return_value = mock_entity_data
            
            with patch.object(provider, '_find_entity_by_label', new_callable=AsyncMock) as mock_find:
                mock_find.return_value = "Q12345"
                
                results = await provider.search("Test Entity", max_results=5)
                
                assert len(results) > 0
                result = results[0]
                assert result.metadata["entity_id"] == "Q12345"


class TestDirectSiteCrawlerVerifiedURLs:
    """Test that DirectSiteCrawler uses verified URLs from context."""

    @pytest.mark.asyncio
    async def test_crawler_prefers_verified_official_website(self):
        """Test that crawler uses official_website from context."""
        crawler = DirectSiteCrawler()
        
        context = {"official_website": "https://www.example.com/"}
        
        with patch.object(crawler, '_crawl_url', new_callable=AsyncMock) as mock_crawl:
            mock_crawl.return_value = [{"title": "Test", "url": "https://www.example.com/", "snippet": "Test content"}]
            
            results = await crawler.search("Test Entity", max_results=5, context=context)
            
            # Should have called _crawl_url with the verified website
            assert mock_crawl.called
            call_args = mock_crawl.call_args
            assert call_args[0][0] == "https://www.example.com/"
            
            # Should have returned results
            assert len(results) == 1
            assert results[0].url == "https://www.example.com/"

    @pytest.mark.asyncio
    async def test_crawler_does_not_guess_urls(self):
        """Test that crawler does not guess URLs when no verified URL is available."""
        crawler = DirectSiteCrawler()
        
        # No context, no URL in query
        with patch.object(crawler, '_crawl_url', new_callable=AsyncMock) as mock_crawl:
            results = await crawler.search("Test Entity (TEST)", max_results=5, context=None)
            
            # Should NOT have called _crawl_url (no verified URLs to crawl)
            assert not mock_crawl.called
            
            # Should return empty results
            assert len(results) == 0

    @pytest.mark.asyncio
    async def test_crawler_uses_url_from_query(self):
        """Test that crawler uses URL when query is a URL."""
        crawler = DirectSiteCrawler()
        
        with patch.object(crawler, '_crawl_url', new_callable=AsyncMock) as mock_crawl:
            mock_crawl.return_value = [{"title": "Test", "url": "https://www.example.com/", "snippet": "Test content"}]
            
            results = await crawler.search("https://www.example.com/", max_results=5, context=None)
            
            # Should have called _crawl_url with the URL from query
            assert mock_crawl.called
            call_args = mock_crawl.call_args
            assert call_args[0][0] == "https://www.example.com/"
            
            assert len(results) == 1

    @pytest.mark.asyncio
    async def test_crawler_uses_multiple_verified_urls(self):
        """Test that crawler uses multiple verified URLs from context."""
        crawler = DirectSiteCrawler()
        
        context = {
            "urls": [
                "https://www.example1.com/",
                "https://www.example2.com/",
            ]
        }
        
        with patch.object(crawler, '_crawl_url', new_callable=AsyncMock) as mock_crawl:
            mock_crawl.return_value = [{"title": "Test", "url": "https://www.example.com/", "snippet": "Test content"}]
            
            results = await crawler.search("Test Entity", max_results=5, context=context)
            
            # Should have called _crawl_url for both URLs
            assert mock_crawl.call_count == 2
            
            # Should have returned results
            assert len(results) == 2

    @pytest.mark.asyncio
    async def test_crawler_deduplicates_urls(self):
        """Test that crawler deduplicates URLs from context."""
        crawler = DirectSiteCrawler()
        
        context = {
            "official_website": "https://www.example.com/",
            "urls": ["https://www.example.com/", "https://www.example.com/"],
        }
        
        with patch.object(crawler, '_crawl_url', new_callable=AsyncMock) as mock_crawl:
            mock_crawl.return_value = [{"title": "Test", "url": "https://www.example.com/", "snippet": "Test content"}]
            
            results = await crawler.search("Test Entity", max_results=5, context=context)
            
            # Should have called _crawl_url only once (deduplicated)
            assert mock_crawl.call_count == 1


class TestWikidataMetadataPropagation:
    """Test that Wikidata metadata is propagated through the orchestrator."""

    @pytest.mark.asyncio
    async def test_wikidata_metadata_preserved_in_results(self):
        """Test that Wikidata metadata is preserved in search results."""
        provider = WikidataProvider()
        
        mock_entity_data = {
            "id": "Q7569582",
            "labels": {"en": {"value": "Southern African Power Pool"}},
            "descriptions": {"en": {"value": "A power pool"}},
            "claims": {
                "P856": [{"mainsnak": {"datavalue": {"value": "https://www.sapp.co.zw/"}}}],
            },
        }
        
        with patch.object(provider, '_get_entity_info', new_callable=AsyncMock) as mock_get_info:
            mock_get_info.return_value = mock_entity_data
            
            with patch.object(provider, '_find_entity_by_label', new_callable=AsyncMock) as mock_find:
                mock_find.return_value = "Q7569582"
                
                results = await provider.search("Southern African Power Pool", max_results=5)
                
                assert len(results) > 0
                result = results[0]
                
                # Metadata should be present
                assert hasattr(result, "metadata")
                assert "official_website" in result.metadata

    @pytest.mark.asyncio
    async def test_wikidata_without_official_website(self):
        """Test that Wikidata works without official website."""
        provider = WikidataProvider()
        
        mock_entity_data = {
            "id": "Q12345",
            "labels": {"en": {"value": "Test Entity"}},
            "descriptions": {"en": {"value": "Test description"}},
            "claims": {},  # No P856 claim
        }
        
        with patch.object(provider, '_get_entity_info', new_callable=AsyncMock) as mock_get_info:
            mock_get_info.return_value = mock_entity_data
            
            with patch.object(provider, '_find_entity_by_label', new_callable=AsyncMock) as mock_find:
                mock_find.return_value = "Q12345"
                
                results = await provider.search("Test Entity", max_results=5)
                
                assert len(results) > 0
                result = results[0]
                
                # Should have empty or no metadata
                metadata = result.metadata
                assert "official_website" not in metadata


class TestDirectSiteCrawlerContextPropagation:
    """Test that context is propagated correctly through the system."""

    @pytest.mark.asyncio
    async def test_context_with_official_website_and_urls(self):
        """Test that context with both official_website and urls works."""
        crawler = DirectSiteCrawler()
        
        context = {
            "official_website": "https://www.primary.com/",
            "urls": ["https://www.secondary.com/"],
        }
        
        with patch.object(crawler, '_crawl_url', new_callable=AsyncMock) as mock_crawl:
            mock_crawl.return_value = [{"title": "Test", "url": "https://www.test.com/", "snippet": "Test content"}]
            
            results = await crawler.search("Test Entity", max_results=5, context=context)
            
            # Should have called _crawl_url twice (once for official_website, once for urls)
            assert mock_crawl.call_count == 2
            
            # Check that both URLs were crawled
            call_args_list = [call[0][0] for call in mock_crawl.call_args_list]
            assert "https://www.primary.com/" in call_args_list
            assert "https://www.secondary.com/" in call_args_list
