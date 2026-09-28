"""Unit tests for the CommonCrawlProvider."""
from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.research.commoncrawl_provider import CommonCrawlProvider


class TestCommonCrawlProvider:
    """Tests for CommonCrawlProvider class."""

    def test_provider_initialization_default(self):
        """Test provider initializes with default parameters."""
        provider = CommonCrawlProvider()
        assert provider.index_url == "https://index.commoncrawl.org"
        assert provider.timeout == 15.0
        assert provider.max_results == 10

    def test_provider_initialization_custom(self):
        """Test provider initializes with custom parameters."""
        provider = CommonCrawlProvider(
            index_url="https://custom-commoncrawl.example.com",
            timeout=30.0,
            max_results=20,
        )
        assert provider.index_url == "https://custom-commoncrawl.example.com"
        assert provider.timeout == 30.0
        assert provider.max_results == 20

    def test_empty_query_returns_empty_list(self):
        """Test empty query returns empty results."""
        provider = CommonCrawlProvider()
        
        async def run_test():
            results = await provider.search("")
            assert results == []
        
        import asyncio
        asyncio.run(run_test())

    def test_whitespace_only_query_returns_empty_list(self):
        """Test whitespace-only query returns empty results."""
        provider = CommonCrawlProvider()
        
        async def run_test():
            results = await provider.search("   ")
            assert results == []
        
        import asyncio
        asyncio.run(run_test())

    @patch("httpx.AsyncClient")
    async def test_get_latest_crawl_format(self, mock_async_client):
        """Test _get_latest_crawl returns properly formatted crawl identifier."""
        provider = CommonCrawlProvider()
        crawl_id = provider._get_latest_crawl()
        
        # Should be in format CC-MAIN-YYYY-WW
        assert crawl_id.startswith("CC-MAIN-")
        # Should have year and week parts
        parts = crawl_id.split("-")
        assert len(parts) == 4  # CC, MAIN, year, week
        # Year should be 4 digits
        assert parts[2].isdigit() and len(parts[2]) == 4
        # Week should be 2 digits
        assert parts[3].isdigit() and len(parts[3]) == 2

    @patch("httpx.AsyncClient")
    async def test_text_search_url_no_duplicate_cc_main(self, mock_async_client):
        """Test text search URL does not duplicate CC-MAIN- prefix."""
        provider = CommonCrawlProvider()
        
        # Mock the _get_latest_crawl to return a known value
        with patch.object(provider, '_get_latest_crawl', return_value="CC-MAIN-2026-40"):
            # Mock the async client
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = []
            
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get.return_value = mock_response
            mock_async_client.return_value = mock_client
            
            # Call _search_by_text
            results = await provider._search_by_text("test query", 5)
            
            # Verify the URL that was called
            mock_client.get.assert_called_once()
            call_args = mock_client.get.call_args
            url = call_args[0][0]
            
            # URL should be https://index.commoncrawl.org/CC-MAIN-2026-40-text-index
            # NOT https://index.commoncrawl.org/CC-MAIN-CC-MAIN-2026-40-text-index
            assert "CC-MAIN-2026-40-text-index" in url
            assert "CC-MAIN-CC-MAIN-" not in url  # No duplication
            assert url == "https://index.commoncrawl.org/CC-MAIN-2026-40-text-index"

    @patch("httpx.AsyncClient")
    async def test_text_search_handles_307_redirect(self, mock_async_client):
        """Test text search handles 307 redirect properly."""
        provider = CommonCrawlProvider()
        
        with patch.object(provider, '_get_latest_crawl', return_value="CC-MAIN-2026-40"):
            # First response is 307 redirect
            mock_redirect_response = MagicMock()
            mock_redirect_response.status_code = 307
            mock_redirect_response.headers = {"location": "https://index.commoncrawl.org/CC-MAIN-2026-40/?url=test"}
            
            # Second response (after redirect) is 200
            mock_final_response = MagicMock()
            mock_final_response.status_code = 200
            mock_final_response.json.return_value = []
            
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            # First call returns redirect, second call returns final response
            mock_client.get.side_effect = [mock_redirect_response, mock_final_response]
            mock_async_client.return_value = mock_client
            
            results = await provider._search_by_text("test query", 5)
            
            # Should have made 2 calls (original + redirect)
            assert mock_client.get.call_count == 2

    @patch("httpx.AsyncClient")
    async def test_text_search_handles_redirect_to_non_cc_url(self, mock_async_client):
        """Test text search returns empty when redirect is to non-CC URL."""
        provider = CommonCrawlProvider()
        
        with patch.object(provider, '_get_latest_crawl', return_value="CC-MAIN-2026-40"):
            mock_response = MagicMock()
            mock_response.status_code = 307
            mock_response.headers = {"location": "https://evil.com"}
            
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get.return_value = mock_response
            mock_async_client.return_value = mock_client
            
            results = await provider._search_by_text("test query", 5)
            
            assert results == []

    @patch("httpx.AsyncClient")
    async def test_url_search_handles_404_crawl_index(self, mock_async_client):
        """Test URL search handles 404 for unavailable crawl index."""
        provider = CommonCrawlProvider()
        
        with patch.object(provider, '_get_available_crawl_indexes', new_callable=AsyncMock) as mock_get_crawls:
            mock_get_crawls.return_value = ["CC-MAIN-2026-40"]
            
            mock_response = MagicMock()
            mock_response.status_code = 404
            
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get.return_value = mock_response
            mock_async_client.return_value = mock_client
            
            results = await provider._search_by_url("example.com", 5)
            
            # Should return empty list when crawl index is not available
            assert results == []

    @patch("httpx.AsyncClient")
    async def test_url_search_success(self, mock_async_client):
        """Test URL search with valid response."""
        provider = CommonCrawlProvider()
        
        with patch.object(provider, '_get_available_crawl_indexes', new_callable=AsyncMock) as mock_get_crawls:
            mock_get_crawls.return_value = ["CC-MAIN-2026-40"]
            
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = [
                {
                    "url": "https://example.com",
                    "timestamp": "20260101000000",
                    "fetchTime": "2026-01-01T00:00:00Z",
                }
            ]
            
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get.return_value = mock_response
            mock_async_client.return_value = mock_client
            
            results = await provider._search_by_url("example.com", 5)
            
            assert len(results) == 1
            assert results[0]["url"] == "https://example.com"

    def test_normalize_for_cc_removes_protocol(self):
        """Test _normalize_for_cc removes protocol."""
        provider = CommonCrawlProvider()
        
        assert provider._normalize_for_cc("https://example.com") == "example.com"
        assert provider._normalize_for_cc("http://example.com") == "example.com"

    def test_normalize_for_cc_removes_www(self):
        """Test _normalize_for_cc removes www prefix."""
        provider = CommonCrawlProvider()
        
        assert provider._normalize_for_cc("www.example.com") == "example.com"
        assert provider._normalize_for_cc("https://www.example.com") == "example.com"

    def test_normalize_for_cc_removes_path(self):
        """Test _normalize_for_cc removes path."""
        provider = CommonCrawlProvider()
        
        assert provider._normalize_for_cc("https://example.com/path/to/page") == "example.com"
        assert provider._normalize_for_cc("example.com/path?query=1") == "example.com"

    def test_normalize_for_cc_removes_port(self):
        """Test _normalize_for_cc removes port."""
        provider = CommonCrawlProvider()
        
        assert provider._normalize_for_cc("example.com:8080") == "example.com"

    def test_extract_domain_from_query(self):
        """Test _extract_domain extracts domain from query."""
        provider = CommonCrawlProvider()
        
        assert provider._extract_domain("sapp.co.zw") == "sapp.co.zw"
        assert provider._extract_domain("https://sapp.co.zw") == "sapp.co.zw"
        assert provider._extract_domain("www.sapp.co.zw") == "sapp.co.zw"
        assert provider._extract_domain("African Development Bank") is None

    def test_extract_title_from_url(self):
        """Test _extract_title_from_url extracts reasonable title."""
        provider = CommonCrawlProvider()
        
        assert provider._extract_title_from_url("https://example.com/about") == "About"
        assert provider._extract_title_from_url("https://example.com") == "Example Com"
        assert provider._extract_title_from_url("https://sub.example.com/path/to/page") == "Page"

    def test_format_cc_result(self):
        """Test _format_cc_result formats result correctly."""
        provider = CommonCrawlProvider()
        
        item = {
            "url": "https://example.com",
            "timestamp": "20260101000000",
            "fetchTime": "2026-01-01T00:00:00Z",
        }
        result = provider._format_cc_result(item)
        
        assert result is not None
        assert result["url"] == "https://example.com"
        assert result["source"] == "common_crawl"
        assert "Captured" in result["snippet"] or "Fetched" in result["snippet"]

    def test_format_cc_result_empty_url(self):
        """Test _format_cc_result returns None for empty URL."""
        provider = CommonCrawlProvider()
        
        item = {"url": "", "timestamp": "20260101000000"}
        result = provider._format_cc_result(item)
        
        assert result is None

    def test_format_cc_result_missing_url(self):
        """Test _format_cc_result returns None for missing URL."""
        provider = CommonCrawlProvider()
        
        item = {"timestamp": "20260101000000"}
        result = provider._format_cc_result(item)
        
        assert result is None

    @patch("httpx.AsyncClient")
    async def test_search_deduplicates_urls(self, mock_async_client):
        """Test search deduplicates URLs from multiple approaches."""
        provider = CommonCrawlProvider()
        
        # Mock _search_by_url and _search_by_text to return overlapping results
        with patch.object(provider, '_search_by_url', new_callable=AsyncMock) as mock_url_search:
            mock_url_search.return_value = [
                {"url": "https://example.com", "title": "Example", "snippet": "...", "source": "common_crawl"}
            ]
            
            with patch.object(provider, '_search_by_text', new_callable=AsyncMock) as mock_text_search:
                mock_text_search.return_value = [
                    {"url": "https://example.com", "title": "Example", "snippet": "...", "source": "common_crawl"},
                    {"url": "https://example.org", "title": "Example Org", "snippet": "...", "source": "common_crawl"},
                ]
                
                with patch.object(provider, '_extract_domain', return_value=None):
                    results = await provider.search("test", max_results=10)
                    
                    # Should have only 2 unique URLs
                    urls = [r.url for r in results]
                    assert len(urls) == 2
                    assert "https://example.com" in urls
                    assert "https://example.org" in urls
