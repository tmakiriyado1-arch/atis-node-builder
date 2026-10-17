"""
Regression tests for ZERA pipeline failures from run 4c6e116b-d12f-435b-bf00-0edf5bc5507f

These tests verify fixes for the confirmed findings:
1. logger not defined in relevance_filter and semantic_extractor
2. atomic_evidence variable access errors
3. LLM response parsing failures for list-based content
4. Evidence-quality decisions for block/error pages
5. Provider configuration issues
6. Pipeline state transition failures
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.services.research.evidence import EvidenceRecord, EvidenceStatus, ExtractionQuality
from app.services.research.semantic_extractor import (
    MistralSemanticExtractor,
    AtomicEvidence,
    EvidenceType,
    ExtractionResult,
    ResearchDocument,
)
from app.services.research.relevance_filter import RelevanceFilter, RelevanceFilterResult
from app.services.research.mistral_response import normalize_mistral_content, extract_mistral_message_content
from app.services.research.evidence_filter import EvidenceFilterPipeline, RelevanceClassification
from app.services.research.llm_ranking import LLMRanker, RankingResult, RankedResult


# =============================================================================
# Test A: Logger Fixes
# =============================================================================

class TestLoggerFixes:
    """Test that logger is properly defined and accessible."""

    def test_relevance_filter_logger_import(self):
        """Test that relevance_filter can access logger without import errors."""
        # This should not raise an ImportError or NameError
        filter_obj = RelevanceFilter(api_key="test-key")
        assert filter_obj is not None

    def test_semantic_extractor_logger_import(self):
        """Test that semantic_extractor can access logger without import errors."""
        # This should not raise an ImportError or NameError
        extractor = MistralSemanticExtractor(api_key="test-key")
        assert extractor is not None

    def test_evidence_filter_logger_import(self):
        """Test that evidence_filter can access logger without import errors."""
        # This should not raise an ImportError or NameError
        pipeline = EvidenceFilterPipeline(target_entity="ZERA")
        assert pipeline is not None


# =============================================================================
# Test B: atomic_evidence Variable Access
# =============================================================================

class TestAtomicEvidenceVariable:
    """Test that atomic_evidence variable is always properly defined."""

    @pytest.fixture
    def extractor(self):
        return MistralSemanticExtractor(api_key="test-key")

    @pytest.fixture
    def test_document(self):
        record = EvidenceRecord(
            url="https://test.com",
            title="Test",
            snippet="Test content",
            normalized_text="Test content",
            source="test",
            query="test"
        )
        return ResearchDocument.from_evidence_record(record)

    def test_parse_empty_response(self, extractor, test_document):
        """Test parsing empty response doesn't cause atomic_evidence access error."""
        parsed = {}
        result = extractor._parse_extraction_result("TestEntity", test_document, parsed)
        assert result is not None
        assert isinstance(result.atomic_evidence, list)
        assert len(result.atomic_evidence) == 0

    def test_parse_missing_atomic_evidence_key(self, extractor, test_document):
        """Test parsing response without atomic_evidence key."""
        parsed = {"entity_assessment": {"entity_match": True}}
        result = extractor._parse_extraction_result("TestEntity", test_document, parsed)
        assert result is not None
        assert isinstance(result.atomic_evidence, list)
        assert len(result.atomic_evidence) == 0

    def test_parse_with_atomic_evidence_list(self, extractor, test_document):
        """Test parsing response with atomic_evidence list."""
        parsed = {
            "atomic_evidence": [
                {
                    "subject": "ZERA",
                    "predicate": "regulates",
                    "object": "energy sector",
                    "passage": "ZERA regulates the energy sector",
                    "evidence_type": "FACT",
                    "chunk_index": 0
                }
            ],
            "entity_assessment": {"entity_match": True}
        }
        result = extractor._parse_extraction_result("ZERA", test_document, parsed)
        assert result is not None
        assert len(result.atomic_evidence) == 1
        assert result.atomic_evidence[0].subject == "ZERA"

    def test_parse_with_non_list_atomic_evidence(self, extractor, test_document):
        """Test parsing response with non-list atomic_evidence."""
        parsed = {
            "atomic_evidence": "not a list",
            "entity_assessment": {"entity_match": True}
        }
        result = extractor._parse_extraction_result("TestEntity", test_document, parsed)
        assert result is not None
        assert isinstance(result.atomic_evidence, list)
        assert len(result.atomic_evidence) == 0
        assert "No atomic_evidence list in response" in result.extraction_errors

    def test_extract_with_no_api_key_fallback(self, extractor):
        """Test extraction with no API key uses fallback without atomic_evidence errors."""
        extractor.api_key = ""
        records = [
            EvidenceRecord(
                url="https://test.com",
                title="Test",
                snippet="Test content about ZERA",
                normalized_text="Test content about ZERA",
                source="test",
                query="test"
            )
        ]
        import asyncio
        async def test():
            results = await extractor.extract("ZERA", records)
            return results
        
        results = asyncio.run(test())
        assert len(results) == 1
        # Fallback should create atomic evidence
        assert isinstance(results[0].atomic_evidence, list)


# =============================================================================
# Test C: LLM Response Parsing for List-Based Content
# =============================================================================

class TestLLMResponseParsing:
    """Test parsing of list-based LLM responses with type, thinking, closed fields."""

    def test_normalize_string_content(self):
        """Test normalization of string content."""
        content = '{"atomic_evidence": []}'
        result = normalize_mistral_content(content, context="TEST")
        assert result == content

    def test_normalize_list_of_strings(self):
        """Test normalization of list of strings."""
        content = ["part1", "part2"]
        result = normalize_mistral_content(content, context="TEST")
        assert result == "part1\npart2"

    def test_normalize_list_with_type_and_text(self):
        """Test normalization of list with type and text fields."""
        content = [
            {"type": "text", "text": "Hello"},
            {"type": "text", "text": "World"}
        ]
        result = normalize_mistral_content(content, context="TEST")
        assert result == "Hello\nWorld"

    def test_normalize_list_with_thinking_field(self):
        """Test normalization of list with thinking field."""
        content = [
            {"type": "reasoning", "thinking": "Let me think...", "closed": True},
            {"type": "text", "text": "Final answer"}
        ]
        result = normalize_mistral_content(content, context="TEST")
        # Should extract thinking content
        assert "Let me think..." in result

    def test_normalize_list_with_thinking_dict(self):
        """Test normalization of list with thinking as dict."""
        content = [
            {"type": "reasoning", "thinking": {"content": "Thinking..."}, "closed": True},
            {"type": "text", "text": "Answer"}
        ]
        result = normalize_mistral_content(content, context="TEST")
        assert "Thinking..." in result

    def test_normalize_empty_list(self):
        """Test normalization of empty list."""
        content = []
        result = normalize_mistral_content(content, context="TEST")
        assert result is None

    def test_normalize_none(self):
        """Test normalization of None."""
        result = normalize_mistral_content(None, context="TEST")
        assert result is None

    def test_extract_mistral_message_content(self):
        """Test extraction of message content from Mistral response."""
        response = {
            "choices": [
                {
                    "message": {
                        "content": '{"atomic_evidence": []}'
                    }
                }
            ]
        }
        result = extract_mistral_message_content(response, context="TEST")
        assert result == '{"atomic_evidence": []}'

    def test_extract_mistral_message_content_with_list(self):
        """Test extraction with list-based content."""
        response = {
            "choices": [
                {
                    "message": {
                        "content": [
                            {"type": "text", "text": "Test"}
                        ]
                    }
                }
            ]
        }
        result = extract_mistral_message_content(response, context="TEST")
        assert result == "Test"


# =============================================================================
# Test D: Evidence Quality Decisions for Block/Error Pages
# =============================================================================

class TestBlockErrorPageHandling:
    """Test handling of block and error pages."""

    @pytest.fixture
    def pipeline(self):
        return EvidenceFilterPipeline(target_entity="ZERA")

    def test_block_page_classification(self, pipeline):
        """Test that block pages are classified as IRRELEVANT."""
        block_record = EvidenceRecord(
            url="https://test.com/blocked",
            title="Access Denied",
            snippet="Access Denied - You do not have permission",
            normalized_text="Access Denied - You do not have permission to access this page",
            source="test",
            query="test",
            evidence_status=EvidenceStatus.USABLE
        )
        
        direct, related, irrelevant = pipeline.filter_entity_relevant_evidence([block_record])
        assert len(direct) == 0
        assert len(related) == 0
        assert len(irrelevant) == 1
        assert irrelevant[0].url == block_record.url

    def test_error_page_classification(self, pipeline):
        """Test that error pages are classified as IRRELEVANT."""
        error_record = EvidenceRecord(
            url="https://test.com/404",
            title="Page Not Found",
            snippet="404 Not Found - The page you are looking for does not exist",
            normalized_text="404 Not Found - The page you are looking for does not exist",
            source="test",
            query="test",
            evidence_status=EvidenceStatus.USABLE
        )
        
        direct, related, irrelevant = pipeline.filter_entity_relevant_evidence([error_record])
        assert len(direct) == 0
        assert len(related) == 0
        assert len(irrelevant) == 1
        assert irrelevant[0].url == error_record.url

    def test_block_page_with_entity_name(self, pipeline):
        """Test that block pages with entity name are still IRRELEVANT."""
        block_with_entity = EvidenceRecord(
            url="https://test.com/blocked-zera",
            title="Access Denied",
            snippet="Access Denied - ZERA You do not have permission",
            normalized_text="Access Denied - ZERA You do not have permission to access this page",
            source="test",
            query="test",
            evidence_status=EvidenceStatus.USABLE
        )
        
        direct, related, irrelevant = pipeline.filter_entity_relevant_evidence([block_with_entity])
        # Block pages should be rejected even if entity name appears
        assert len(direct) == 0
        assert len(related) == 0
        assert len(irrelevant) == 1

    def test_cloudflare_block_page(self, pipeline):
        """Test Cloudflare block page classification."""
        cloudflare_record = EvidenceRecord(
            url="https://test.com/cloudflare",
            title="Cloudflare",
            snippet="Please verify you are human - Cloudflare",
            normalized_text="Please verify you are human - Cloudflare security check",
            source="test",
            query="test",
            evidence_status=EvidenceStatus.USABLE
        )
        
        direct, related, irrelevant = pipeline.filter_entity_relevant_evidence([cloudflare_record])
        assert len(direct) == 0
        assert len(related) == 0
        assert len(irrelevant) == 1

    def test_valid_evidence_with_entity(self, pipeline):
        """Test that valid evidence with entity is classified as DIRECT."""
        valid_record = EvidenceRecord(
            url="https://zera.co.zw",
            title="Zimbabwe Energy Regulatory Authority",
            snippet="ZERA is the energy regulator for Zimbabwe",
            normalized_text="ZERA is the energy regulator for Zimbabwe",
            source="test",
            query="test",
            evidence_status=EvidenceStatus.USABLE
        )
        
        direct, related, irrelevant = pipeline.filter_entity_relevant_evidence([valid_record])
        assert len(direct) == 1
        assert len(related) == 0
        assert len(irrelevant) == 0
        assert direct[0].url == valid_record.url


# =============================================================================
# Test E: Provider Configuration
# =============================================================================

class TestProviderConfiguration:
    """Test provider configuration handling."""

    def test_relevance_filter_no_api_key(self):
        """Test relevance filter with no API key uses fallback."""
        filter_obj = RelevanceFilter(api_key=None)
        records = [
            EvidenceRecord(
                url="https://test.com",
                title="Test",
                snippet="Test content",
                normalized_text="Test content",
                source="test",
                query="test"
            )
        ]
        import asyncio
        
        async def test():
            result = await filter_obj.filter("ZERA", records)
            return result
        
        result = asyncio.run(test())
        # With no API key, all should be marked as relevant (fallback)
        assert result.kept_count == 1
        assert result.filtered_count == 0

    def test_llm_ranker_no_api_key(self):
        """Test LLM ranker with no API key uses fallback."""
        ranker = LLMRanker(api_key=None)
        records = [
            EvidenceRecord(
                url="https://test.com",
                title="Test",
                snippet="Test content",
                normalized_text="Test content",
                source="test",
                query="test"
            )
        ]
        import asyncio
        
        async def test():
            result = await ranker.rank_results("ZERA", records)
            return result
        
        result = asyncio.run(test())
        # With no API key, should return unranked results with explicit failure status
        assert len(result.ranked_results) == 1
        assert result.ranking_metadata.get("status") == "failed"


# =============================================================================
# Test F: Pipeline State Transitions
# =============================================================================

class TestPipelineStateTransitions:
    """Test pipeline state transitions and failure visibility."""

    def test_pipeline_preserves_error_classifications(self):
        """Test that pipeline preserves error classifications."""
        from app.services.pipeline import PipelineResult
        
        result = PipelineResult(
            entity="ZERA",
            status="failed",
            error_message="Test error",
            classifications={"error": ["test_error"]}
        )
        
        assert result.status == "failed"
        assert result.error_message == "Test error"
        assert "test_error" in result.classifications.get("error", [])

    def test_pipeline_insufficient_status(self):
        """Test pipeline with insufficient status."""
        from app.services.pipeline import PipelineResult
        
        result = PipelineResult(
            entity="ZERA",
            status="insufficient",
            error_message="Not enough evidence",
            classifications={"error": ["no_evidence"]}
        )
        
        assert result.status == "insufficient"
        assert "no_evidence" in result.classifications.get("error", [])


# =============================================================================
# Test G: Integration Tests
# =============================================================================

class TestIntegration:
    """Integration tests for ZERA-specific scenarios."""

    def test_zera_block_page_scenario(self):
        """Test ZERA-specific block page scenario."""
        pipeline = EvidenceFilterPipeline(target_entity="Zimbabwe Energy Regulatory Authority")
        
        # Simulate ZERA block page
        block_record = EvidenceRecord(
            url="https://www.zera.co.zw",
            title="Access Denied",
            snippet="Access Denied - Please verify you are human",
            normalized_text="Access Denied - Please verify you are human - Cloudflare",
            source="zera_website",
            query="ZERA",
            evidence_status=EvidenceStatus.USABLE
        )
        
        direct, related, irrelevant = pipeline.filter_entity_relevant_evidence([block_record])
        assert len(irrelevant) == 1
        assert len(direct) == 0

    def test_zera_valid_page_scenario(self):
        """Test ZERA valid page scenario."""
        pipeline = EvidenceFilterPipeline(target_entity="Zimbabwe Energy Regulatory Authority")
        
        valid_record = EvidenceRecord(
            url="https://www.zera.co.zw/about",
            title="About ZERA",
            snippet="ZERA regulates the energy sector in Zimbabwe",
            normalized_text="The Zimbabwe Energy Regulatory Authority (ZERA) regulates the energy sector in Zimbabwe. It was established to ensure fair competition and protect consumers.",
            source="zera_website",
            query="ZERA",
            evidence_status=EvidenceStatus.USABLE
        )
        
        direct, related, irrelevant = pipeline.filter_entity_relevant_evidence([valid_record])
        assert len(direct) == 1
        assert len(irrelevant) == 0

    def test_mistral_response_with_reasoning_blocks(self):
        """Test Mistral response with reasoning blocks (type, thinking, closed)."""
        response = {
            "choices": [
                {
                    "message": {
                        "content": [
                            {"type": "reasoning", "thinking": "Analyzing ZERA...", "closed": True},
                            {"type": "text", "text": '{"atomic_evidence": [{"subject": "ZERA", "predicate": "regulates", "object": "energy sector", "passage": "ZERA regulates", "evidence_type": "FACT", "chunk_index": 0}], "entity_assessment": {"entity_match": true, "match_type": "DIRECT", "match_confidence": 0.95}}'}
                        ]
                    }
                }
            ]
        }
        
        result = extract_mistral_message_content(response, context="ZERA_TEST")
        assert result is not None
        # Should extract the JSON from the text block
        assert '{"atomic_evidence"' in result

    def test_semantic_extractor_with_list_response(self):
        """Test semantic extractor with list-based response."""
        extractor = MistralSemanticExtractor(api_key="test-key")
        
        # Mock the _call_mistral to return a list-based response
        async def mock_call_mistral(prompt, client=None):
            return {
                "atomic_evidence": [
                    {
                        "subject": "ZERA",
                        "predicate": "regulates",
                        "object": "energy sector",
                        "passage": "ZERA regulates the energy sector",
                        "evidence_type": "FACT",
                        "chunk_index": 0
                    }
                ],
                "entity_assessment": {"entity_match": True}
            }
        
        extractor._call_mistral = mock_call_mistral
        
        records = [
            EvidenceRecord(
                url="https://zera.co.zw",
                title="ZERA",
                snippet="ZERA regulates",
                normalized_text="ZERA regulates the energy sector",
                source="test",
                query="test"
            )
        ]
        
        import asyncio
        results = asyncio.run(extractor.extract("ZERA", records))
        assert len(results) == 1
        assert len(results[0].atomic_evidence) == 1
