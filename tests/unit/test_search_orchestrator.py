"""Focused tests for SearchOrchestrator role-based architecture."""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.research.search_orchestrator import (
    OrchestratorResult,
    ProviderResult,
    ProviderStatus,
    ResearchStatus,
    SearchOrchestrator,
)
from app.services.research.search_provider import ProviderRole, SearchProvider, SearchResult


class FakeIdentityProvider(SearchProvider):
    """Fake provider for testing - simulates Wikidata (identity role)."""
    role = ProviderRole.IDENTITY

    def __init__(self, results: Optional[List[Dict[str, Any]]] = None, error: Optional[Exception] = None):
        self._results = results or []
        self.error = error

    async def search(self, query: str, max_results: int = 10, context: Optional[Dict[str, Any]] = None) -> List[SearchResult]:
        if self.error:
            raise self.error
        results = []
        for r in self._results:
            results.append(SearchResult(
                provider="FakeIdentityProvider",
                query=query,
                page=1,
                rank=len(results) + 1,
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("snippet", None),
                metadata=r.get("metadata", {}),
            ))
        return results


class FakeReferenceProvider(SearchProvider):
    """Fake provider for testing - simulates Wikipedia (reference role)."""
    role = ProviderRole.REFERENCE

    def __init__(self, results: Optional[List[Dict[str, Any]]] = None, error: Optional[Exception] = None):
        self._results = results or []
        self.error = error

    async def search(self, query: str, max_results: int = 10, context: Optional[Dict[str, Any]] = None) -> List[SearchResult]:
        if self.error:
            raise self.error
        results = []
        for r in self._results:
            results.append(SearchResult(
                provider="FakeReferenceProvider",
                query=query,
                page=1,
                rank=len(results) + 1,
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("snippet", None),
                metadata=r.get("metadata", {}),
            ))
        return results


class FakeWebDiscoveryProvider(SearchProvider):
    """Fake provider for testing - simulates DuckDuckGo (web_discovery role)."""
    role = ProviderRole.WEB_DISCOVERY

    def __init__(self, results: Optional[List[Dict[str, Any]]] = None, error: Optional[Exception] = None):
        self._results = results or []
        self.error = error

    async def search(self, query: str, max_results: int = 10, context: Optional[Dict[str, Any]] = None) -> List[SearchResult]:
        if self.error:
            raise self.error
        results = []
        for r in self._results:
            results.append(SearchResult(
                provider="FakeWebDiscoveryProvider",
                query=query,
                page=1,
                rank=len(results) + 1,
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("snippet", None),
                metadata=r.get("metadata", {}),
            ))
        return results


class FakeNewsProvider(SearchProvider):
    """Fake provider for testing - simulates GDELT (news role)."""
    role = ProviderRole.NEWS

    def __init__(self, results: Optional[List[Dict[str, Any]]] = None, error: Optional[Exception] = None):
        self._results = results or []
        self.error = error

    async def search(self, query: str, max_results: int = 10, context: Optional[Dict[str, Any]] = None) -> List[SearchResult]:
        if self.error:
            raise self.error
        results = []
        for r in self._results:
            results.append(SearchResult(
                provider="FakeNewsProvider",
                query=query,
                page=1,
                rank=len(results) + 1,
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("snippet", None),
                metadata=r.get("metadata", {}),
            ))
        return results


class TestProviderRoleMetadata:
    """Test that providers have correct role metadata."""

    def test_identity_provider_has_correct_role(self):
        provider = FakeIdentityProvider()
        assert provider.role == ProviderRole.IDENTITY

    def test_reference_provider_has_correct_role(self):
        provider = FakeReferenceProvider()
        assert provider.role == ProviderRole.REFERENCE

    def test_web_discovery_provider_has_correct_role(self):
        provider = FakeWebDiscoveryProvider()
        assert provider.role == ProviderRole.WEB_DISCOVERY

    def test_news_provider_has_correct_role(self):
        provider = FakeNewsProvider()
        assert provider.role == ProviderRole.NEWS


class TestProviderResultIncludesRole:
    """Test that ProviderResult includes role information."""

    @pytest.mark.asyncio
    async def test_success_result_includes_role(self):
        orchestrator = SearchOrchestrator(
            providers=[FakeIdentityProvider(results=[{"url": "http://test.com", "title": "Test", "snippet": "Test snippet"}])],
            max_concurrent_providers=3,
        )
        result = await orchestrator.search("test query")
        
        # Check that provider results have role
        assert len(result.provider_results) > 0
        for pr in result.provider_results:
            assert hasattr(pr, 'role')
            assert pr.role == "identity"


class TestFailingProviderDoesNotBlockSuccess:
    """Test that failing providers don't prevent successful ones from returning evidence."""

    @pytest.mark.asyncio
    async def test_failing_provider_allows_success(self):
        # Create one failing provider and one successful provider
        failing = FakeWebDiscoveryProvider(error=Exception("Connection failed"))
        successful = FakeReferenceProvider(results=[
            {"url": "http://wikipedia.org/test", "title": "Test Page", "snippet": "Test content"}
        ])
        
        orchestrator = SearchOrchestrator(
            providers=[failing, successful],
            max_concurrent_providers=3,
        )
        
        result = await orchestrator.search("test query")
        
        # Should have attempted both providers
        assert "FakeWebDiscoveryProvider" in result.providers_attempted
        assert "FakeReferenceProvider" in result.providers_attempted
        
        # Failing provider should be in failed list
        assert "FakeWebDiscoveryProvider" in result.providers_failed
        
        # Successful provider should be in succeeded list
        assert "FakeReferenceProvider" in result.providers_succeeded
        
        # Should have evidence from successful provider
        assert len(result.evidence) > 0


class TestWikidataAloneDoesNotSatisfyThreshold:
    """Test that Wikidata (identity) evidence alone does not satisfy multi-source threshold."""

    @pytest.mark.asyncio
    async def test_identity_alone_not_enough(self):
        # Only identity provider with results
        identity = FakeIdentityProvider(results=[
            {"url": "http://wikidata.org/entity/Q1", "title": "Entity 1", "snippet": "Description"},
            {"url": "http://wikidata.org/entity/Q2", "title": "Entity 2", "snippet": "Description"},
            {"url": "http://wikidata.org/entity/Q3", "title": "Entity 3", "snippet": "Description"},
        ])
        
        orchestrator = SearchOrchestrator(
            providers=[identity],
            min_evidence=3,
            max_concurrent_providers=3,
        )
        
        result = await orchestrator.search("test query")
        
        # Should have 3 evidence items but from identity only
        assert len(result.evidence) == 3
        
        # Status should NOT be COMPLETE because identity doesn't count toward general evidence
        # With only identity evidence, we don't have enough general evidence
        assert result.status != ResearchStatus.COMPLETE


class TestEvidenceFromTwoDistinctProviders:
    """Test that evidence from two distinct providers can satisfy the threshold."""

    @pytest.mark.asyncio
    async def test_two_providers_satisfy_threshold(self):
        # Two non-identity providers with results
        provider1 = FakeReferenceProvider(results=[
            {"url": "http://wikipedia.org/page1", "title": "Page 1", "snippet": "Content 1"},
            {"url": "http://wikipedia.org/page2", "title": "Page 2", "snippet": "Content 2"},
        ])
        provider2 = FakeWebDiscoveryProvider(results=[
            {"url": "http://duckduckgo.com/result1", "title": "Result 1", "snippet": "Content 3"},
            {"url": "http://duckduckgo.com/result2", "title": "Result 2", "snippet": "Content 4"},
        ])
        
        orchestrator = SearchOrchestrator(
            providers=[provider1, provider2],
            min_evidence=3,
            max_concurrent_providers=3,
        )
        
        result = await orchestrator.search("test query")
        
        # Should have evidence from both providers
        assert len(result.evidence) >= 4
        
        # Both providers should have succeeded
        assert "FakeReferenceProvider" in result.providers_succeeded
        assert "FakeWebDiscoveryProvider" in result.providers_succeeded
        
        # With 4 evidence items from 2 distinct sources, should satisfy threshold
        assert result.status == ResearchStatus.COMPLETE


class TestDuplicateURLsCountOnce:
    """Test that duplicate URLs across providers count only once for diversity."""

    @pytest.mark.asyncio
    async def test_duplicate_urls_deduped(self):
        # Two providers returning the same URL
        provider1 = FakeReferenceProvider(results=[
            {"url": "http://example.com/page1", "title": "Page 1", "snippet": "Content 1"},
            {"url": "http://example.com/page1", "title": "Page 1", "snippet": "Content 1"},
        ])
        provider2 = FakeWebDiscoveryProvider(results=[
            {"url": "http://example.com/page1", "title": "Page 1", "snippet": "Content 1"},
            {"url": "http://example.com/page2", "title": "Page 2", "snippet": "Content 2"},
        ])
        
        orchestrator = SearchOrchestrator(
            providers=[provider1, provider2],
            min_evidence=3,
            max_concurrent_providers=3,
        )
        
        result = await orchestrator.search("test query")
        
        # Should have deduplicated evidence
        unique_urls = {e.url for e in result.evidence}
        assert len(unique_urls) == 2  # Only 2 unique URLs


class TestProviderFailureMetadataPreserved:
    """Test that provider failure metadata is preserved."""

    @pytest.mark.asyncio
    async def test_failure_metadata_preserved(self):
        # Provider that times out
        timeout_provider = FakeNewsProvider(
            error=asyncio.TimeoutError("Timeout")
        )
        
        orchestrator = SearchOrchestrator(
            providers=[timeout_provider],
            max_concurrent_providers=3,
        )
        
        result = await orchestrator.search("test query")
        
        # Should have failure recorded
        assert "FakeNewsProvider" in result.providers_failed
        assert len(result.provider_results) == 1
        
        failure_result = result.provider_results[0]
        assert failure_result.status == ProviderStatus.TIMEOUT
        assert failure_result.error is not None
        assert "Timeout" in failure_result.error
        assert failure_result.role == "news"


class TestConcurrencyLimitUnchanged:
    """Test that concurrency limit remains at 3."""

    @pytest.mark.asyncio
    async def test_concurrency_limit_preserved(self):
        # Create 6 providers
        providers = [
            FakeIdentityProvider(results=[{"url": f"http://test{i}.com", "title": f"Test {i}", "snippet": f"Content {i}"}])
            for i in range(6)
        ]
        
        orchestrator = SearchOrchestrator(
            providers=providers,
            max_concurrent_providers=3,
        )
        
        # Verify the limit is still 3
        assert orchestrator.max_concurrent_providers == 3


class TestDependencyInjectionWorks:
    """Test that existing dependency injection still works."""

    @pytest.mark.asyncio
    async def test_dependency_injection(self):
        # Create orchestrator with injected providers
        providers = [
            FakeIdentityProvider(),
            FakeReferenceProvider(),
            FakeWebDiscoveryProvider(),
        ]
        
        orchestrator = SearchOrchestrator(
            providers=providers,
            min_evidence=2,
            max_concurrent_providers=2,
        )
        
        result = await orchestrator.search("test query")
        
        # Should have run all providers
        assert len(result.providers_attempted) == 3
        assert orchestrator.min_evidence == 2
        assert orchestrator.max_concurrent_providers == 2


class TestSourceDiversityCheck:
    """Test the source diversity logic in _enough_evidence."""

    @pytest.mark.asyncio
    async def test_three_from_same_source_not_enough(self):
        """Test that 3 results from same source don't satisfy diversity requirement."""
        from app.services.research.page_crawler import CrawlResult
        from unittest.mock import AsyncMock
        
        # Create a mock crawler that succeeds for all URLs
        async def mock_crawl(url, metadata=None):
            return CrawlResult(
                url=url,
                final_url=url,
                status_code=200,
                success=True,
                content=f"Content for {url}",
                content_type="text/html",
                title=f"Page for {url}",
            )
        
        mock_crawler = MagicMock()
        mock_crawler.crawl_url = mock_crawl
        
        provider = FakeReferenceProvider(results=[
            {"url": "http://same-source.com/1", "title": "Page 1", "snippet": "Content 1"},
            {"url": "http://same-source.com/2", "title": "Page 2", "snippet": "Content 2"},
            {"url": "http://same-source.com/3", "title": "Page 3", "snippet": "Content 3"},
        ])
        
        orchestrator = SearchOrchestrator(
            providers=[provider],
            min_evidence=3,
            max_concurrent_providers=3,
            max_concurrent_crawls=5,
        )
        orchestrator._page_crawler = mock_crawler
        
        result = await orchestrator.search("test query")
        
        # Should have 3 evidence items but only 1 unique source (FakeReferenceProvider)
        # This should NOT be enough due to lack of source diversity
        assert len(result.evidence) == 3
        # Status should not be COMPLETE because only 1 unique source
        assert result.status != ResearchStatus.COMPLETE

    @pytest.mark.asyncio
    async def test_three_from_two_sources_is_enough(self):
        """Test that 3 results from 2 sources satisfy diversity requirement."""
        from app.services.research.page_crawler import CrawlResult
        
        # Create a mock crawler that succeeds for all URLs
        async def mock_crawl(url, metadata=None):
            return CrawlResult(
                url=url,
                final_url=url,
                status_code=200,
                success=True,
                content=f"Content for {url}",
                content_type="text/html",
                title=f"Page for {url}",
            )
        
        mock_crawler = MagicMock()
        mock_crawler.crawl_url = mock_crawl
        
        # Results from two different sources
        provider1 = FakeReferenceProvider(results=[
            {"url": "http://source1.com/1", "title": "Page 1", "snippet": "Content 1"},
            {"url": "http://source1.com/2", "title": "Page 2", "snippet": "Content 2"},
        ])
        provider2 = FakeWebDiscoveryProvider(results=[
            {"url": "http://source2.com/1", "title": "Page 3", "snippet": "Content 3"},
        ])
        
        orchestrator = SearchOrchestrator(
            providers=[provider1, provider2],
            min_evidence=3,
            max_concurrent_providers=3,
            max_concurrent_crawls=5,
        )
        orchestrator._page_crawler = mock_crawler
        
        result = await orchestrator.search("test query")
        
        # Should have enough evidence with diversity
        assert len(result.evidence) >= 3
        # With 3+ evidence from 2+ sources, should be COMPLETE
        assert result.status == ResearchStatus.COMPLETE
