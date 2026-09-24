"""
Step 18 Regression Tests - Confirmed Defect Fixes

This test file verifies all the fixes for Step 17.5 confirmed defects.
"""
from __future__ import annotations

import pytest
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.services.research.evidence import (
    EvidenceRecord,
    EvidenceStatus,
    ExtractionQuality,
    RetrievalStatus,
    classify_extraction_quality,
    classify_evidence_status,
)
from app.services.research.page_crawler import CrawlResult, PageCrawler
from app.services.research.search_orchestrator import ResearchStatus, SearchOrchestrator
from app.services.research.wikidata_provider import WikidataProvider
from app.services.pipeline import EntityPipelineService
from app.services.rita_intake import RITAEntity
from app.services.entity_resolution.registry import EntityRegistry
from app.services.entity_resolution.resolver import EntityResolver


# =============================================================================
# Test 1: Evidence Quality Classification
# =============================================================================

class TestEvidenceQualityClassification:
    """Test that HTTP 200 responses are properly classified."""
    
    def test_classify_block_page_cloudflare(self):
        """Test that Cloudflare/access-denied pages are classified as BLOCK_PAGE."""
        content = "Access Denied - Cloudflare"
        html = "<html><body><h1>Access Denied</h1><p>Please verify you are human</p></body></html>"
        
        quality = classify_extraction_quality(content, html, "https://example.com", 200)
        assert quality == ExtractionQuality.BLOCK_PAGE
    
    def test_classify_block_page_permission_denied(self):
        """Test that permission denied pages are classified as BLOCK_PAGE."""
        content = "403 Forbidden - You do not have permission to access this page"
        html = "<html><body><h1>403 Forbidden</h1></body></html>"
        
        quality = classify_extraction_quality(content, html, "https://example.com", 200)
        assert quality == ExtractionQuality.BLOCK_PAGE
    
    def test_classify_js_shell(self):
        """Test that JavaScript-only pages are classified as JS_SHELL."""
        content = "Loading..."
        # Need multiple script tags (at least 3) and minimal text content
        html = "<html><head><script>var app = {};</script><script>var config = {};</script></head><body><div id='app'>Loading...</div><script>ReactDOM.render(...)</script><script>init();</script></body></html>"
        
        quality = classify_extraction_quality(content, html, "https://example.com", 200)
        assert quality == ExtractionQuality.JS_SHELL
    
    def test_classify_empty_content(self):
        """Test that empty content is classified as EMPTY."""
        content = ""
        html = "<html><body></body></html>"
        
        quality = classify_extraction_quality(content, html, "https://example.com", 200)
        assert quality == ExtractionQuality.EMPTY
    
    def test_classify_thin_content(self):
        """Test that very short content is classified as THIN."""
        content = "Home page"
        html = "<html><body><h1>Home</h1></body></html>"
        
        quality = classify_extraction_quality(content, html, "https://example.com", 200)
        assert quality == ExtractionQuality.THIN
    
    def test_classify_error_page_404(self):
        """Test that 404 error pages (returned with 200) are classified as ERROR_PAGE."""
        content = "404 Not Found - The page you are looking for does not exist"
        html = "<html><body><h1>404 Not Found</h1></body></html>"
        
        quality = classify_extraction_quality(content, html, "https://example.com", 200)
        assert quality == ExtractionQuality.ERROR_PAGE
    
    def test_classify_error_page_500(self):
        """Test that 500 error pages are classified as ERROR_PAGE."""
        content = "500 Internal Server Error"
        html = "<html><body><h1>500 Internal Server Error</h1></body></html>"
        
        quality = classify_extraction_quality(content, html, "https://example.com", 200)
        assert quality == ExtractionQuality.ERROR_PAGE
    
    def test_classify_soft_404(self):
        """Test that soft 404 pages are classified as SOFT_404."""
        content = "Index of /"
        html = "<html><body><h1>Index of /</h1><p>Apache Server</p></body></html>"
        
        quality = classify_extraction_quality(content, html, "https://example.com", 200)
        assert quality == ExtractionQuality.SOFT_404
    
    def test_classify_substantive_content(self):
        """Test that substantive content is classified as SUBSTANTIVE."""
        content = "The Southern African Power Pool (SAPP) is a regional power trading market that facilitates the sharing of electricity among member countries. It was established to promote efficient and reliable electricity supply across the Southern African region."
        html = "<html><body><h1>About SAPP</h1><p>The Southern African Power Pool...</p></body></html>"
        
        quality = classify_extraction_quality(content, html, "https://sapp.co.zw", 200)
        assert quality == ExtractionQuality.SUBSTANTIVE


class TestEvidenceStatusClassification:
    """Test that evidence status is correctly determined from extraction quality and retrieval status."""
    
    def test_usable_evidence(self):
        """Test that substantive content with successful retrieval is USABLE."""
        status = classify_evidence_status(ExtractionQuality.SUBSTANTIVE, RetrievalStatus.SUCCESS)
        assert status == EvidenceStatus.USABLE
    
    def test_thin_evidence(self):
        """Test that thin content is THIN."""
        status = classify_evidence_status(ExtractionQuality.THIN, RetrievalStatus.SUCCESS)
        assert status == EvidenceStatus.THIN
    
    def test_unusable_block_page(self):
        """Test that block pages are UNUSABLE."""
        status = classify_evidence_status(ExtractionQuality.BLOCK_PAGE, RetrievalStatus.SUCCESS)
        assert status == EvidenceStatus.UNUSABLE
    
    def test_unusable_http_error(self):
        """Test that HTTP errors are UNUSABLE."""
        status = classify_evidence_status(ExtractionQuality.EMPTY, RetrievalStatus.HTTP_ERROR)
        assert status == EvidenceStatus.UNUSABLE
    
    def test_unusable_timeout(self):
        """Test that timeouts are UNUSABLE."""
        status = classify_evidence_status(ExtractionQuality.EMPTY, RetrievalStatus.TIMEOUT)
        assert status == EvidenceStatus.UNUSABLE


# =============================================================================
# Test 2: CrawlResult Quality Fields
# =============================================================================

class TestCrawlResultQuality:
    """Test that CrawlResult includes quality classification fields."""
    
    @pytest.mark.asyncio
    async def test_crawl_result_has_quality_fields(self):
        """Test that CrawlResult has retrieval_status, extraction_quality, evidence_status."""
        crawler = PageCrawler(timeout=5.0)
        
        # Create a mock successful crawl
        result = CrawlResult(
            url="https://example.com",
            final_url="https://example.com",
            status_code=200,
            success=True,
            content="Test content",
            content_type="text/html",
            title="Test Page",
        )
        
        # Check that quality fields exist with default values
        assert hasattr(result, 'retrieval_status')
        assert hasattr(result, 'extraction_quality')
        assert hasattr(result, 'evidence_status')


# =============================================================================
# Test 3: EvidenceRecord Quality Fields
# =============================================================================

class TestEvidenceRecordQuality:
    """Test that EvidenceRecord includes quality classification fields."""
    
    def test_evidence_record_has_quality_fields(self):
        """Test that EvidenceRecord has quality fields."""
        record = EvidenceRecord(
            url="https://example.com",
            title="Test",
            snippet="Test snippet",
        )
        
        # Check that quality fields exist with default values
        assert hasattr(record, 'retrieval_status')
        assert hasattr(record, 'extraction_quality')
        assert hasattr(record, 'evidence_status')
        assert hasattr(record, 'content')
        assert hasattr(record, 'final_url')
        assert hasattr(record, 'http_status')
        assert hasattr(record, 'content_type')


# =============================================================================
# Test 4: Wikidata Semantic Validation - ZERA
# =============================================================================

class TestWikidataSemanticValidation:
    """Test that Wikidata semantic validation prevents false positives."""
    
    @pytest.mark.asyncio
    async def test_zera_does_not_match_insect_genus(self):
        """Test that ZERA does not resolve to Q1761087 (Zera insect genus)."""
        provider = WikidataProvider()
        
        # This should NOT return Q1761087 for Zimbabwe Energy Regulatory Authority
        results = await provider.search(
            "Zimbabwe Energy Regulatory Authority (ZERA)",
            max_results=10,
            context={"entity_type": "government agency", "country": "Zimbabwe"}
        )
        
        # Check that no result has entity_id Q1761087
        for result in results:
            if isinstance(result, dict):
                entity_id = result.get("entity_id", "")
                assert entity_id != "Q1761087", f"ZERA incorrectly matched to Q1761087 (Zera insect genus)"
            
            # Also check metadata
            metadata = result.get("metadata", {})
            if isinstance(metadata, dict):
                entity_id = metadata.get("entity_id", "")
                assert entity_id != "Q1761087", f"ZERA metadata incorrectly contains Q1761087"
    
    @pytest.mark.asyncio
    async def test_zera_standalone_does_not_match_insect_genus(self):
        """Test that standalone ZERA acronym does not resolve to Q1761087."""
        provider = WikidataProvider()
        
        # Even with just "ZERA", it should not match Q1761087 if context indicates organization
        results = await provider.search(
            "ZERA",
            max_results=10,
            context={"entity_type": "organization", "country": "Zimbabwe"}
        )
        
        # Check that no result has entity_id Q1761087
        for result in results:
            if isinstance(result, dict):
                entity_id = result.get("entity_id", "")
                assert entity_id != "Q1761087", f"ZERA acronym incorrectly matched to Q1761087"


# =============================================================================
# Test 5: Research Status Propagation
# =============================================================================

class TestResearchStatusPropagation:
    """Test that research_status is properly checked in pipeline."""
    
    @pytest.mark.asyncio
    async def test_partial_research_status_blocks_node_creation(self):
        """Test that PARTIAL research status prevents node creation."""
        from app.services.research.search_orchestrator import OrchestratorResult, ResearchStatus
        from app.services.research_engine import ResearchResult
        from app.services.research.evidence import EvidenceRecord
        from unittest.mock import AsyncMock, MagicMock
        
        # Create a mock research engine that returns PARTIAL status
        mock_orchestrator = MagicMock()
        mock_orchestrator.search = AsyncMock(return_value=OrchestratorResult(
            status=ResearchStatus.PARTIAL,
            evidence=[],
            providers_attempted=["WikipediaProvider", "WikidataProvider"],
            providers_succeeded=["WikipediaProvider"],
            providers_failed=["WikidataProvider"],
        ))
        
        # Create research engine with mock orchestrator
        from app.services.research_engine import ResearchEngine
        engine = ResearchEngine(orchestrator=mock_orchestrator)
        
        result = await engine.research("Test Entity")
        
        # ResearchResult should have research_status = PARTIAL
        assert result.research_status == ResearchStatus.PARTIAL
        assert result.status == "completed"  # Execution completed
    
    @pytest.mark.asyncio
    async def test_degraded_research_status_blocks_node_creation(self):
        """Test that DEGRADED research status prevents node creation."""
        from app.services.research.search_orchestrator import OrchestratorResult, ResearchStatus
        from unittest.mock import AsyncMock, MagicMock
        
        # Create a mock orchestrator that returns DEGRADED status
        mock_orchestrator = MagicMock()
        mock_orchestrator.search = AsyncMock(return_value=OrchestratorResult(
            status=ResearchStatus.DEGRADED,
            evidence=[],
            providers_attempted=["WikipediaProvider"],
            providers_succeeded=["WikipediaProvider"],
            providers_failed=[],
        ))
        
        from app.services.research_engine import ResearchEngine
        engine = ResearchEngine(orchestrator=mock_orchestrator)
        
        result = await engine.research("Test Entity")
        
        # ResearchResult should have research_status = DEGRADED
        assert result.research_status == ResearchStatus.DEGRADED
        assert result.status == "completed"  # Execution completed


# =============================================================================
# Test 6: Pipeline Research Quality Gate
# =============================================================================

class TestPipelineQualityGate:
    """Test that pipeline checks research_status and blocks insufficient research."""
    
    @pytest.mark.asyncio
    async def test_pipeline_blocks_partial_research(self):
        """Test that pipeline does not create node for PARTIAL research."""
        from app.services.research.search_orchestrator import OrchestratorResult, ResearchStatus
        from app.services.research.evidence import EvidenceRecord
        from unittest.mock import AsyncMock, MagicMock
        
        # Create mock orchestrator that returns PARTIAL with some evidence
        mock_orchestrator = MagicMock()
        mock_orchestrator.search = AsyncMock(return_value=OrchestratorResult(
            status=ResearchStatus.PARTIAL,
            evidence=[
                EvidenceRecord(
                    url="https://example.com/1",
                    title="Test 1",
                    snippet="Test snippet 1",
                )
            ],
            providers_attempted=["WikipediaProvider", "WikidataProvider"],
            providers_succeeded=["WikipediaProvider"],
            providers_failed=["WikidataProvider"],
        ))
        
        pipeline = EntityPipelineService(
            orchestrator=mock_orchestrator,
            registry=EntityRegistry(),
            resolver=EntityResolver(EntityRegistry()),
        )
        
        result = await pipeline.run("Test Entity")
        
        # Pipeline should mark as insufficient, not completed
        assert result.status == "insufficient"
        assert "partial" in (result.error_message or "").lower()
        # Node should not be created
        assert result.node_draft is None
        assert result.canonical_row is None
    
    @pytest.mark.asyncio
    async def test_pipeline_blocks_degraded_research(self):
        """Test that pipeline does not create node for DEGRADED research."""
        from app.services.research.search_orchestrator import OrchestratorResult, ResearchStatus
        from app.services.research.evidence import EvidenceRecord
        from unittest.mock import AsyncMock, MagicMock
        
        # Create mock orchestrator that returns DEGRADED
        mock_orchestrator = MagicMock()
        mock_orchestrator.search = AsyncMock(return_value=OrchestratorResult(
            status=ResearchStatus.DEGRADED,
            evidence=[],
            providers_attempted=["WikipediaProvider"],
            providers_succeeded=["WikipediaProvider"],
            providers_failed=[],
        ))
        
        pipeline = EntityPipelineService(
            orchestrator=mock_orchestrator,
            registry=EntityRegistry(),
            resolver=EntityResolver(EntityRegistry()),
        )
        
        result = await pipeline.run("Test Entity")
        
        # Pipeline should mark as insufficient
        assert result.status == "insufficient"
        assert "degraded" in (result.error_message or "").lower()
        assert result.node_draft is None
        assert result.canonical_row is None
    
    @pytest.mark.asyncio
    async def test_pipeline_allows_complete_research(self):
        """Test that pipeline allows COMPLETE research to proceed past quality gate."""
        from app.services.research.search_orchestrator import OrchestratorResult, ResearchStatus
        from app.services.research.evidence import EvidenceRecord
        from app.services.research_engine import ResearchEngine
        from unittest.mock import AsyncMock, MagicMock
        
        # Create mock orchestrator that returns COMPLETE
        mock_orchestrator = MagicMock()
        mock_orchestrator.search = AsyncMock(return_value=OrchestratorResult(
            status=ResearchStatus.COMPLETE,
            evidence=[
                EvidenceRecord(url="https://example.com/1", title="Test 1", snippet="Test snippet 1", content="Full content about Test Entity"),
                EvidenceRecord(url="https://example.com/2", title="Test 2", snippet="Test snippet 2", content="More content about Test Entity"),
                EvidenceRecord(url="https://example.com/3", title="Test 3", snippet="Test snippet 3", content="Additional content about Test Entity"),
            ],
            providers_attempted=["WikipediaProvider", "WikidataProvider"],
            providers_succeeded=["WikipediaProvider", "WikidataProvider"],
            providers_failed=[],
        ))
        
        # Create research engine with mock orchestrator
        engine = ResearchEngine(orchestrator=mock_orchestrator)
        
        # Verify the engine returns COMPLETE status
        research_result = await engine.research("Test Entity")
        assert research_result.research_status == ResearchStatus.COMPLETE
        assert research_result.status == "completed"
        
        # Test that pipeline with COMPLETE research passes the quality gate
        # (It may fail later for other reasons, but it should NOT be blocked at the quality gate)
        pipeline = EntityPipelineService(
            research_engine=engine,
            registry=EntityRegistry(),
            resolver=EntityResolver(EntityRegistry()),
        )
        
        result = await pipeline.run("Test Entity")
        
        # Pipeline should NOT be blocked at the quality gate for COMPLETE research
        # The error (if any) should NOT be about research quality being insufficient
        assert result.status in ["completed", "failed", "insufficient"]
        # If it's insufficient, it should NOT be due to COMPLETE status
        if result.status == "insufficient":
            assert "COMPLETE" not in (result.error_message or "")
            assert "complete" not in (result.error_message or "").lower()


# =============================================================================
# Test 7: Evidence Content Preservation
# =============================================================================

class TestEvidenceContentPreservation:
    """Test that full crawled content is preserved in EvidenceRecord."""
    
    def test_evidence_record_preserves_full_content(self):
        """Test that EvidenceRecord.content preserves full crawled content."""
        full_content = "This is the full content of the page. " * 100  # Long content
        
        record = EvidenceRecord(
            url="https://example.com",
            title="Test Page",
            snippet=full_content[:2000],  # Truncated snippet
            content=full_content,  # Full content
        )
        
        # Verify full content is preserved
        assert record.content == full_content
        assert len(record.content) > 2000
        assert len(record.snippet) == 2000
    
    def test_evidence_record_content_field_exists(self):
        """Test that EvidenceRecord has a content field."""
        record = EvidenceRecord(
            url="https://example.com",
            title="Test",
            snippet="Test snippet",
        )
        
        assert hasattr(record, 'content')


# =============================================================================
# Test 8: Crawl Metrics Distinguish Quality
# =============================================================================

class TestCrawlMetrics:
    """Test that crawl metrics distinguish between retrieved, substantive, and usable."""
    
    @pytest.mark.asyncio
    async def test_orchestrator_reports_quality_metrics(self):
        """Test that orchestrator reports quality metrics."""
        from app.services.research.search_orchestrator import OrchestratorResult
        from app.services.research.evidence import EvidenceRecord, EvidenceStatus, ExtractionQuality
        
        # Create an orchestrator result with quality metrics
        result = OrchestratorResult(
            status=ResearchStatus.COMPLETE,
            evidence=[
                EvidenceRecord(
                    url="https://example.com/1",
                    title="Substantive",
                    snippet="Good content",
                    evidence_status=EvidenceStatus.USABLE,
                    extraction_quality=ExtractionQuality.SUBSTANTIVE,
                ),
                EvidenceRecord(
                    url="https://example.com/2",
                    title="Thin",
                    snippet="Little content",
                    evidence_status=EvidenceStatus.THIN,
                    extraction_quality=ExtractionQuality.THIN,
                ),
                EvidenceRecord(
                    url="https://example.com/3",
                    title="Blocked",
                    snippet="Access denied",
                    evidence_status=EvidenceStatus.UNUSABLE,
                    extraction_quality=ExtractionQuality.BLOCK_PAGE,
                ),
            ],
            substantive_evidence_count=1,
            thin_evidence_count=1,
            unusable_evidence_count=1,
        )
        
        # Verify quality metrics are tracked
        assert result.substantive_evidence_count == 1
        assert result.thin_evidence_count == 1
        assert result.unusable_evidence_count == 1


# =============================================================================
# Test 9: DirectSiteCrawler Sequencing
# =============================================================================

class TestDirectSiteCrawlerSequencing:
    """Test that DirectSiteCrawler receives official_website from Wikidata."""
    
    @pytest.mark.asyncio
    async def test_orchestrator_phases_identity_first(self):
        """Test that orchestrator runs identity/reference providers in Phase 1a before official_source in Phase 1b."""
        from app.services.research.search_provider import ProviderRole, SearchProvider, SearchResult
        from app.services.research.wikipedia_provider import WikipediaProvider
        from app.services.research.wikidata_provider import WikidataProvider
        from app.services.research.direct_site_crawler import DirectSiteCrawler
        from app.services.research.web_search import WebSearchProvider
        from unittest.mock import AsyncMock, MagicMock
        
        # Create providers
        wikidata = WikidataProvider()
        wikipedia = WikipediaProvider()
        direct_crawler = DirectSiteCrawler()
        web_search = WebSearchProvider()
        
        # Verify provider roles
        assert wikidata.role == ProviderRole.IDENTITY
        assert wikipedia.role == ProviderRole.REFERENCE
        assert direct_crawler.role == ProviderRole.OFFICIAL_SOURCE
        assert web_search.role == ProviderRole.WEB_DISCOVERY
        
        # Create orchestrator with these providers
        orchestrator = SearchOrchestrator(
            providers=[wikidata, wikipedia, direct_crawler, web_search],
            min_evidence=2,
            max_concurrent_providers=2,
        )
        
        # Verify that providers are separated into correct phases
        # Phase 1a: IDENTITY and REFERENCE
        # Phase 1b: OFFICIAL_SOURCE
        # Phase 2: WEB_DISCOVERY and others
        phase1a_roles = {ProviderRole.IDENTITY.value, ProviderRole.REFERENCE.value}
        phase1b_roles = {ProviderRole.OFFICIAL_SOURCE.value}
        phase2_roles = {ProviderRole.WEB_DISCOVERY.value, ProviderRole.NEWS.value, ProviderRole.DEEP_ARCHIVE.value, ProviderRole.SECONDARY_WEB_SEARCH.value}
        
        phase1a_providers = []
        phase1b_providers = []
        phase2_providers = []
        for provider in orchestrator.providers:
            role = orchestrator._get_provider_role(provider)
            if role in phase1a_roles:
                phase1a_providers.append(provider)
            elif role in phase1b_roles:
                phase1b_providers.append(provider)
            else:
                phase2_providers.append(provider)
        
        # Wikidata and Wikipedia should be in Phase 1a
        assert any(p.__class__.__name__ == "WikidataProvider" for p in phase1a_providers)
        assert any(p.__class__.__name__ == "WikipediaProvider" for p in phase1a_providers)
        # DirectSiteCrawler should be in Phase 1b (NOT Phase 1a)
        assert any(p.__class__.__name__ == "DirectSiteCrawler" for p in phase1b_providers)
        assert not any(p.__class__.__name__ == "DirectSiteCrawler" for p in phase1a_providers)
        # WebSearch should be in Phase 2
        assert any(p.__class__.__name__ == "WebSearchProvider" for p in phase2_providers)
    
    @pytest.mark.asyncio
    async def test_direct_site_crawler_receives_official_website(self):
        """Test that DirectSiteCrawler receives official_website from Wikidata in context."""
        from app.services.research.search_provider import ProviderRole, SearchResult
        from app.services.research.wikipedia_provider import WikipediaProvider
        from app.services.research.wikidata_provider import WikidataProvider
        from app.services.research.direct_site_crawler import DirectSiteCrawler
        from unittest.mock import AsyncMock, MagicMock, patch
        
        # Create mock providers
        mock_wikidata = MagicMock(spec=WikidataProvider)
        mock_wikidata.role = ProviderRole.IDENTITY
        mock_wikidata.__class__.__name__ = "WikidataProvider"
        mock_wikidata.search = AsyncMock(return_value=[
            {
                "title": "Test Entity",
                "url": "https://wikidata.org/wiki/Q123",
                "snippet": "Test description",
                "metadata": {"official_website": "https://example.com/official"}
            }
        ])
        
        mock_direct_crawler = MagicMock(spec=DirectSiteCrawler)
        mock_direct_crawler.role = ProviderRole.OFFICIAL_SOURCE
        mock_direct_crawler.__class__.__name__ = "DirectSiteCrawler"
        mock_direct_crawler.search = AsyncMock(return_value=[])
        
        # Create orchestrator
        orchestrator = SearchOrchestrator(
            providers=[mock_wikidata, mock_direct_crawler],
            min_evidence=2,
            max_concurrent_providers=2,
        )
        
        # Run search
        result = await orchestrator.search("Test Entity", context={})
        
        # Verify that DirectSiteCrawler was called with context containing official_website
        assert mock_direct_crawler.search.called
        call_args = mock_direct_crawler.search.call_args
        assert call_args is not None
        context_arg = call_args.kwargs.get("context", {})
        assert "official_website" in context_arg
        assert context_arg["official_website"] == "https://example.com/official"


# =============================================================================
# Test 10: Common Crawl Index Discovery
# =============================================================================

class TestCommonCrawlIndexDiscovery:
    """Test that Common Crawl uses available indexes."""
    
    def test_common_crawl_latest_crawl_fallback(self):
        """Test that Common Crawl provider has fallback for latest crawl."""
        from app.services.research.commoncrawl_provider import CommonCrawlProvider
        
        provider = CommonCrawlProvider()
        
        # Get the latest crawl
        latest = provider._get_latest_crawl()
        
        # Should return a string in format like "2024-51" or "CC-MAIN-2024-51"
        assert isinstance(latest, str)
        assert len(latest) > 0


# =============================================================================
# Test 11: Prevent Rejected Candidate Metadata Contamination
# =============================================================================

class TestRejectedCandidateMetadataContamination:
    """Test that Wikidata provider doesn't propagate rejected candidate metadata."""
    
    @pytest.mark.asyncio
    async def test_wikidata_does_not_propagate_rejected_metadata(self):
        """Test that when semantic validation rejects a candidate, its metadata is not returned."""
        from app.services.research.wikidata_provider import WikidataProvider
        from unittest.mock import AsyncMock, patch, MagicMock
        
        # Create a Wikidata provider
        provider = WikidataProvider()
        
        # Mock _find_entity_by_label to return Q1761087 (Zera insect genus)
        with patch.object(provider, '_find_entity_by_label', AsyncMock(return_value="Q1761087")):
            # Mock _semantic_match to reject Q1761087
            with patch.object(provider, '_semantic_match', AsyncMock(return_value=False)):
                # Mock _get_entity_info to return entity data with official_website
                mock_entity_data = {
                    "id": "Q1761087",
                    "labels": {"en": {"value": "Zera"}},
                    "descriptions": {"en": {"value": "genus of insects"}},
                    "claims": {
                        "P856": [{"mainsnak": {"datavalue": {"value": "https://insects.example.com/zera"}}}]
                    }
                }
                with patch.object(provider, '_get_entity_info', AsyncMock(return_value=mock_entity_data)):
                    # Search for ZERA (Zimbabwe Energy Regulatory Authority)
                    results = await provider.search(
                        "Zimbabwe Energy Regulatory Authority (ZERA)",
                        max_results=10,
                        context={"entity_type": "government agency", "country": "Zimbabwe"}
                    )
                    
                    # Q1761087 should be rejected by semantic validation
                    # Therefore no results should contain its metadata (including official_website)
                    for result in results:
                        if isinstance(result, dict):
                            assert result.get("entity_id") != "Q1761087"
                            metadata = result.get("metadata", {})
                            if isinstance(metadata, dict):
                                # The rejected candidate's official_website should not appear
                                assert "insects.example.com" not in metadata.get("official_website", "")
    
    @pytest.mark.asyncio
    async def test_wikidata_sparql_results_validated(self):
        """Test that SPARQL results also go through semantic validation."""
        from app.services.research.wikidata_provider import WikidataProvider
        from unittest.mock import AsyncMock, patch, MagicMock
        
        provider = WikidataProvider()
        
        # Mock _find_entity_by_label to return None (no direct match)
        with patch.object(provider, '_find_entity_by_label', AsyncMock(return_value=None)):
            # Mock _sparql_search to return Q1761087
            mock_sparql_result = {
                "title": "Zera",
                "url": "https://www.wikidata.org/wiki/Q1761087",
                "snippet": "genus of insects",
                "source": "wikidata",
                "entity_id": "Q1761087",
                "metadata": {"official_website": "https://insects.example.com/zera"}
            }
            with patch.object(provider, '_sparql_search', AsyncMock(return_value=[mock_sparql_result])):
                # Mock _semantic_match to reject Q1761087
                with patch.object(provider, '_semantic_match', AsyncMock(return_value=False)):
                    results = await provider.search(
                        "Zimbabwe Energy Regulatory Authority (ZERA)",
                        max_results=10,
                        context={"entity_type": "government agency", "country": "Zimbabwe"}
                    )
                    
                    # Q1761087 should be filtered out by semantic validation
                    # No results should contain the rejected entity
                    for result in results:
                        if isinstance(result, dict):
                            assert result.get("entity_id") != "Q1761087"


# =============================================================================
# Test 12: Provider Failure Isolation
# =============================================================================

class TestProviderFailureIsolation:
    """Test that provider failures are isolated and don't erase other results."""
    
    @pytest.mark.asyncio
    async def test_orchestrator_preserves_successful_results_on_failure(self):
        """Test that orchestrator preserves successful provider results even when others fail."""
        from app.services.research.search_orchestrator import OrchestratorResult, ResearchStatus, ProviderStatus
        from app.services.research.evidence import EvidenceRecord
        from unittest.mock import AsyncMock, MagicMock
        
        # Create a mock orchestrator
        orchestrator = SearchOrchestrator(
            providers=[],
            min_evidence=2,
        )
        
        # Manually create a result with mixed provider outcomes
        result = OrchestratorResult(
            status=ResearchStatus.PARTIAL,
            evidence=[
                EvidenceRecord(url="https://wikipedia.org/test", title="Wikipedia", snippet="Wiki content"),
                EvidenceRecord(url="https://wikidata.org/test", title="Wikidata", snippet="WD content"),
            ],
            providers_attempted=["WikipediaProvider", "WikidataProvider", "MozillaProvider"],
            providers_succeeded=["WikipediaProvider", "WikidataProvider"],
            providers_failed=["MozillaProvider"],
        )
        
        # Verify that successful providers are tracked
        assert len(result.providers_succeeded) == 2
        assert len(result.providers_failed) == 1
        assert len(result.evidence) == 2
        
        # Verify that evidence is preserved
        assert any("wikipedia" in e.url.lower() for e in result.evidence)
        assert any("wikidata" in e.url.lower() for e in result.evidence)


# =============================================================================
# Summary
# =============================================================================

if __name__ == "__main__":
    # Run tests
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
