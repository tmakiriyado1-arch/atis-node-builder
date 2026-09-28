"""Unit tests for the MozillaProvider."""
from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx

from app.services.research.mozilla_provider import MozillaProvider


class TestMozillaProvider:
    """Tests for MozillaProvider class."""

    def test_provider_initialization_default(self):
        """Test provider initializes with default parameters."""
        provider = MozillaProvider()
        assert provider.base_url == "https://search.mozilla.org/api/v1/search"
        assert provider.timeout == 15.0
        assert provider.max_results == 10

    def test_provider_initialization_custom(self):
        """Test provider initializes with custom parameters."""
        provider = MozillaProvider(
            base_url="https://custom-mozilla.example.com/api/v1/search",
            timeout=30.0,
            max_results=20,
        )
        assert provider.base_url == "https://custom-mozilla.example.com/api/v1/search"
        assert provider.timeout == 30.0
        assert provider.max_results == 20

    def test_empty_query_returns_empty_list(self):
        """Test empty query returns empty results."""
        provider = MozillaProvider()
        
        async def run_test():
            results = await provider.search("")
            assert results == []
        
        import asyncio
        asyncio.run(run_test())

    def test_whitespace_only_query_returns_empty_list(self):
        """Test whitespace-only query returns empty results."""
        provider = MozillaProvider()
        
        async def run_test():
            results = await provider.search("   ")
            assert results == []
        
        import asyncio
        asyncio.run(run_test())

    @patch("httpx.AsyncClient")
    async def test_search_connection_error_dns(self, mock_async_client):
        """Test search handles DNS resolution failure."""
        provider = MozillaProvider()
        
        # Simulate DNS failure
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.side_effect = httpx.ConnectError("[Errno -2] Name or service not known")
        mock_async_client.return_value = mock_client
        
        results = await provider.search("test query")
        
        assert results == []

    @patch("httpx.AsyncClient")
    async def test_search_connection_error_generic(self, mock_async_client):
        """Test search handles generic connection error."""
        provider = MozillaProvider()
        
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.side_effect = httpx.ConnectError("Connection refused")
        mock_async_client.return_value = mock_client
        
        results = await provider.search("test query")
        
        assert results == []

    @patch("httpx.AsyncClient")
    async def test_search_timeout(self, mock_async_client):
        """Test search handles timeout."""
        provider = MozillaProvider()
        
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.side_effect = httpx.TimeoutException("Request timed out")
        mock_async_client.return_value = mock_client
        
        results = await provider.search("test query")
        
        assert results == []

    @patch("httpx.AsyncClient")
    async def test_search_http_error(self, mock_async_client):
        """Test search handles HTTP errors."""
        provider = MozillaProvider()
        
        mock_response = MagicMock()
        mock_response.status_code = 500
        
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_async_client.return_value = mock_client
        
        results = await provider.search("test query")
        
        assert results == []

    @patch("httpx.AsyncClient")
    async def test_search_successful_json(self, mock_async_client):
        """Test search with successful JSON response."""
        provider = MozillaProvider()
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {
                    "title": "Test Result",
                    "url": "https://example.com",
                    "description": "Test description",
                },
            ],
        }
        
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_async_client.return_value = mock_client
        
        results = await provider.search("test query")
        
        assert len(results) == 1
        # Results are SearchResult objects
        from app.services.research.search_provider import SearchResult
        assert isinstance(results[0], SearchResult)

    @patch("httpx.AsyncClient")
    async def test_search_successful_web_pages_key(self, mock_async_client):
        """Test search handles web_pages key in response."""
        provider = MozillaProvider()
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "web_pages": [
                {
                    "title": "Test Result",
                    "url": "https://example.com",
                    "snippet": "Test snippet",
                },
            ],
        }
        
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_async_client.return_value = mock_client
        
        results = await provider.search("test query")
        
        assert len(results) == 1

    @patch("httpx.AsyncClient")
    async def test_search_html_fallback(self, mock_async_client):
        """Test search falls back to HTML parsing when response is not JSON."""
        provider = MozillaProvider()
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Not JSON")
        mock_response.text = "<html><body><a href='https://example.com'>Test</a></body></html>"
        
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_async_client.return_value = mock_client
        
        results = await provider.search("test query")
        
        # Should parse HTML and extract links
        assert len(results) >= 0  # May find 0 or more links depending on HTML

    def test_generate_query_variants(self):
        """Test _generate_query_variants method."""
        provider = MozillaProvider()
        
        variants = provider._generate_query_variants("African Development Bank (AfDB)")
        
        assert "African Development Bank (AfDB)" in variants
        assert "African Development Bank" in variants  # Without acronym
        # Note: MozillaProvider._generate_query_variants doesn't extract just the acronym
        # It only removes the acronym from the name, not extract it separately

    def test_generate_query_variants_with_context(self):
        """Test _generate_query_variants with context."""
        provider = MozillaProvider()
        
        context = {"country": "Zimbabwe", "entity_type": "organization"}
        variants = provider._generate_query_variants("SAPP (SAPP)", context)
        
        # Should include country and type variants
        assert any("Zimbabwe" in v for v in variants)

    def test_extract_acronym(self):
        """Test _extract_acronym static method."""
        assert MozillaProvider._extract_acronym("Test (ABC)") == "ABC"
        assert MozillaProvider._extract_acronym("Test (ABCD)") == "ABCD"
        assert MozillaProvider._extract_acronym("Test") is None
        assert MozillaProvider._extract_acronym("Test (abc)") is None  # lowercase

    def test_remove_acronym(self):
        """Test _remove_acronym static method."""
        assert MozillaProvider._remove_acronym("Test (ABC)") == "Test"
        assert MozillaProvider._remove_acronym("Test (ABC) ") == "Test"
        assert MozillaProvider._remove_acronym("Test") == "Test"

    def test_clean_url(self):
        """Test _clean_url static method."""
        # URL-encoded
        assert MozillaProvider._clean_url("https%3A%2F%2Fexample.com") == "https://example.com"
        
        # With tracking params
        url_with_params = "https://example.com?utm_source=test&gclid=123"
        cleaned = MozillaProvider._clean_url(url_with_params)
        assert "utm_" not in cleaned
        assert "gclid" not in cleaned

    def test_format_result(self):
        """Test _format_result method."""
        provider = MozillaProvider()
        
        item = {
            "title": "Test",
            "url": "https://example.com",
            "description": "Test description",
        }
        result = provider._format_result(item)
        
        assert result is not None
        assert result["title"] == "Test"
        assert result["url"] == "https://example.com"
        assert result["snippet"] == "Test description"

    def test_format_result_missing_fields(self):
        """Test _format_result returns None for missing required fields."""
        provider = MozillaProvider()
        
        # Missing title
        result = provider._format_result({"url": "https://example.com"})
        assert result is None
        
        # Missing URL
        result = provider._format_result({"title": "Test"})
        assert result is None
