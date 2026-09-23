"""Comprehensive tests for full first-page crawling architecture (Step 17).

These tests verify the core functionality without requiring network access.
"""
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
from app.services.research.evidence import EvidenceRecord
from app.services.research.page_crawler import CrawlResult, PageCrawler


# =============================================================================
# Fake Providers for Testing
# =============================================================================

class FakeSearchProvider(SearchProvider):
    """Generic fake search provider for testing."""
    
    role = ProviderRole.WEB_DISCOVERY
    
    def __init__(
        self,
        name: str = "FakeSearchProvider",
        results: Optional[List[SearchResult]] = None,
        error: Optional[Exception] = None,
        delay: float = 0.0,
    ):
        self.name = name
        self._results = results or []
        self._error = error
        self._delay = delay
    
    async def search(
        self,
        query: str,
        max_results: int = 10,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        if self._error:
            raise self._error
        if self._delay:
            await asyncio.sleep(self._delay)
        # Set the provider name on each result
        results = []
        for r in self._results:
            r_copy = SearchResult(
                provider=self.name,
                query=r.query,
                page=r.page,
                rank=r.rank,
                title=r.title,
                url=r.url,
                snippet=r.snippet,
                metadata=r.metadata,
            )
            results.append(r_copy)
        return results


class FakeIdentityProvider(SearchProvider):
    """Fake identity provider (Wikidata-like)."""
    
    role = ProviderRole.IDENTITY
    
    def __init__(
        self,
        results: Optional[List[SearchResult]] = None,
        error: Optional[Exception] = None,
        official_website: Optional[str] = None,
    ):
        self._results = results or []
        self._error = error
        self._official_website = official_website
    
    async def search(
        self,
        query: str,
        max_results: int = 10,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        if self._error:
            raise self._error
        
        results = []
        for r in self._results:
            r_copy = SearchResult(
                provider="FakeIdentityProvider",
                query=query,
                page=r.page,
                rank=r.rank,
                title=r.title,
                url=r.url,
                snippet=r.snippet,
                metadata=r.metadata,
            )
            results.append(r_copy)
        
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


# =============================================================================
# Helper to create mock crawler
# =============================================================================

def create_mock_crawler(success_urls=None, fail_urls=None):
    """Create a mock page crawler for testing."""
    success_urls = success_urls or []
    fail_urls = fail_urls or []
    
    async def mock_crawl(url, metadata=None):
        if url in fail_urls:
            return CrawlResult(
                url=url,
                final_url="",
                status_code=0,
                success=False,
                content="",
                content_type="",
                title="",
                error="Simulated crawl error",
            )
        return CrawlResult(
            url=url,
            final_url=url,
            status_code=200,
            success=True,
            content=f"Page content for {url}",
            content_type="text/html",
            title=f"Title for {url}",
        )
    
    mock_crawler = MagicMock()
    mock_crawler.crawl_url = mock_crawl
    return mock_crawler


# =============================================================================
# Simplified Tests
# =============================================================================

class TestProviderInterface:
    """Test that providers return SearchResult objects."""
    
    @pytest.mark.asyncio
    async def test_provider_returns_search_results(self):
        provider = FakeSearchProvider(
            name="TestProvider",
            results=[
                SearchResult(
                    provider="TestProvider",
                    query="test query",
                    page=1,
                    rank=1,
                    title="Test Title",
                    url="https://example.com/test",
                    snippet="Test snippet",
                ),
            ],
        )
        
        results = await provider.search("test query")
        assert len(results) == 1
        assert isinstance(results[0], SearchResult)
        assert results[0].provider == "TestProvider"


class TestMultiProvider:
    """Test multi-provider orchestration."""
    
    @pytest.mark.asyncio
    async def test_orchestrator_queries_all_providers(self):
        mock_crawler = create_mock_crawler()
        
        # Create distinct provider classes
        class Provider1(FakeSearchProvider):
            role = ProviderRole.WEB_DISCOVERY
            def __init__(self):
                super().__init__(name="Provider1", results=[
                    SearchResult(provider="Provider1", query="q", page=1, rank=1, 
                               title="T1", url="http://p1.com/1")
                ])
        
        class Provider2(FakeSearchProvider):
            role = ProviderRole.WEB_DISCOVERY
            def __init__(self):
                super().__init__(name="Provider2", results=[
                    SearchResult(provider="Provider2", query="q", page=1, rank=1, 
                               title="T2", url="http://p2.com/1")
                ])
        
        providers = [Provider1(), Provider2()]
        
        orchestrator = SearchOrchestrator(
            providers=providers,
            max_concurrent_providers=3,
            max_concurrent_crawls=5,
        )
        orchestrator._page_crawler = mock_crawler
        
        result = await orchestrator.search("test query")
        
        assert len(result.providers_attempted) == 2
        assert "Provider1" in result.providers_attempted
        assert "Provider2" in result.providers_attempted


class TestURLDeduplication:
    """Test URL deduplication."""
    
    @pytest.mark.asyncio
    async def test_duplicate_urls_deduped(self):
        mock_crawler = create_mock_crawler()
        
        providers = [
            FakeSearchProvider(
                results=[
                    SearchResult(provider="P1", query="q", page=1, rank=1, 
                               title="T1", url="http://example.com/page1"),
                    SearchResult(provider="P1", query="q", page=1, rank=2, 
                               title="T2", url="http://example.com/page2"),
                ],
            ),
            FakeSearchProvider(
                results=[
                    SearchResult(provider="P2", query="q", page=1, rank=1, 
                               title="T1", url="http://example.com/page1"),  # Duplicate
                    SearchResult(provider="P2", query="q", page=1, rank=2, 
                               title="T3", url="http://example.com/page3"),
                ],
            ),
        ]
        
        orchestrator = SearchOrchestrator(
            providers=providers,
            max_concurrent_providers=3,
            max_concurrent_crawls=5,
        )
        orchestrator._page_crawler = mock_crawler
        
        result = await orchestrator.search("q")
        
        assert result.unique_urls_discovered == 3


class TestFullCrawl:
    """Test full first-page crawl."""
    
    @pytest.mark.asyncio
    async def test_all_urls_crawled(self):
        mock_crawler = create_mock_crawler()
        
        providers = [
            FakeSearchProvider(
                results=[
                    SearchResult(provider="P1", query="q", page=1, rank=1, 
                               title="T1", url="http://test.com/a"),
                    SearchResult(provider="P1", query="q", page=1, rank=2, 
                               title="T2", url="http://test.com/b"),
                ],
            ),
            FakeSearchProvider(
                results=[
                    SearchResult(provider="P2", query="q", page=1, rank=1, 
                               title="T3", url="http://test.com/c"),
                ],
            ),
        ]
        
        orchestrator = SearchOrchestrator(
            providers=providers,
            max_concurrent_providers=3,
            max_concurrent_crawls=5,
        )
        orchestrator._page_crawler = mock_crawler
        
        result = await orchestrator.search("q")
        
        assert result.unique_urls_discovered == 3
        assert result.urls_crawl_attempted == 3
        assert result.urls_crawl_succeeded == 3


class TestProvenance:
    """Test provenance preservation."""
    
    @pytest.mark.asyncio
    async def test_crawl_preserves_provider(self):
        mock_crawler = create_mock_crawler()
        
        providers = [
            FakeSearchProvider(
                results=[
                    SearchResult(provider="P1", query="q", page=1, rank=1, 
                               title="T", url="http://test.com/page"),
                ],
            ),
        ]
        
        orchestrator = SearchOrchestrator(
            providers=providers,
            max_concurrent_providers=3,
            max_concurrent_crawls=5,
        )
        orchestrator._page_crawler = mock_crawler
        
        result = await orchestrator.search("q")
        
        assert len(result.evidence) >= 1
        for evidence in result.evidence:
            if evidence.metadata:
                assert "discovery" in evidence.metadata


class TestFailureHandling:
    """Test failure handling."""
    
    @pytest.mark.asyncio
    async def test_failed_url_does_not_stop_others(self):
        mock_crawler = create_mock_crawler(
            fail_urls=["http://test.com/fail"],
        )
        
        providers = [
            FakeSearchProvider(
                results=[
                    SearchResult(provider="P1", query="q", page=1, rank=1, 
                               title="Fail", url="http://test.com/fail"),
                    SearchResult(provider="P1", query="q", page=1, rank=2, 
                               title="Success1", url="http://test.com/success1"),
                    SearchResult(provider="P1", query="q", page=1, rank=3, 
                               title="Success2", url="http://test.com/success2"),
                ],
            ),
        ]
        
        orchestrator = SearchOrchestrator(
            providers=providers,
            max_concurrent_providers=3,
            max_concurrent_crawls=5,
        )
        orchestrator._page_crawler = mock_crawler
        
        result = await orchestrator.search("q")
        
        assert result.urls_crawl_attempted == 3
        assert result.urls_crawl_failed >= 1
        assert len(result.evidence) >= 2  # At least 2 should succeed


class TestMetrics:
    """Test observability metrics."""
    
    @pytest.mark.asyncio
    async def test_metrics_tracked(self):
        mock_crawler = create_mock_crawler()
        
        providers = [
            FakeSearchProvider(
                results=[
                    SearchResult(provider="P1", query="q", page=1, rank=1, 
                               title="T1", url="http://test.com/a"),
                    SearchResult(provider="P1", query="q", page=1, rank=2, 
                               title="T2", url="http://test.com/b"),
                ],
            ),
            FakeSearchProvider(
                results=[
                    SearchResult(provider="P2", query="q", page=1, rank=1, 
                               title="T3", url="http://test.com/c"),
                ],
            ),
        ]
        
        orchestrator = SearchOrchestrator(
            providers=providers,
            max_concurrent_providers=3,
            max_concurrent_crawls=5,
        )
        orchestrator._page_crawler = mock_crawler
        
        result = await orchestrator.search("q")
        
        assert hasattr(result, 'search_results_total')
        assert hasattr(result, 'unique_urls_discovered')
        assert hasattr(result, 'urls_crawl_attempted')
        assert hasattr(result, 'urls_crawl_succeeded')
        assert hasattr(result, 'evidence_records_created')


class TestWikidataBehavior:
    """Test Wikidata behavior preservation."""
    
    @pytest.mark.asyncio
    async def test_wikidata_identity_does_not_count_toward_threshold(self):
        mock_crawler = create_mock_crawler()
        
        wikidata = FakeIdentityProvider(
            results=[
                SearchResult(
                    provider="FakeIdentityProvider",
                    query="test",
                    page=1,
                    rank=1,
                    title="Entity 1",
                    url="https://wikidata.org/wiki/Q1",
                    snippet="Description",
                ),
                SearchResult(
                    provider="FakeIdentityProvider",
                    query="test",
                    page=1,
                    rank=2,
                    title="Entity 2",
                    url="https://wikidata.org/wiki/Q2",
                    snippet="Description",
                ),
                SearchResult(
                    provider="FakeIdentityProvider",
                    query="test",
                    page=1,
                    rank=3,
                    title="Entity 3",
                    url="https://wikidata.org/wiki/Q3",
                    snippet="Description",
                ),
            ],
        )
        
        orchestrator = SearchOrchestrator(
            providers=[wikidata],
            min_evidence=3,
            max_concurrent_providers=3,
            max_concurrent_crawls=5,
        )
        orchestrator._page_crawler = mock_crawler
        
        result = await orchestrator.search("test")
        
        assert len(result.evidence) >= 3
        # Status should NOT be COMPLETE because identity doesn't count toward general evidence
        assert result.status != ResearchStatus.COMPLETE


class TestProviderFailure:
    """Test provider failure handling."""
    
    @pytest.mark.asyncio
    async def test_provider_failure_does_not_stop_pipeline(self):
        mock_crawler = create_mock_crawler()
        
        failing_provider = FakeSearchProvider(
            name="FailingProvider",
            error=Exception("Connection failed"),
        )
        
        working_provider = FakeSearchProvider(
            name="WorkingProvider",
            results=[
                SearchResult(provider="WorkingProvider", query="q", page=1, rank=1, 
                           title="T", url="http://test.com/page"),
            ],
        )
        
        orchestrator = SearchOrchestrator(
            providers=[failing_provider, working_provider],
            max_concurrent_providers=3,
            max_concurrent_crawls=5,
        )
        orchestrator._page_crawler = mock_crawler
        
        result = await orchestrator.search("q")
        
        assert "FailingProvider" in result.providers_attempted
        assert "WorkingProvider" in result.providers_attempted
        assert "FailingProvider" in result.providers_failed
        assert "WorkingProvider" in result.providers_succeeded
        assert len(result.evidence) >= 1


class TestCompleteFlow:
    """Integration test for complete flow."""
    
    @pytest.mark.asyncio
    async def test_complete_flow_with_multiple_providers(self):
        mock_crawler = create_mock_crawler()
        
        providers = [
            FakeIdentityProvider(
                results=[
                    SearchResult(
                        provider="FakeIdentityProvider",
                        query="ZERA",
                        page=1,
                        rank=1,
                        title="ZERA",
                        url="https://wikidata.org/wiki/Q123",
                        snippet="Zimbabwe Energy Regulatory Authority",
                        metadata={"official_website": "https://zera.co.zw"},
                    ),
                ],
            ),
            FakeSearchProvider(
                name="FakeWebDiscovery",
                results=[
                    SearchResult(
                        provider="FakeWebDiscovery",
                        query="ZERA",
                        page=1,
                        rank=1,
                        title="ZERA Official",
                        url="https://zera.co.zw",
                        snippet="Official website",
                    ),
                    SearchResult(
                        provider="FakeWebDiscovery",
                        query="ZERA",
                        page=1,
                        rank=2,
                        title="ZERA News",
                        url="https://news.co.zw/zera",
                        snippet="News",
                    ),
                ],
            ),
        ]
        
        orchestrator = SearchOrchestrator(
            providers=providers,
            max_concurrent_providers=3,
            max_concurrent_crawls=5,
        )
        orchestrator._page_crawler = mock_crawler
        
        result = await orchestrator.search("ZERA")
        
        assert len(result.providers_attempted) == 2
        assert result.unique_urls_discovered >= 2
        assert result.urls_crawl_attempted >= 2
        assert len(result.evidence) >= 1
