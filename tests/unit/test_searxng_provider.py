"""Unit tests for the SearXNGProvider."""
from __future__ import annotations

import json
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.research.searxng_provider import SearXNGProvider


class TestSearXNGProvider:
    """Tests for SearXNGProvider class."""

    def test_provider_initialization_default(self):
        """Test provider initializes with default base_url."""
        provider = SearXNGProvider()
        assert provider.base_url == "https://crispy-potato-vpr6pwwjrqxvfwx5p-8888.app.github.dev"
        assert provider.timeout == 15.0
        assert provider.max_results == 10
        assert provider.role.value == "web_discovery"

    def test_provider_initialization_custom(self):
        """Test provider initializes with custom parameters."""
        provider = SearXNGProvider(
            base_url="https://custom-searxng.example.com",
            timeout=30.0,
            max_results=20,
        )
        assert provider.base_url == "https://custom-searxng.example.com"
        assert provider.timeout == 30.0
        assert provider.max_results == 20

    def test_provider_initialization_trailing_slash_removed(self):
        """Test provider removes trailing slash from base_url."""
        provider = SearXNGProvider(base_url="https://example.com/")
        assert provider.base_url == "https://example.com"

    def test_empty_query_returns_empty_list(self):
        """Test empty query returns empty results."""
        provider = SearXNGProvider()
        
        async def run_test():
            results = await provider.search("")
            assert results == []
        
        import asyncio
        asyncio.run(run_test())

    def test_whitespace_only_query_returns_empty_list(self):
        """Test whitespace-only query returns empty results."""
        provider = SearXNGProvider()
        
        async def run_test():
            results = await provider.search("   ")
            assert results == []
        
        import asyncio
        asyncio.run(run_test())

    @patch("httpx.AsyncClient")
    async def test_successful_search(self, mock_async_client):
        """Test successful search with valid SearXNG response."""
        # Create mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "query": "African Development Bank",
            "results": [
                {
                    "title": "African Development Bank",
                    "url": "https://www.afdb.org",
                    "content": "The African Development Bank Group...",
                    "engine": "wikipedia",
                    "engines": ["wikipedia", "brave"],
                    "score": 2.0,
                },
                {
                    "title": "AfDB Overview",
                    "url": "https://en.wikipedia.org/wiki/African_Development_Bank",
                    "content": "The African Development Bank is a multinational...",
                    "engine": "wikipedia",
                    "engines": ["wikipedia"],
                    "score": 1.8,
                },
            ],
        }
        
        # Configure mock client
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_async_client.return_value = mock_client
        
        provider = SearXNGProvider()
        results = await provider.search("African Development Bank", max_results=5)
        
        assert len(results) == 2
        assert results[0]["title"] == "African Development Bank"
        assert results[0]["url"] == "https://www.afdb.org"
        assert results[0]["snippet"] == "The African Development Bank Group..."
        assert results[0]["source"] == "searxng"
        assert "engine" in results[0]["metadata"]
        assert results[0]["metadata"]["engine"] == "wikipedia"

    @patch("httpx.AsyncClient")
    async def test_search_with_snippet_from_content(self, mock_async_client):
        """Test search extracts snippet from content field."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {
                    "title": "Test",
                    "url": "https://example.com",
                    "content": "This is the snippet content.",
                    "engine": "brave",
                },
            ],
        }
        
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_async_client.return_value = mock_client
        
        provider = SearXNGProvider()
        results = await provider.search("test")
        
        assert len(results) == 1
        assert results[0]["snippet"] == "This is the snippet content."

    @patch("httpx.AsyncClient")
    async def test_search_with_snippet_from_snippet_field(self, mock_async_client):
        """Test search extracts snippet from snippet field if content is missing."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {
                    "title": "Test",
                    "url": "https://example.com",
                    "snippet": "This is the snippet field.",
                    "engine": "brave",
                },
            ],
        }
        
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_async_client.return_value = mock_client
        
        provider = SearXNGProvider()
        results = await provider.search("test")
        
        assert len(results) == 1
        assert results[0]["snippet"] == "This is the snippet field."

    @patch("httpx.AsyncClient")
    async def test_search_http_403_returns_empty(self, mock_async_client):
        """Test HTTP 403 returns empty results."""
        mock_response = MagicMock()
        mock_response.status_code = 403
        
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_async_client.return_value = mock_client
        
        provider = SearXNGProvider()
        results = await provider.search("test")
        
        assert results == []

    @patch("httpx.AsyncClient")
    async def test_search_http_404_returns_empty(self, mock_async_client):
        """Test HTTP 404 returns empty results."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_async_client.return_value = mock_client
        
        provider = SearXNGProvider()
        results = await provider.search("test")
        
        assert results == []

    @patch("httpx.AsyncClient")
    async def test_search_http_500_returns_empty(self, mock_async_client):
        """Test HTTP 500 returns empty results."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_async_client.return_value = mock_client
        
        provider = SearXNGProvider()
        results = await provider.search("test")
        
        assert results == []

    @patch("httpx.AsyncClient")
    async def test_search_redirect_returns_empty(self, mock_async_client):
        """Test redirect (301/302) returns empty results without following."""
        mock_response = MagicMock()
        mock_response.status_code = 302
        mock_response.headers = {"location": "https://evil.com"}
        
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_async_client.return_value = mock_client
        
        provider = SearXNGProvider()
        results = await provider.search("test")
        
        assert results == []

    @patch("httpx.AsyncClient")
    async def test_search_invalid_json_returns_empty(self, mock_async_client):
        """Test invalid JSON response returns empty results."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Invalid JSON")
        
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_async_client.return_value = mock_client
        
        provider = SearXNGProvider()
        results = await provider.search("test")
        
        assert results == []

    @patch("httpx.AsyncClient")
    async def test_search_missing_results_key_returns_empty(self, mock_async_client):
        """Test response missing 'results' key returns empty results."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"query": "test"}
        
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_async_client.return_value = mock_client
        
        provider = SearXNGProvider()
        results = await provider.search("test")
        
        assert results == []

    @patch("httpx.AsyncClient")
    async def test_search_results_not_list_returns_empty(self, mock_async_client):
        """Test response with non-list results returns empty results."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": "not a list"}
        
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_async_client.return_value = mock_client
        
        provider = SearXNGProvider()
        results = await provider.search("test")
        
        assert results == []

    @patch("httpx.AsyncClient")
    async def test_search_empty_results_list(self, mock_async_client):
        """Test empty results list returns empty results."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": []}
        
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_async_client.return_value = mock_client
        
        provider = SearXNGProvider()
        results = await provider.search("test")
        
        assert results == []

    @patch("httpx.AsyncClient")
    async def test_search_duplicate_urls_removed(self, mock_async_client):
        """Test duplicate URLs are removed from results."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {
                    "title": "First",
                    "url": "https://example.com",
                    "content": "First result",
                    "engine": "wikipedia",
                },
                {
                    "title": "Second",
                    "url": "https://example.com",  # Duplicate URL
                    "content": "Second result",
                    "engine": "brave",
                },
                {
                    "title": "Third",
                    "url": "https://example.org",
                    "content": "Third result",
                    "engine": "google",
                },
            ],
        }
        
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_async_client.return_value = mock_client
        
        provider = SearXNGProvider()
        results = await provider.search("test")
        
        assert len(results) == 2  # Duplicate removed
        assert results[0]["url"] == "https://example.com"
        assert results[1]["url"] == "https://example.org"

    @patch("httpx.AsyncClient")
    async def test_search_empty_url_skipped(self, mock_async_client):
        """Test results with empty URLs are skipped."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {
                    "title": "No URL",
                    "url": "",
                    "content": "No URL result",
                    "engine": "test",
                },
                {
                    "title": "Valid",
                    "url": "https://example.com",
                    "content": "Valid result",
                    "engine": "wikipedia",
                },
            ],
        }
        
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_async_client.return_value = mock_client
        
        provider = SearXNGProvider()
        results = await provider.search("test")
        
        assert len(results) == 1
        assert results[0]["url"] == "https://example.com"

    @patch("httpx.AsyncClient")
    async def test_search_respects_max_results(self, mock_async_client):
        """Test search respects max_results parameter."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {"title": f"Result {i}", "url": f"https://example.com/{i}", "content": f"Content {i}", "engine": "test"}
                for i in range(100)
            ],
        }
        
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_async_client.return_value = mock_client
        
        provider = SearXNGProvider()
        results = await provider.search("test", max_results=5)
        
        assert len(results) == 5

    @patch("httpx.AsyncClient")
    async def test_search_connect_error_returns_empty(self, mock_async_client):
        """Test connection error returns empty results."""
        import httpx
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.side_effect = httpx.ConnectError("Connection refused")
        mock_async_client.return_value = mock_client
        
        provider = SearXNGProvider()
        results = await provider.search("test")
        
        assert results == []

    @patch("httpx.AsyncClient")
    async def test_search_timeout_returns_empty(self, mock_async_client):
        """Test timeout returns empty results."""
        import httpx
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.side_effect = httpx.TimeoutException("Request timed out")
        mock_async_client.return_value = mock_client
        
        provider = SearXNGProvider()
        results = await provider.search("test")
        
        assert results == []

    @patch("httpx.AsyncClient")
    async def test_search_url_encoding(self, mock_async_client):
        """Test query is properly URL-encoded."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": []}
        
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_async_client.return_value = mock_client
        
        provider = SearXNGProvider()
        await provider.search("African Development Bank & Group")
        
        # Check the URL that was called
        mock_client.get.assert_called_once()
        call_args = mock_client.get.call_args
        url = call_args[0][0]
        assert "African+Development+Bank+%26+Group" in url or "African%20Development%20Bank%20%26%20Group" in url

    @patch("httpx.AsyncClient")
    async def test_search_engines_list_in_metadata(self, mock_async_client):
        """Test engines list is preserved in metadata."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {
                    "title": "Test",
                    "url": "https://example.com",
                    "content": "Content",
                    "engine": "wikipedia",
                    "engines": ["wikipedia", "brave", "google cse"],
                },
            ],
        }
        
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_async_client.return_value = mock_client
        
        provider = SearXNGProvider()
        results = await provider.search("test")
        
        assert len(results) == 1
        assert results[0]["metadata"]["engines"] == ["wikipedia", "brave", "google cse"]

    @patch("httpx.AsyncClient")
    async def test_search_parsed_url_in_metadata(self, mock_async_client):
        """Test parsed_url is included in metadata if present."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {
                    "title": "Test",
                    "url": "https://example.com",
                    "content": "Content",
                    "engine": "wikipedia",
                    "parsed_url": [{"url": "https://example.com/clean"}],
                },
            ],
        }
        
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_async_client.return_value = mock_client
        
        provider = SearXNGProvider()
        results = await provider.search("test")
        
        assert len(results) == 1
        assert "parsed_url" in results[0]["metadata"]

    @patch("httpx.AsyncClient")
    async def test_search_score_in_metadata(self, mock_async_client):
        """Test score is included in metadata if present."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {
                    "title": "Test",
                    "url": "https://example.com",
                    "content": "Content",
                    "engine": "wikipedia",
                    "score": 3.5,
                },
            ],
        }
        
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_async_client.return_value = mock_client
        
        provider = SearXNGProvider()
        results = await provider.search("test")
        
        assert len(results) == 1
        assert results[0]["metadata"]["searxng_score"] == 3.5

    @patch("httpx.AsyncClient")
    async def test_search_position_in_metadata(self, mock_async_client):
        """Test position is included in metadata."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {"title": "First", "url": "https://example.com/1", "content": "1", "engine": "test"},
                {"title": "Second", "url": "https://example.com/2", "content": "2", "engine": "test"},
                {"title": "Third", "url": "https://example.com/3", "content": "3", "engine": "test"},
            ],
        }
        
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_async_client.return_value = mock_client
        
        provider = SearXNGProvider()
        results = await provider.search("test")
        
        assert len(results) == 3
        assert results[0]["metadata"]["searxng_position"] == 1
        assert results[1]["metadata"]["searxng_position"] == 2
        assert results[2]["metadata"]["searxng_position"] == 3

    @patch("httpx.AsyncClient")
    async def test_parse_response_non_dict(self, mock_async_client):
        """Test _parse_searxng_response handles non-dict responses."""
        provider = SearXNGProvider()
        results = provider._parse_searxng_response("not a dict", "test", 10)
        assert results == []

    @patch("httpx.AsyncClient")
    async def test_parse_response_non_list_results(self, mock_async_client):
        """Test _parse_searxng_response handles non-list results."""
        provider = SearXNGProvider()
        results = provider._parse_searxng_response(
            {"results": {"not": "a list"}}, "test", 10
        )
        assert results == []

    @patch("httpx.AsyncClient")
    async def test_parse_response_non_dict_result(self, mock_async_client):
        """Test _parse_searxng_response skips non-dict result items."""
        provider = SearXNGProvider()
        results = provider._parse_searxng_response(
            {"results": ["not a dict", {"title": "Valid", "url": "https://example.com"}]},
            "test",
            10
        )
        assert len(results) == 1
        assert results[0]["title"] == "Valid"

    @patch("httpx.AsyncClient")
    async def test_parse_response_large_snippet_truncated(self, mock_async_client):
        """Test large snippets are truncated to 1000 characters."""
        provider = SearXNGProvider()
        large_content = "x" * 2000
        results = provider._parse_searxng_response(
            {"results": [{"title": "Test", "url": "https://example.com", "content": large_content, "engine": "test"}]},
            "test",
            10
        )
        assert len(results) == 1
        assert len(results[0]["snippet"]) == 1000

    @patch("httpx.AsyncClient")
    async def test_parse_response_empty_content_uses_snippet(self, mock_async_client):
        """Test empty content falls back to snippet field."""
        provider = SearXNGProvider()
        results = provider._parse_searxng_response(
            {"results": [{"title": "Test", "url": "https://example.com", "content": "", "snippet": "Fallback snippet", "engine": "test"}]},
            "test",
            10
        )
        assert len(results) == 1
        assert results[0]["snippet"] == "Fallback snippet"

    @patch("httpx.AsyncClient")
    async def test_parse_response_whitespace_content(self, mock_async_client):
        """Test whitespace-only content is treated as empty."""
        provider = SearXNGProvider()
        results = provider._parse_searxng_response(
            {"results": [{"title": "Test", "url": "https://example.com", "content": "   ", "snippet": "Fallback", "engine": "test"}]},
            "test",
            10
        )
        assert len(results) == 1
        assert results[0]["snippet"] == "Fallback"
