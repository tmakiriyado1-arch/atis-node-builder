"""Unit tests for the AppsScriptSearchProvider."""
from __future__ import annotations

import json
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.research.apps_script_provider import AppsScriptSearchProvider


class TestAppsScriptSearchProvider:
    """Tests for AppsScriptSearchProvider class."""

    def test_provider_initialization_custom(self):
        """Test provider initializes with custom parameters."""
        provider = AppsScriptSearchProvider(
            base_url="https://custom-gateway.example.com",
            timeout=30.0,
            max_results=20,
        )
        assert provider.base_url == "https://custom-gateway.example.com"
        assert provider.timeout == 30.0
        assert provider.max_results == 20

    def test_provider_initialization_trailing_slash_removed(self):
        """Test provider removes trailing slash from base_url."""
        provider = AppsScriptSearchProvider(base_url="https://example.com/")
        assert provider.base_url == "https://example.com"

    def test_empty_query_returns_empty_list(self):
        """Test empty query returns empty results."""
        provider = AppsScriptSearchProvider(base_url="https://example.com")
        
        async def run_test():
            results = await provider.search("")
            assert results == []
        
        import asyncio
        asyncio.run(run_test())

    def test_whitespace_only_query_returns_empty_list(self):
        """Test whitespace-only query returns empty results."""
        provider = AppsScriptSearchProvider(base_url="https://example.com")
        
        async def run_test():
            results = await provider.search("   ")
            assert results == []
        
        import asyncio
        asyncio.run(run_test())

    def test_no_base_url_returns_empty_list(self):
        """Test provider with no base_url returns empty results."""
        provider = AppsScriptSearchProvider(base_url=None)
        
        async def run_test():
            results = await provider.search("test query")
            assert results == []
        
        import asyncio
        asyncio.run(run_test())

    @patch("httpx.AsyncClient")
    async def test_successful_search(self, mock_async_client):
        """Test successful search with valid gateway response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "ok": True,
            "qualityOk": True,
            "query": "Zimbabwe",
            "count": 10,
            "results": [
                {
                    "rank": 1,
                    "score": 18.3,
                    "url": "https://www.newzimbabwe.com",
                },
                {
                    "rank": 2,
                    "score": 15.2,
                    "url": "https://en.wikipedia.org/wiki/Zimbabwe",
                },
            ],
            "diagnostics": {},
            "rawCandidateCount": 10,
            "qualityCount": 10,
        }
        
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_async_client.return_value = mock_client
        
        provider = AppsScriptSearchProvider(base_url="https://script.google.com/macros/s/TEST/exec")
        results = await provider.search("Zimbabwe", max_results=5)
        
        assert len(results) == 2
        assert results[0]["url"] == "https://www.newzimbabwe.com"
        assert results[0]["title"] == "https://www.newzimbabwe.com"
        assert results[0]["snippet"] is None
        assert results[0]["source"] == "apps_script"
        assert "gateway_rank" in results[0]["metadata"]
        assert results[0]["metadata"]["gateway_rank"] == 1
        assert results[0]["metadata"]["gateway_score"] == 18.3
        assert results[0]["metadata"]["quality_ok"] is True

    @patch("httpx.AsyncClient")
    async def test_search_with_title_in_response(self, mock_async_client):
        """Test search uses title from response when available."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "ok": True,
            "qualityOk": True,
            "results": [
                {
                    "rank": 1,
                    "score": 18.3,
                    "url": "https://www.newzimbabwe.com",
                    "title": "New Zimbabwe News",
                },
            ],
        }
        
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_async_client.return_value = mock_client
        
        provider = AppsScriptSearchProvider(base_url="https://script.google.com/macros/s/TEST/exec")
        results = await provider.search("Zimbabwe")
        
        assert len(results) == 1
        assert results[0]["title"] == "New Zimbabwe News"

    @patch("httpx.AsyncClient")
    async def test_search_respects_max_results(self, mock_async_client):
        """Test search respects max_results parameter."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "ok": True,
            "results": [
                {"rank": i, "score": 10.0, "url": f"https://example.com/{i}"}
                for i in range(100)
            ],
        }
        
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_async_client.return_value = mock_client
        
        provider = AppsScriptSearchProvider(base_url="https://script.google.com/macros/s/TEST/exec")
        results = await provider.search("test", max_results=5)
        
        assert len(results) == 5

    @patch("httpx.AsyncClient")
    async def test_search_empty_results_list(self, mock_async_client):
        """Test empty results list returns empty results."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "ok": True,
            "qualityOk": False,
            "count": 0,
            "results": [],
        }
        
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_async_client.return_value = mock_client
        
        provider = AppsScriptSearchProvider(base_url="https://script.google.com/macros/s/TEST/exec")
        results = await provider.search("test")
        
        assert results == []

    @patch("httpx.AsyncClient")
    async def test_search_gateway_ok_false_returns_empty(self, mock_async_client):
        """Test gateway ok:false returns empty results."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "ok": False,
            "error": "Search backend unavailable",
        }
        
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_async_client.return_value = mock_client
        
        provider = AppsScriptSearchProvider(base_url="https://script.google.com/macros/s/TEST/exec")
        results = await provider.search("test")
        
        assert results == []

    @patch("httpx.AsyncClient")
    async def test_search_missing_results_key_returns_empty(self, mock_async_client):
        """Test response missing 'results' key returns empty results."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True, "query": "test"}
        
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_async_client.return_value = mock_client
        
        provider = AppsScriptSearchProvider(base_url="https://script.google.com/macros/s/TEST/exec")
        results = await provider.search("test")
        
        assert results == []

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
        
        provider = AppsScriptSearchProvider(base_url="https://script.google.com/macros/s/TEST/exec")
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
        
        provider = AppsScriptSearchProvider(base_url="https://script.google.com/macros/s/TEST/exec")
        results = await provider.search("test")
        
        assert results == []

    @patch("httpx.AsyncClient")
    async def test_search_duplicate_urls_removed(self, mock_async_client):
        """Test duplicate URLs are removed from results."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "ok": True,
            "results": [
                {"rank": 1, "score": 18.3, "url": "https://example.com"},
                {"rank": 2, "score": 15.2, "url": "https://example.com"},
                {"rank": 3, "score": 10.0, "url": "https://example.org"},
            ],
        }
        
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_async_client.return_value = mock_client
        
        provider = AppsScriptSearchProvider(base_url="https://script.google.com/macros/s/TEST/exec")
        results = await provider.search("test")
        
        assert len(results) == 2
        urls = [r["url"] for r in results]
        assert "https://example.com" in urls
        assert "https://example.org" in urls

    @patch("httpx.AsyncClient")
    async def test_search_connect_error_returns_empty(self, mock_async_client):
        """Test connection error returns empty results."""
        import httpx
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.side_effect = httpx.ConnectError("Connection refused")
        mock_async_client.return_value = mock_client
        
        provider = AppsScriptSearchProvider(base_url="https://script.google.com/macros/s/TEST/exec")
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
        
        provider = AppsScriptSearchProvider(base_url="https://script.google.com/macros/s/TEST/exec")
        results = await provider.search("test")
        
        assert results == []

    @patch("httpx.AsyncClient")
    async def test_search_url_encoding(self, mock_async_client):
        """Test query is properly URL-encoded."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True, "results": []}
        
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_async_client.return_value = mock_client
        
        provider = AppsScriptSearchProvider(base_url="https://script.google.com/macros/s/TEST/exec")
        await provider.search("African Development Bank & Group")
        
        mock_client.get.assert_called_once()
        call_args = mock_client.get.call_args
        url = call_args[0][0]
        assert "African+Development+Bank+%26+Group" in url or "African%20Development%20Bank%20%26%20Group" in url

    @patch("httpx.AsyncClient")
    async def test_search_preserves_all_metadata(self, mock_async_client):
        """Test that all gateway metadata is preserved."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "ok": True,
            "qualityOk": True,
            "query": "Zimbabwe",
            "count": 10,
            "results": [
                {"rank": 1, "score": 18.3, "url": "https://www.newzimbabwe.com"},
            ],
            "diagnostics": {},
            "rawCandidateCount": 100,
            "qualityCount": 50,
        }
        
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_async_client.return_value = mock_client
        
        provider = AppsScriptSearchProvider(base_url="https://script.google.com/macros/s/TEST/exec")
        results = await provider.search("Zimbabwe")
        
        assert len(results) == 1
        metadata = results[0]["metadata"]
        assert metadata["gateway_rank"] == 1
        assert metadata["gateway_score"] == 18.3
        assert metadata["quality_ok"] is True
        assert metadata["raw_candidate_count"] == 100
        assert metadata["quality_count"] == 50

    @patch("httpx.AsyncClient")
    async def test_search_with_zimbabwe_example(self, mock_async_client):
        """Test with the real Zimbabwe example from requirements."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "ok": True,
            "qualityOk": True,
            "query": "Zimbabwe",
            "count": 10,
            "results": [
                {"rank": 1, "score": 18.3, "url": "https://www.newzimbabwe.com"},
                {"rank": 2, "score": 17.5, "url": "https://zimbabwetourism.net/en"},
                {"rank": 3, "score": 16.8, "url": "https://en.wikipedia.org/wiki/Zimbabwe"},
                {"rank": 4, "score": 16.2, "url": "https://www.britannica.com/place/Zimbabwe"},
                {"rank": 5, "score": 15.9, "url": "https://www.britannica.com/topic/history-of-Zimbabwe"},
                {"rank": 6, "score": 15.5, "url": "https://www.worldatlas.com/maps/zimbabwe"},
                {"rank": 7, "score": 15.2, "url": "https://countries.world/africa/zimbabwe"},
                {"rank": 8, "score": 14.8, "url": "https://www.countryreports.org/country/Zimbabwe"},
                {"rank": 9, "score": 14.5, "url": "https://en.wikipedia.org/wiki/History_of_Zimbabwe"},
                {"rank": 10, "score": 14.2, "url": "https://www.pindula.co.zw/Zimbabwe"},
            ],
            "diagnostics": {},
            "rawCandidateCount": 10,
            "qualityCount": 10,
        }
        
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_async_client.return_value = mock_client
        
        provider = AppsScriptSearchProvider(base_url="https://script.google.com/macros/s/TEST/exec")
        results = await provider.search("Zimbabwe")
        
        assert len(results) == 10
        expected_urls = [
            "https://www.newzimbabwe.com",
            "https://zimbabwetourism.net/en",
            "https://en.wikipedia.org/wiki/Zimbabwe",
            "https://www.britannica.com/place/Zimbabwe",
            "https://www.britannica.com/topic/history-of-Zimbabwe",
            "https://www.worldatlas.com/maps/zimbabwe",
            "https://countries.world/africa/zimbabwe",
            "https://www.countryreports.org/country/Zimbabwe",
            "https://en.wikipedia.org/wiki/History_of_Zimbabwe",
            "https://www.pindula.co.zw/Zimbabwe",
        ]
        actual_urls = [r["url"] for r in results]
        for expected_url in expected_urls:
            assert expected_url in actual_urls
