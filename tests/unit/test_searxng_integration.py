"""Integration tests for SearXNGProvider within the search orchestrator."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.research.search_orchestrator import SearchOrchestrator, ProviderStatus
from app.services.research.searxng_provider import SearXNGProvider


class TestSearXNGIntegration:
    """Tests for SearXNGProvider integration with SearchOrchestrator."""

    @patch("httpx.AsyncClient")
    async def test_searxng_in_orchestrator(self, mock_async_client):
        """Test SearXNGProvider works within SearchOrchestrator."""
        # Create mock response for SearXNG
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
                },
            ],
        }
        
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_async_client.return_value = mock_client
        
        # Create orchestrator with SearXNG as primary provider
        searxng_provider = SearXNGProvider()
        orchestrator = SearchOrchestrator(
            providers=[searxng_provider],
            min_evidence=1,
            timeout_per_provider=15.0,
        )
        
        # Run search
        result = await orchestrator.search("African Development Bank", max_results=5)
        
        # Verify SearXNG was called and returned results
        assert len(result.provider_results) == 1
        assert result.provider_results[0].provider_name == "SearXNGProvider"
        assert result.provider_results[0].status == ProviderStatus.SUCCESS
        assert result.provider_results[0].results_returned >= 1
        assert len(result.search_results_total) >= 1

    @patch("httpx.AsyncClient")
    async def test_searxng_failure_in_orchestrator(self, mock_async_client):
        """Test SearXNGProvider failure is handled gracefully in orchestrator."""
        import httpx
        
        # Mock SearXNG connection error
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.side_effect = httpx.ConnectError("Connection refused")
        mock_async_client.return_value = mock_client
        
        # Create orchestrator with SearXNG as primary provider
        searxng_provider = SearXNGProvider()
        orchestrator = SearchOrchestrator(
            providers=[searxng_provider],
            min_evidence=1,
            timeout_per_provider=15.0,
        )
        
        # Run search
        result = await orchestrator.search("African Development Bank", max_results=5)
        
        # Verify SearXNG failed but orchestrator didn't crash
        assert len(result.provider_results) == 1
        assert result.provider_results[0].provider_name == "SearXNGProvider"
        assert result.provider_results[0].status == ProviderStatus.FAILED
        assert result.provider_results[0].results_returned == 0

    @patch("httpx.AsyncClient")
    async def test_searxng_empty_results_in_orchestrator(self, mock_async_client):
        """Test SearXNGProvider with empty results in orchestrator."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": []}
        
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_async_client.return_value = mock_client
        
        searxng_provider = SearXNGProvider()
        orchestrator = SearchOrchestrator(
            providers=[searxng_provider],
            min_evidence=1,
            timeout_per_provider=15.0,
        )
        
        result = await orchestrator.search("test", max_results=5)
        
        assert len(result.provider_results) == 1
        assert result.provider_results[0].status == ProviderStatus.SUCCESS
        assert result.provider_results[0].results_returned == 0

    @patch("httpx.AsyncClient")
    async def test_searxng_with_other_providers(self, mock_async_client):
        """Test SearXNGProvider works alongside other providers."""
        # Mock SearXNG response
        searxng_response = MagicMock()
        searxng_response.status_code = 200
        searxng_response.json.return_value = {
            "results": [
                {
                    "title": "SearXNG Result",
                    "url": "https://searxng-result.com",
                    "content": "From SearXNG",
                    "engine": "wikipedia",
                },
            ],
        }
        
        # Mock Mozilla response
        mozilla_response = MagicMock()
        mozilla_response.status_code = 200
        mozilla_response.json.return_value = {
            "results": [
                {
                    "title": "Mozilla Result",
                    "url": "https://mozilla-result.com",
                    "snippet": "From Mozilla",
                },
            ],
        }
        
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        
        # SearXNG call first, then Mozilla
        mock_client.get.side_effect = [searxng_response, mozilla_response]
        mock_async_client.return_value = mock_client
        
        from app.services.research.mozilla_provider import MozillaProvider
        
        searxng_provider = SearXNGProvider()
        mozilla_provider = MozillaProvider()
        
        orchestrator = SearchOrchestrator(
            providers=[searxng_provider, mozilla_provider],
            min_evidence=1,
            timeout_per_provider=15.0,
            max_concurrent_providers=2,
        )
        
        result = await orchestrator.search("test", max_results=5)
        
        # Both providers should succeed
        assert len(result.provider_results) == 2
        provider_names = [p.provider_name for p in result.provider_results]
        assert "SearXNGProvider" in provider_names
        assert "MozillaProvider" in provider_names
        
        # At least one provider succeeded
        succeeded = [p for p in result.provider_results if p.status == ProviderStatus.SUCCESS]
        assert len(succeeded) >= 1

    @patch("httpx.AsyncClient")
    async def test_searxng_query_construction(self, mock_async_client):
        """Test SearXNGProvider constructs correct query URL."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": []}
        
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_async_client.return_value = mock_client
        
        provider = SearXNGProvider(base_url="https://test-searxng.example.com")
        await provider.search("test query")
        
        # Verify the URL was constructed correctly
        mock_client.get.assert_called_once()
        call_args = mock_client.get.call_args
        url = call_args[0][0]
        assert url == "https://test-searxng.example.com/search?q=test+query&format=json"

    @patch("httpx.AsyncClient")
    async def test_searxng_context_parameter(self, mock_async_client):
        """Test SearXNGProvider accepts context parameter."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": []}
        
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_async_client.return_value = mock_client
        
        provider = SearXNGProvider()
        # Should not raise even with context
        results = await provider.search("test", context={"entity_type": "organization"})
        assert results == []

    @patch("httpx.AsyncClient")
    async def test_searxng_max_results_parameter(self, mock_async_client):
        """Test SearXNGProvider respects max_results parameter."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {"title": f"Result {i}", "url": f"https://example.com/{i}", "content": "", "engine": "test"}
                for i in range(100)
            ],
        }
        
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_async_client.return_value = mock_client
        
        provider = SearXNGProvider()
        results = await provider.search("test", max_results=3)
        
        assert len(results) == 3

    @patch("httpx.AsyncClient")
    async def test_searxng_timeout_parameter(self, mock_async_client):
        """Test SearXNGProvider respects timeout parameter."""
        import httpx
        
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.side_effect = httpx.TimeoutException("Request timed out")
        mock_async_client.return_value = mock_client
        
        provider = SearXNGProvider(timeout=5.0)
        results = await provider.search("test")
        
        assert results == []
        # Verify timeout was passed to client
        mock_client.get.assert_called_once()
        call_kwargs = mock_client.get.call_args[1]
        assert call_kwargs["timeout"] == 5.0
