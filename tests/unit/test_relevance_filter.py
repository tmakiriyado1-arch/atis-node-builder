"""Tests for LLM-based relevance filtering.

These tests cover the semantic relevance classification functionality
that determines whether crawled page content is relevant to the target entity.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.research.relevance_filter import (
    RelevanceFilter,
    RelevanceFilterResult,
    RelevanceResult,
    BLOCK_PAGE_INDICATORS,
    ERROR_PAGE_INDICATORS,
)
from app.services.research.evidence import EvidenceRecord, EvidenceStatus, ExtractionQuality


# =============================================================================
# Test 1: Relevant page without literal target name
# =============================================================================
@pytest.mark.asyncio
async def test_relevant_page_without_literal_target_name():
    """Test that a page can be relevant even without literal target name.
    
    Target: Theotechnic College
    Page title: Students
    URL: https://www.theotec.org/students
    Content: Students at the institution undertake technical training in construction,
    electrical installation and mechanical engineering.
    
    Expected: relevant = true
    """
    # Create evidence record
    evidence = EvidenceRecord(
        url="https://www.theotec.org/students",
        title="Students",
        snippet="Students at the institution undertake technical training",
        content="Students at the institution undertake technical training in construction, electrical installation and mechanical engineering.",
        normalized_text="Students at the institution undertake technical training in construction, electrical installation and mechanical engineering.",
        source="page_crawl",
        evidence_status=EvidenceStatus.USABLE,
        extraction_quality=ExtractionQuality.SUBSTANTIVE,
    )
    
    # Create filter with low min_content_length to allow this content
    filter_obj = RelevanceFilter(min_content_length=10)
    
    # Mock the LLM call to return relevant=True
    mock_result = RelevanceResult(
        url="https://www.theotec.org/students",
        relevant=True,
        reason="URL domain and content context indicate this is about Theotechnic College",
        confidence=0.95,
    )
    
    with patch.object(filter_obj, '_filter_batch', new_callable=AsyncMock) as mock_filter_batch:
        mock_filter_batch.return_value = [mock_result]
        
        result = await filter_obj.filter("Theotechnic College", [evidence])
        
        assert len(result.relevant_evidence) == 1
        assert len(result.irrelevant_evidence) == 0
        assert result.kept_count == 1


# =============================================================================
# Test 2: Unrelated page with similar terminology
# =============================================================================
@pytest.mark.asyncio
async def test_unrelated_page_with_similar_terminology():
    """Test that a page with similar terminology but different entity is irrelevant.
    
    Target: Theotechnic College
    Content: Our college provides engineering training in Zimbabwe...
    URL belongs to an unrelated institution.
    
    Expected: relevant = false
    """
    evidence = EvidenceRecord(
        url="https://www.other-college.edu.zm/",
        title="About Our College",
        snippet="Our college provides engineering training in Zimbabwe",
        content="Our college provides engineering training in Zimbabwe. We are not affiliated with Theotechnic College.",
        normalized_text="Our college provides engineering training in Zimbabwe. We are not affiliated with Theotechnic College.",
        source="page_crawl",
        evidence_status=EvidenceStatus.USABLE,
        extraction_quality=ExtractionQuality.SUBSTANTIVE,
    )
    
    filter_obj = RelevanceFilter(min_content_length=10)
    
    # Mock the LLM call to return relevant=False
    mock_result = RelevanceResult(
        url="https://www.other-college.edu.zm/",
        relevant=False,
        reason="Page is about a different college, not Theotechnic College",
        confidence=0.90,
    )
    
    with patch.object(filter_obj, '_filter_batch', new_callable=AsyncMock) as mock_filter_batch:
        mock_filter_batch.return_value = [mock_result]
        
        result = await filter_obj.filter("Theotechnic College", [evidence])
        
        assert len(result.relevant_evidence) == 0
        assert len(result.irrelevant_evidence) == 1
        assert result.filtered_count == 1


# =============================================================================
# Test 3: Real error page mentioning target
# =============================================================================
@pytest.mark.asyncio
async def test_error_page_mentioning_target():
    """Test that an error page mentioning the target is still irrelevant.
    
    Content: 404 Not Found - Theotechnic College
    
    Expected: relevant = false (filtered by quality pre-filter)
    """
    evidence = EvidenceRecord(
        url="https://www.theotec.org/missing-page",
        title="404 Not Found",
        snippet="404 Not Found - Theotechnic College",
        content="404 Not Found - Theotechnic College",
        normalized_text="404 Not Found - Theotechnic College",
        source="page_crawl",
        evidence_status=EvidenceStatus.USABLE,
        extraction_quality=ExtractionQuality.SUBSTANTIVE,
    )
    
    filter_obj = RelevanceFilter(min_content_length=10)
    
    # This should be filtered by quality pre-filter (error page detection)
    result = await filter_obj.filter("Theotechnic College", [evidence])
    
    assert len(result.irrelevant_evidence) == 1
    assert len(result.relevant_evidence) == 0


# =============================================================================
# Test 4: Short but potentially meaningful page
# =============================================================================
@pytest.mark.asyncio
async def test_short_but_meaningful_page():
    """Test that a short but meaningful page is NOT rejected by quality filter.
    
    Title: Theotechnic College
    URL: https://www.theotec.org/
    Content: Technical education in Zimbabwe.
    
    Expected: The deterministic pre-filter must NOT reject it merely because it is short.
    The LLM should receive it.
    """
    evidence = EvidenceRecord(
        url="https://www.theotec.org/",
        title="Theotechnic College",
        snippet="Technical education in Zimbabwe.",
        content="Technical education in Zimbabwe.",
        normalized_text="Technical education in Zimbabwe.",
        source="page_crawl",
        evidence_status=EvidenceStatus.USABLE,
        extraction_quality=ExtractionQuality.THIN,  # May be classified as thin
    )
    
    filter_obj = RelevanceFilter(min_content_length=10)
    
    # Mock the LLM call to return relevant=True
    mock_result = RelevanceResult(
        url="https://www.theotec.org/",
        relevant=True,
        reason="URL and title clearly identify this as Theotechnic College",
        confidence=0.98,
    )
    
    with patch.object(filter_obj, '_filter_batch', new_callable=AsyncMock) as mock_filter_batch:
        mock_filter_batch.return_value = [mock_result]
        
        result = await filter_obj.filter("Theotechnic College", [evidence])
        
        # Should NOT be filtered by quality (content length > min_content_length)
        # Should be passed to LLM for evaluation
        assert len(result.relevant_evidence) == 1
        assert result.kept_count == 1


# =============================================================================
# Test 5: Target mentioned only as a relationship
# =============================================================================
@pytest.mark.asyncio
async def test_target_mentioned_as_relationship():
    """Test that a page mentioning target in a relationship context is relevant.
    
    Content: The Ministry provides accreditation and oversight to Theotechnic College.
    
    Expected: relevant = true
    """
    evidence = EvidenceRecord(
        url="https://www.ministry.gov.zm/accreditation",
        title="Accreditation",
        snippet="The Ministry provides accreditation and oversight to Theotechnic College",
        content="The Ministry provides accreditation and oversight to Theotechnic College.",
        normalized_text="The Ministry provides accreditation and oversight to Theotechnic College.",
        source="page_crawl",
        evidence_status=EvidenceStatus.USABLE,
        extraction_quality=ExtractionQuality.SUBSTANTIVE,
    )
    
    filter_obj = RelevanceFilter(min_content_length=10)
    
    # Mock the LLM call to return relevant=True
    mock_result = RelevanceResult(
        url="https://www.ministry.gov.zm/accreditation",
        relevant=True,
        reason="Explicit relationship mentioned with Theotechnic College",
        confidence=0.95,
    )
    
    with patch.object(filter_obj, '_filter_batch', new_callable=AsyncMock) as mock_filter_batch:
        mock_filter_batch.return_value = [mock_result]
        
        result = await filter_obj.filter("Theotechnic College", [evidence])
        
        assert len(result.relevant_evidence) == 1
        assert result.kept_count == 1


# =============================================================================
# Test 6: Entity absent from body but identity obvious from context
# =============================================================================
@pytest.mark.asyncio
async def test_entity_absent_from_body_but_identity_obvious():
    """Test that identity can be established from URL/domain/title/content/context.
    
    URL: https://www.theotec.org/programmes
    Title: Programmes
    Content: Construction Technology, Electrical Installation, Mechanical Engineering
    
    Expected: The page may be relevant based on URL/domain/title/content/context.
    The literal entity-name check must NOT reject it.
    """
    evidence = EvidenceRecord(
        url="https://www.theotec.org/programmes",
        title="Programmes",
        snippet="Construction Technology, Electrical Installation, Mechanical Engineering",
        content="Construction Technology\nElectrical Installation\nMechanical Engineering",
        normalized_text="Construction Technology\nElectrical Installation\nMechanical Engineering",
        source="page_crawl",
        evidence_status=EvidenceStatus.USABLE,
        extraction_quality=ExtractionQuality.SUBSTANTIVE,
    )
    
    filter_obj = RelevanceFilter(min_content_length=10)
    
    # Mock the LLM call to return relevant=True based on URL/domain context
    mock_result = RelevanceResult(
        url="https://www.theotec.org/programmes",
        relevant=True,
        reason="Official domain (theotec.org) strongly indicates this is about Theotechnic College",
        confidence=0.90,
    )
    
    with patch.object(filter_obj, '_filter_batch', new_callable=AsyncMock) as mock_filter_batch:
        mock_filter_batch.return_value = [mock_result]
        
        result = await filter_obj.filter("Theotechnic College", [evidence])
        
        assert len(result.relevant_evidence) == 1
        assert result.kept_count == 1


# =============================================================================
# Test: Quality pre-filter behavior
# =============================================================================
@pytest.mark.asyncio
async def test_quality_pre_filter_blocks_error_pages():
    """Test that explicit error pages are filtered by quality pre-filter."""
    # Test various error page indicators
    error_contents = [
        "404 Not Found",
        "Internal Server Error",
        "Page not found",
        "Error 500",
        "Service unavailable",
    ]
    
    filter_obj = RelevanceFilter(min_content_length=10)
    
    for content in error_contents:
        evidence = EvidenceRecord(
            url="https://example.com/error",
            title="Error",
            snippet=content,
            content=content,
            normalized_text=content,
            source="page_crawl",
        )
        
        # Pre-filter should catch this
        filtered_out, kept = filter_obj._pre_filter_by_quality([evidence])
        
        assert len(filtered_out) == 1
        assert len(kept) == 0


@pytest.mark.asyncio
async def test_quality_pre_filter_blocks_block_pages():
    """Test that explicit block pages are filtered by quality pre-filter."""
    block_contents = [
        "Access denied",
        "Forbidden",
        "You do not have permission",
        "Cloudflare",
        "Please verify you are human",
        "CAPTCHA",
    ]
    
    filter_obj = RelevanceFilter(min_content_length=10)
    
    for content in block_contents:
        evidence = EvidenceRecord(
            url="https://example.com/blocked",
            title="Blocked",
            snippet=content,
            content=content,
            normalized_text=content,
            source="page_crawl",
        )
        
        # Pre-filter should catch this
        filtered_out, kept = filter_obj._pre_filter_by_quality([evidence])
        
        assert len(filtered_out) == 1
        assert len(kept) == 0


@pytest.mark.asyncio
async def test_quality_pre_filter_allows_short_content():
    """Test that short content is NOT filtered by quality pre-filter."""
    short_contents = [
        "Technical education",
        "Theotechnic College",
        "Welcome to our institution",
    ]
    
    filter_obj = RelevanceFilter(min_content_length=10)
    
    for content in short_contents:
        evidence = EvidenceRecord(
            url="https://example.com/short",
            title="Short Page",
            snippet=content,
            content=content,
            normalized_text=content,
            source="page_crawl",
            evidence_status=EvidenceStatus.USABLE,
            extraction_quality=ExtractionQuality.THIN,
        )
        
        # Pre-filter should NOT catch this (not a block/error page)
        filtered_out, kept = filter_obj._pre_filter_by_quality([evidence])
        
        # Should be kept for LLM evaluation
        assert len(kept) == 1
        assert len(filtered_out) == 0


# =============================================================================
# Test: Empty content handling
# =============================================================================
@pytest.mark.asyncio
async def test_empty_content_filtered():
    """Test that completely empty content is filtered out."""
    evidence = EvidenceRecord(
        url="https://example.com/empty",
        title="Empty",
        snippet="",
        content="",
        normalized_text="",
        source="page_crawl",
    )
    
    filter_obj = RelevanceFilter(min_content_length=10)
    
    filtered_out, kept = filter_obj._pre_filter_by_quality([evidence])
    
    assert len(filtered_out) == 1
    assert len(kept) == 0


# =============================================================================
# Test: No API key fallback behavior
# =============================================================================
@pytest.mark.asyncio
async def test_no_api_key_fallback():
    """Test that when no API key is available, all evidence is retained."""
    evidence1 = EvidenceRecord(
        url="https://example.com/page1",
        title="Page 1",
        snippet="Content 1",
        content="Content 1",
        normalized_text="Content 1",
        source="page_crawl",
    )
    evidence2 = EvidenceRecord(
        url="https://example.com/page2",
        title="Page 2",
        snippet="Content 2",
        content="Content 2",
        normalized_text="Content 2",
        source="page_crawl",
    )
    
    filter_obj = RelevanceFilter(api_key=None, min_content_length=10)
    
    result = await filter_obj.filter("Test Entity", [evidence1, evidence2])
    
    # With no API key, all should be marked as relevant (fallback)
    assert len(result.relevant_evidence) == 2
    assert len(result.irrelevant_evidence) == 0


# =============================================================================
# Test: Batch processing
# =============================================================================
@pytest.mark.asyncio
async def test_batch_processing():
    """Test that batching works correctly."""
    # Create 5 evidence records
    evidences = []
    for i in range(5):
        evidence = EvidenceRecord(
            url=f"https://example.com/page{i}",
            title=f"Page {i}",
            snippet=f"Content {i}",
            content=f"Content {i}",
            normalized_text=f"Content {i}",
            source="page_crawl",
        )
        evidences.append(evidence)
    
    filter_obj = RelevanceFilter(min_content_length=10, batch_size=3)
    
    # Mock the batch filter to return all relevant
    mock_results = [
        RelevanceResult(url=f"https://example.com/page{i}", relevant=True, reason="Relevant", confidence=0.9)
        for i in range(5)
    ]
    
    with patch.object(filter_obj, '_filter_batch', new_callable=AsyncMock) as mock_filter_batch:
        # First batch: 3 items, second batch: 2 items
        mock_filter_batch.side_effect = [
            mock_results[:3],  # First batch
            mock_results[3:],  # Second batch
        ]
        
        result = await filter_obj.filter("Test Entity", evidences)
        
        assert len(result.relevant_evidence) == 5
        assert len(result.irrelevant_evidence) == 0
        assert mock_filter_batch.call_count == 2
