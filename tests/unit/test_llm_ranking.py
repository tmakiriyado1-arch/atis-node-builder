"""
Tests for LLM-based ranking of search results.

This test file verifies the LLM ranking functionality works correctly.
"""
from __future__ import annotations

import pytest
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.services.research.evidence import EvidenceRecord
from app.services.research.llm_ranking import LLMRanker, RankedResult, RankingResult


# =============================================================================
# Test LLM Ranking Module
# =============================================================================

class TestLLMRanking:
    """Test LLM-based ranking of evidence records."""
    
    def test_ranker_initialization(self):
        """Test that LLMRanker initializes correctly."""
        ranker = LLMRanker()
        assert ranker.api_key == ""
        assert ranker.model == "mistral-large-latest"
        assert ranker.max_results == 10
    
    def test_ranker_with_custom_config(self):
        """Test LLMRanker with custom configuration."""
        ranker = LLMRanker(
            api_key="test_key",
            model="test-model",
            max_results=5,
        )
        assert ranker.api_key == "test_key"
        assert ranker.model == "test-model"
        assert ranker.max_results == 5
    
    def test_ranked_result_creation(self):
        """Test RankedResult dataclass."""
        evidence = EvidenceRecord(
            url="https://example.com",
            title="Test Evidence",
            snippet="Test snippet",
        )
        
        ranked = RankedResult(
            evidence_record=evidence,
            rank_score=0.95,
            relevance="high",
            validation="valid",
            reasoning="This is highly relevant",
            query_variation="test query",
        )
        
        assert ranked.evidence_record == evidence
        assert ranked.rank_score == 0.95
        assert ranked.relevance == "high"
        assert ranked.validation == "valid"
        assert ranked.reasoning == "This is highly relevant"
        assert ranked.query_variation == "test query"
    
    def test_ranked_result_to_dict(self):
        """Test RankedResult.to_dict() method."""
        evidence = EvidenceRecord(
            url="https://example.com",
            title="Test Evidence",
            snippet="Test snippet",
        )
        
        ranked = RankedResult(
            evidence_record=evidence,
            rank_score=0.95,
            relevance="high",
            validation="valid",
            reasoning="This is highly relevant",
            query_variation="test query",
        )
        
        result = ranked.to_dict()
        
        assert result["url"] == "https://example.com"
        assert result["rank_score"] == 0.95
        assert result["relevance"] == "high"
        assert result["validation"] == "valid"
        assert result["query_variation"] == "test query"
    
    def test_ranking_result_creation(self):
        """Test RankingResult dataclass."""
        evidence1 = EvidenceRecord(url="https://example.com/1", title="Test 1", snippet="Test")
        evidence2 = EvidenceRecord(url="https://example.com/2", title="Test 2", snippet="Test")
        
        ranked1 = RankedResult(
            evidence_record=evidence1,
            rank_score=0.9,
            relevance="high",
            validation="valid",
            reasoning="Relevant",
            query_variation="query1",
        )
        ranked2 = RankedResult(
            evidence_record=evidence2,
            rank_score=0.7,
            relevance="medium",
            validation="valid",
            reasoning="Somewhat relevant",
            query_variation="query1",
        )
        
        ranking = RankingResult(
            ranked_results=[ranked1, ranked2],
            top_results=[ranked1],
            rejected_results=[ranked2],
            ranking_metadata={"total": 2, "top": 1},
        )
        
        assert len(ranking.ranked_results) == 2
        assert len(ranking.top_results) == 1
        assert len(ranking.rejected_results) == 1
        assert ranking.top_evidence == [evidence1]
    
    def test_ranking_result_empty(self):
        """Test RankingResult with no results."""
        ranking = RankingResult()
        
        assert len(ranking.ranked_results) == 0
        assert len(ranking.top_results) == 0
        assert len(ranking.rejected_results) == 0
        assert len(ranking.top_evidence) == 0


# =============================================================================
# Test LLM Ranking with Mock
# =============================================================================

class TestLLMRankingWithMock:
    """Test LLM ranking with mocked LLM calls."""
    
    @pytest.mark.asyncio
    async def test_rank_with_no_evidence(self):
        """Test ranking with no evidence returns empty result."""
        ranker = LLMRanker(api_key="test")
        
        result = await ranker.rank_results(
            "Test Entity",
            [],
            ["query1"],
            {},
        )
        
        assert len(result.ranked_results) == 0
    
    @pytest.mark.asyncio
    async def test_rank_with_no_api_key(self):
        """Test ranking with no API key returns unranked results."""
        ranker = LLMRanker(api_key=None)
        
        evidence = [
            EvidenceRecord(url="https://example.com/1", title="Test 1", snippet="Test"),
            EvidenceRecord(url="https://example.com/2", title="Test 2", snippet="Test"),
        ]
        
        result = await ranker.rank_results(
            "Test Entity",
            evidence,
            ["query1"],
            {},
        )
        
        # Should return all results with default ranking
        assert len(result.ranked_results) == 2
        assert len(result.top_results) == 2
        # All should have default values
        for ranked in result.ranked_results:
            assert ranked.rank_score == 0.5
            assert ranked.relevance == "medium"
            assert ranked.validation == "uncertain"
    
    @pytest.mark.asyncio
    async def test_select_top_results_no_ranking(self):
        """Test selecting top results with no ranking data."""
        ranker = LLMRanker(api_key=None)
        
        evidence = [
            EvidenceRecord(url="https://example.com/1", title="Test 1", snippet="Test"),
            EvidenceRecord(url="https://example.com/2", title="Test 2", snippet="Test"),
        ]
        
        # Create ranking result manually
        ranking_result = RankingResult(
            ranked_results=[
                RankedResult(
                    evidence_record=evidence[0],
                    rank_score=0.9,
                    relevance="high",
                    validation="valid",
                    reasoning="Good",
                    query_variation="query1",
                ),
                RankedResult(
                    evidence_record=evidence[1],
                    rank_score=0.7,
                    relevance="medium",
                    validation="valid",
                    reasoning="OK",
                    query_variation="query1",
                ),
            ],
        )
        
        selected = await ranker.select_top_results(
            ranking_result,
            "Test Entity",
            max_results=1,
        )
        
        # Should select top result by score
        assert len(selected) == 1
        assert selected[0].url == "https://example.com/1"
    
    @pytest.mark.asyncio
    async def test_rank_with_mock_client(self):
        """Test ranking with mocked HTTP client."""
        import httpx
        from unittest.mock import AsyncMock, MagicMock
        
        ranker = LLMRanker(api_key="test_key")
        
        # Create mock client
        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": '{"rankings": [{"index": 0, "rank_score": 0.9, "relevance": "high", "validation": "valid", "reasoning": "Good match"}]}'
                }
            }]
        }
        mock_client.post = AsyncMock(return_value=mock_response)
        
        evidence = [
            EvidenceRecord(url="https://example.com/1", title="Test", snippet="Test"),
        ]
        
        result = await ranker.rank_results(
            "Test Entity",
            evidence,
            ["query1"],
            {},
            client=mock_client,
        )
        
        assert len(result.ranked_results) == 1
        assert result.ranked_results[0].rank_score == 0.9


# =============================================================================
# Test LLM Ranking Edge Cases
# =============================================================================

class TestLLMRankingEdgeCases:
    """Test edge cases for LLM ranking."""
    
    @pytest.mark.asyncio
    async def test_rank_with_malformed_response(self):
        """Test ranking handles malformed LLM response."""
        import httpx
        from unittest.mock import AsyncMock, MagicMock
        
        ranker = LLMRanker(api_key="test_key")
        
        # Create mock client with malformed response
        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"invalid": "response"}
        mock_client.post = AsyncMock(return_value=mock_response)
        
        evidence = [
            EvidenceRecord(url="https://example.com/1", title="Test", snippet="Test"),
        ]
        
        result = await ranker.rank_results(
            "Test Entity",
            evidence,
            ["query1"],
            {},
            client=mock_client,
        )
        
        # Should return default ranking
        assert len(result.ranked_results) == 1
        assert result.ranked_results[0].rank_score == 0.5
    
    @pytest.mark.asyncio
    async def test_rank_with_http_error(self):
        """Test ranking handles HTTP errors."""
        import httpx
        from unittest.mock import AsyncMock, MagicMock
        
        ranker = LLMRanker(api_key="test_key")
        
        # Create mock client with HTTP error
        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(side_effect=httpx.HTTPStatusError("Error", request=MagicMock(), response=MagicMock()))
        
        evidence = [
            EvidenceRecord(url="https://example.com/1", title="Test", snippet="Test"),
        ]
        
        result = await ranker.rank_results(
            "Test Entity",
            evidence,
            ["query1"],
            {},
            client=mock_client,
        )
        
        # Should return default ranking
        assert len(result.ranked_results) == 1
        assert result.ranked_results[0].rank_score == 0.5
    
    def test_parse_rankings_with_code_block(self):
        """Test parsing rankings from code block response."""
        ranker = LLMRanker()
        
        response = """Here are the rankings:

```json
{
    "rankings": [
        {"index": 0, "rank_score": 0.9, "relevance": "high", "validation": "valid", "reasoning": "Good"},
        {"index": 1, "rank_score": 0.7, "relevance": "medium", "validation": "valid", "reasoning": "OK"}
    ]
}
```"""
        
        evidence = [
            EvidenceRecord(url="https://example.com/1", title="Test 1", snippet="Test"),
            EvidenceRecord(url="https://example.com/2", title="Test 2", snippet="Test"),
        ]
        
        result = ranker._parse_rankings(response, evidence, ["query1", "query1"])
        
        assert len(result.ranked_results) == 2
        assert result.ranked_results[0].rank_score == 0.9
        assert result.ranked_results[1].rank_score == 0.7
