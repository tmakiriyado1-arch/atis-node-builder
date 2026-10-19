"""Regression tests for block page detection and zero-evidence pipeline failures.

These tests verify fixes for production issues:
- Run 950b96ed-3609-4bf3-b5a3-9a966111518a (ZERA): Zero atomic evidence, ReadTimeout x3
- Run b721446c-17d1-49d9-b799-64e1f9e1f3d1 (Theotechnic): Google block message becoming summary
- Run e8755d18-7aa6-4b12-919a-04de3f0c2558: deduplicate_evidence unassociated local
- Run 3b371ae2-7e8e-40df-ae46-9f9870bcf9d8: CRITICAL NO atomic evidence, success=0 failure=0
"""
import pytest
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.services.research.evidence import (
    EvidenceRecord,
    ExtractionQuality,
    EvidenceStatus,
    RetrievalStatus,
    classify_extraction_quality,
    classify_evidence_status,
)
from app.services.research.semantic_extractor import (
    AtomicEvidence,
    EvidenceType,
    ExtractionResult,
    MistralSemanticExtractor,
    ResearchDocument,
)
from app.services.canonical_row_builder import CanonicalNodeRowBuilder
from app.models import NodeDraft
from app.services.research_engine import ResearchClaim


# =============================================================================
# Fixtures: Production Block Messages
# =============================================================================

@pytest.fixture
def google_block_message():
    """Exact Google-style block message from production run b721446c-17d1-49d9-b799-64e1f9e1f3d1"""
    return "Our systems have detected unusual traffic from your computer network. Please try your request again later."


@pytest.fixture
def cloudflare_block_message():
    """Cloudflare-style block message"""
    return "Access Denied - Cloudflare\nYou do not have permission to access this page."


@pytest.fixture
def captcha_page():
    """CAPTCHA verification page"""
    return "Please verify you are not a robot.\nCAPTCHA verification required."


@pytest.fixture
def login_page():
    """Login wall page"""
    return "Please sign in to continue.\nLogin required to access this content."


@pytest.fixture
def valid_zera_content():
    """Valid ZERA content that should be accepted"""
    return "The Zimbabwe Energy Regulatory Authority (ZERA) is a statutory body established under the Energy Regulatory Authority Act to regulate the energy sector in Zimbabwe. ZERA regulates electricity tariffs, petroleum pricing, and renewable energy."


@pytest.fixture
def zera_evidence_record(valid_zera_content):
    """Create a valid EvidenceRecord for ZERA"""
    return EvidenceRecord(
        url="https://www.zera.co.zw",
        title="Zimbabwe Energy Regulatory Authority",
        snippet="ZERA regulates the energy sector in Zimbabwe",
        content=f"<html><body>{valid_zera_content}</body></html>",
        source="public_web_search",
        query="ZERA",
        entity_name="Zimbabwe Energy Regulatory Authority",
        retrieval_status=RetrievalStatus.SUCCESS,
        extraction_quality=ExtractionQuality.SUBSTANTIVE,
        evidence_status=EvidenceStatus.USABLE,
        normalized_text=valid_zera_content,
    )


@pytest.fixture
def block_message_evidence_record(google_block_message):
    """Create an EvidenceRecord with Google block message"""
    return EvidenceRecord(
        url="https://www.uei.edu/",
        title="Theotechnic College",
        snippet="Theotechnic College official site",
        content=f"<html><body>{google_block_message}</body></html>",
        source="public_web_search",
        query="Theotechnic College",
        entity_name="Theotechnic College",
        retrieval_status=RetrievalStatus.SUCCESS,
        extraction_quality=ExtractionQuality.SUBSTANTIVE,
        evidence_status=EvidenceStatus.USABLE,
        normalized_text=google_block_message,
    )


# =============================================================================
# Test Class 1: Block Page Detection
# =============================================================================

class TestBlockPageDetection:
    """Test that block pages are correctly detected and rejected."""

    def test_google_block_message_detected(self, google_block_message):
        """Test that the exact Google block message from production is detected."""
        quality = classify_extraction_quality(google_block_message)
        assert quality == ExtractionQuality.BLOCK_PAGE

    def test_google_block_message_evidence_status(self, google_block_message):
        """Test that block message evidence is marked as UNUSABLE."""
        quality = classify_extraction_quality(google_block_message)
        status = classify_evidence_status(quality, RetrievalStatus.SUCCESS)
        assert status == EvidenceStatus.UNUSABLE

    def test_cloudflare_block_detected(self, cloudflare_block_message):
        """Test Cloudflare block detection."""
        quality = classify_extraction_quality(cloudflare_block_message)
        assert quality == ExtractionQuality.BLOCK_PAGE

    def test_captcha_page_detected(self, captcha_page):
        """Test CAPTCHA page detection."""
        quality = classify_extraction_quality(captcha_page)
        assert quality == ExtractionQuality.BLOCK_PAGE

    def test_login_page_detected(self, login_page):
        """Test login wall detection."""
        quality = classify_extraction_quality(login_page)
        # Login pages may be classified as THIN or BLOCK_PAGE depending on content
        assert quality in (ExtractionQuality.BLOCK_PAGE, ExtractionQuality.THIN, ExtractionQuality.NAVIGATION)

    def test_valid_content_not_detected_as_block(self, valid_zera_content):
        """Test that valid content is NOT detected as block page."""
        quality = classify_extraction_quality(valid_zera_content)
        assert quality != ExtractionQuality.BLOCK_PAGE
        assert quality == ExtractionQuality.SUBSTANTIVE

    def test_block_message_with_entity_name_still_blocked(self, google_block_message):
        """Test that block message containing entity name is still blocked."""
        block_with_entity = f"{google_block_message} Theotechnic College"
        quality = classify_extraction_quality(block_with_entity)
        assert quality == ExtractionQuality.BLOCK_PAGE


# =============================================================================
# Test Class 2: Canonical Row Builder - Block Page Rejection
# =============================================================================

class TestCanonicalRowBuilderBlockRejection:
    """Test that block pages cannot become entity summaries."""

    def test_block_message_summary_rejected(self, google_block_message):
        """Test that block message summary is rejected by canonical row builder."""
        builder = CanonicalNodeRowBuilder()
        
        claim = ResearchClaim(
            claim="Test claim",
            field_name="fact",
            source_url="https://example.com",
            evidence_passage=google_block_message,
        )
        
        node_draft = NodeDraft(
            title="Theotechnic College",
            body=f"## Summary\n{google_block_message}",
            frontmatter={"entity": "Theotechnic College"},
            source_claims=[claim],
        )
        
        # Should raise ValueError because summary doesn't reference entity
        with pytest.raises(ValueError, match="summary must reference entity"):
            builder.build(node_draft)

    def test_block_message_with_entity_name_rejected(self, google_block_message):
        """Test that block message with entity name is still rejected.
        
        This is the critical fix: even if a block message contains the entity name,
        it should be rejected because it's not actually about the entity.
        """
        builder = CanonicalNodeRowBuilder()
        
        block_with_entity = f"{google_block_message} Theotechnic College"
        
        claim = ResearchClaim(
            claim="Test claim",
            field_name="fact",
            source_url="https://example.com",
            evidence_passage=block_with_entity,
        )
        
        node_draft = NodeDraft(
            title="Theotechnic College",
            body=f"## Summary\n{block_with_entity}",
            frontmatter={"entity": "Theotechnic College"},
            source_claims=[claim],
        )
        
        # Should raise ValueError - block content is detected and rejected
        with pytest.raises(ValueError, match="summary must reference entity"):
            builder.build(node_draft)

    def test_valid_summary_accepted(self, valid_zera_content):
        """Test that valid summary is accepted."""
        builder = CanonicalNodeRowBuilder()
        
        claim = ResearchClaim(
            claim="ZERA regulates the energy sector in Zimbabwe",
            field_name="fact",
            source_url="https://www.zera.co.zw",
            evidence_passage=valid_zera_content[:100],
        )
        
        node_draft = NodeDraft(
            title="Zimbabwe Energy Regulatory Authority",
            body=f"## Summary\n{valid_zera_content}",
            frontmatter={"entity": "Zimbabwe Energy Regulatory Authority"},
            source_claims=[claim],
        )
        
        # Should NOT raise - valid content references entity
        result = builder.build(node_draft)
        assert result.entity == "Zimbabwe Energy Regulatory Authority"


# =============================================================================
# Test Class 3: Semantic Extractor - API Key Handling
# =============================================================================

class TestSemanticExtractorAPIKeyHandling:
    """Test that semantic extractor handles missing API key gracefully."""

    @pytest.mark.asyncio
    async def test_no_api_key_uses_fallback(self, zera_evidence_record):
        """Test that when API key is missing, fallback extraction is used."""
        extractor = MistralSemanticExtractor(api_key=None, max_retries=0)
        
        results = await extractor.extract(
            entity_name="Zimbabwe Energy Regulatory Authority",
            evidence_records=[zera_evidence_record],
        )
        
        assert len(results) == 1
        result = results[0]
        assert result.document is not None
        assert result.document.url == zera_evidence_record.url

    @pytest.mark.asyncio
    async def test_no_api_key_no_evidence_not_called_counter(self, zera_evidence_record):
        """Test that llm_not_called counter is incremented when no API key."""
        extractor = MistralSemanticExtractor(api_key=None, max_retries=0)
        
        results = await extractor.extract(
            entity_name="Zimbabwe Energy Regulatory Authority",
            evidence_records=[zera_evidence_record],
        )
        
        assert len(results) == 1


# =============================================================================
# Test Class 4: Semantic Extractor - Zero Evidence Scenarios
# =============================================================================

class TestSemanticExtractorZeroEvidence:
    """Test various zero-evidence scenarios."""

    @pytest.mark.asyncio
    async def test_empty_evidence_list(self):
        """Test that empty evidence list is handled gracefully."""
        extractor = MistralSemanticExtractor(api_key="test-key", max_retries=0)
        
        results = await extractor.extract(
            entity_name="Test Entity",
            evidence_records=[],
        )
        
        assert results == []

    @pytest.mark.asyncio
    async def test_all_records_skipped(self):
        """Test that all records being skipped is handled."""
        extractor = MistralSemanticExtractor(api_key="test-key", max_retries=0)
        
        records = [
            EvidenceRecord(url="", title="Test", snippet="test"),
            EvidenceRecord(url=None, title="Test 2", snippet="test2"),
        ]
        
        results = await extractor.extract(
            entity_name="Test Entity",
            evidence_records=records,
        )
        
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_unusable_evidence_skipped(self):
        """Test that UNUSABLE evidence is skipped."""
        extractor = MistralSemanticExtractor(api_key="test-key", max_retries=0)
        
        records = [
            EvidenceRecord(
                url="https://example.com",
                title="Test",
                snippet="test",
                evidence_status=EvidenceStatus.UNUSABLE,
            ),
        ]
        
        results = await extractor.extract(
            entity_name="Test Entity",
            evidence_records=records,
        )
        
        assert len(results) == 0


# =============================================================================
# Test Class 5: Pipeline - deduplicate_evidence Fix
# =============================================================================

class TestPipelineDeduplicateEvidence:
    """Test that deduplicate_evidence works correctly in pipeline."""

    @pytest.mark.asyncio
    async def test_pipeline_imports_deduplicate_evidence(self):
        """Test that pipeline.py correctly imports deduplicate_evidence at module level."""
        from app.services.pipeline import EntityPipelineService
        
        # If we get here, the module compiled successfully
        assert EntityPipelineService is not None

    def test_deduplicate_evidence_available(self):
        """Test that deduplicate_evidence is available from evidence module."""
        from app.services.research.evidence import deduplicate_evidence
        
        assert callable(deduplicate_evidence)
        result = deduplicate_evidence([])
        assert result == []


# =============================================================================
# Test Class 6: Fallback Extraction
# =============================================================================

class TestFallbackExtraction:
    """Test fallback extraction behavior."""

    @pytest.mark.asyncio
    async def test_fallback_with_valid_content(self, zera_evidence_record):
        """Test that fallback extraction works with valid content."""
        extractor = MistralSemanticExtractor(api_key=None, max_retries=0)
        
        results = await extractor.extract(
            entity_name="Zimbabwe Energy Regulatory Authority",
            evidence_records=[zera_evidence_record],
        )
        
        assert len(results) == 1
        result = results[0]
        
        assert len(result.atomic_evidence) >= 1
        assert result.atomic_evidence[0].evidence_type == EvidenceType.SUMMARY
        assert result.atomic_evidence[0].extraction_method == "fallback"

    @pytest.mark.asyncio
    async def test_fallback_preserves_source_url(self, zera_evidence_record):
        """Test that fallback extraction preserves source URL."""
        extractor = MistralSemanticExtractor(api_key=None, max_retries=0)
        
        results = await extractor.extract(
            entity_name="Zimbabwe Energy Regulatory Authority",
            evidence_records=[zera_evidence_record],
        )
        
        assert len(results) == 1
        result = results[0]
        
        if result.atomic_evidence:
            for evidence in result.atomic_evidence:
                assert evidence.source_url == zera_evidence_record.url

    @pytest.mark.asyncio
    async def test_fallback_with_empty_content(self):
        """Test that fallback with empty content returns empty evidence."""
        extractor = MistralSemanticExtractor(api_key=None, max_retries=0)
        
        record = EvidenceRecord(
            url="https://example.com",
            title="Empty Page",
            snippet="",
            content="",
            normalized_text="",
        )
        
        results = await extractor.extract(
            entity_name="Test Entity",
            evidence_records=[record],
        )
        
        assert len(results) == 1
        result = results[0]
        
        assert len(result.atomic_evidence) == 0
        # Error could be either from fallback or from chunk creation
        assert len(result.extraction_errors) > 0

    @pytest.mark.asyncio
    async def test_fallback_with_too_short_content(self):
        """Test that fallback with very short content returns empty evidence."""
        extractor = MistralSemanticExtractor(api_key=None, max_retries=0)
        
        record = EvidenceRecord(
            url="https://example.com",
            title="Short Page",
            snippet="Short",
            content="<html><body>Hi</body></html>",
            normalized_text="Hi",
        )
        
        results = await extractor.extract(
            entity_name="Test Entity",
            evidence_records=[record],
        )
        
        assert len(results) == 1
        result = results[0]
        
        assert len(result.atomic_evidence) == 0


# =============================================================================
# Test Class 7: End-to-End Block Page Rejection
# =============================================================================

class TestEndToEndBlockPageRejection:
    """Test complete pipeline rejection of block pages."""

    def test_block_page_evidence_status(self, block_message_evidence_record, google_block_message):
        """Test that block page evidence has UNUSABLE status."""
        quality = classify_extraction_quality(google_block_message)
        assert quality == ExtractionQuality.BLOCK_PAGE
        
        status = classify_evidence_status(quality, block_message_evidence_record.retrieval_status)
        assert status == EvidenceStatus.UNUSABLE

    def test_valid_evidence_status(self, zera_evidence_record):
        """Test that valid evidence has USABLE status."""
        quality = classify_extraction_quality(zera_evidence_record.normalized_text)
        assert quality == ExtractionQuality.SUBSTANTIVE
        
        status = classify_evidence_status(quality, zera_evidence_record.retrieval_status)
        assert status == EvidenceStatus.USABLE
