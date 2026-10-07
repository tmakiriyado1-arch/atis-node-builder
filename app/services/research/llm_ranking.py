"""LLM-based ranking and validation of search results.

This module provides functionality to:
1. Generate multiple query variations for a given entity
2. Search with each variation
3. Use LLM to rank/validate results by relevance
4. Select best evidence based on LLM ranking

The core principle: LLM handles evidence quality assessment and ranking,
while the search system focuses on reliable evidence acquisition.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import httpx

from app import config
from app.logging import logger
from app.services.research.evidence import EvidenceRecord, deduplicate_evidence


@dataclass
class RankedResult:
    """A search result with LLM-assigned ranking and validation."""
    evidence_record: EvidenceRecord
    rank_score: float  # 0.0 to 1.0, higher is better
    relevance: str  # "high", "medium", "low", "irrelevant"
    validation: str  # "valid", "partial", "invalid", "uncertain"
    reasoning: str  # LLM's explanation for the ranking
    query_variation: str  # Which query variation found this result
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.evidence_record.url,
            "title": self.evidence_record.title,
            "rank_score": self.rank_score,
            "relevance": self.relevance,
            "validation": self.validation,
            "reasoning": self.reasoning,
            "query_variation": self.query_variation,
        }


@dataclass
class RankingResult:
    """Result of LLM ranking of multiple evidence items."""
    ranked_results: List[RankedResult] = field(default_factory=list)
    top_results: List[RankedResult] = field(default_factory=list)
    rejected_results: List[RankedResult] = field(default_factory=list)
    ranking_metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def top_evidence(self) -> List[EvidenceRecord]:
        """Get evidence records from top-ranked results."""
        return [r.evidence_record for r in self.top_results]


class LLMRanker:
    """Uses LLM to rank and validate search results for relevance.
    
    This class implements the core principle: LLM handles evidence quality
    assessment and ranking, while the search system focuses on reliable
    evidence acquisition.
    """
    
    RANKING_PROMPT = """You are an expert research assistant. Your task is to rank and validate search results
for relevance to a specific entity query. You will receive:
1. The entity name and context
2. Multiple search results (each with URL, title, and content snippet)

Rules:
- Rank results by relevance to the entity (0.0 to 1.0, where 1.0 is most relevant)
- Classify relevance as: "high", "medium", "low", or "irrelevant"
- Validate each result as: "valid", "partial", "invalid", or "uncertain"
- Provide brief reasoning for each ranking
- Focus on whether the content is actually about the entity, not just contains the keywords
- Be strict: if a result is about a different entity with a similar name, mark as "irrelevant"
- Consider the entity type and context when ranking

Response format (JSON only):
{{
    "rankings": [
        {{
            "url": "https://...",
            "rank_score": 0.95,
            "relevance": "high",
            "validation": "valid",
            "reasoning": "This page is directly about the entity..."
        }},
        ...
    ]
}}

Required: Return ONLY valid JSON, no other text."""
    
    SELECTION_PROMPT = """You are an expert research assistant. Your task is to select the best search results
from a ranked list for further processing.

You will receive:
1. The entity name and context
2. Ranked search results with their scores and reasoning

Rules:
- Select results that are clearly relevant to the entity
- Exclude results marked as "irrelevant" or "invalid"
- Prefer results with "high" relevance and "valid" validation
- Consider source authority (official websites, Wikipedia, reputable news)
- Return at most {max_results} results

Response format (JSON only):
{{
    "selected_indices": [0, 1, 2],
    "selected_urls": ["https://...", "https://..."],
    "rejected_indices": [3, 4],
    "rejected_reasons": ["irrelevant to entity", "false positive match"]
}}

Required: Return ONLY valid JSON, no other text."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        max_results: int = 25,  # PHASE 5: Increased from 10 to allow more results
        min_relevance: str = "medium",
        min_validation: str = "valid",
    ):
        self.api_key = api_key or config.MISTRAL_API_KEY or ""
        self.model = model or config.MISTRAL_MODEL or "mistral-large-latest"
        self.max_results = max_results
        self.min_relevance = min_relevance
        self.min_validation = min_validation
        
    async def rank_results(
        self,
        entity_name: str,
        evidence_records: Sequence[EvidenceRecord],
        query_variations: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> RankingResult:
        """Rank evidence records by relevance to the entity using LLM.
        
        Args:
            entity_name: The entity being researched
            evidence_records: List of evidence records to rank
            query_variations: The query variations that were used
            context: Optional context (entity_type, country, etc.)
            client: Optional HTTP client for reuse
            
        Returns:
            RankingResult with ranked evidence and metadata
        """
        if not evidence_records:
            return RankingResult()
        
        if not self.api_key:
            logger.warning("[LLM_RANKER] No Mistral API key, returning unranked results")
            # Return all results with default ranking
            return RankingResult(
                ranked_results=[
                    RankedResult(
                        evidence_record=er,
                        rank_score=0.5,
                        relevance="medium",
                        validation="uncertain",
                        reasoning="No LLM available for ranking",
                        query_variation=query_variations[0] if query_variations else "",
                    )
                    for er in evidence_records
                ],
                top_results=[
                    RankedResult(
                        evidence_record=er,
                        rank_score=0.5,
                        relevance="medium",
                        validation="uncertain",
                        reasoning="No LLM available for ranking",
                        query_variation=query_variations[0] if query_variations else "",
                    )
                    for er in evidence_records
                ],
            )
        
        # Prepare evidence for LLM
        evidence_data = []
        for idx, er in enumerate(evidence_records):
            # Track which query variation found this
            query_var = query_variations[idx] if query_variations and idx < len(query_variations) else ""
            
            evidence_data.append({
                "index": idx,
                "url": er.url,
                "title": er.title or "",
                "content": er.snippet or er.content or "",
                "source": er.source,
                "query_variation": query_var,
            })
        
        # Build prompt
        context_str = ""
        if context:
            context_parts = []
            if context.get("entity_type"):
                context_parts.append(f"Entity type: {context['entity_type']}")
            if context.get("country"):
                context_parts.append(f"Country: {context['country']}")
            if context.get("aliases"):
                context_parts.append(f"Aliases: {', '.join(context['aliases'])}")
            if context_parts:
                context_str = "Context: " + ". ".join(context_parts) + ". "
        
        prompt = self.RANKING_PROMPT.format(
            entity_name=entity_name,
            context=context_str,
        ) + f"\n\nEntity: {entity_name}\n\n" + \
               f"Results to rank:\n{json.dumps(evidence_data, ensure_ascii=False)}\n\n" + \
               "Return your rankings as JSON."
        
        # Call LLM
        response = await self._call_llm(prompt, client=client)
        if not response:
            logger.warning("[LLM_RANKER] LLM call failed, returning unranked results")
            return RankingResult(
                ranked_results=[
                    RankedResult(
                        evidence_record=er,
                        rank_score=0.5,
                        relevance="uncertain",
                        validation="uncertain",
                        reasoning="LLM call failed",
                        query_variation=query_variations[idx] if query_variations and idx < len(query_variations) else "",
                    )
                    for idx, er in enumerate(evidence_records)
                ],
                ranking_metadata={"status": "failed", "error": "LLM call returned None"},
            )
        
        # Parse response
        try:
            rankings = self._parse_rankings(response, evidence_records, query_variations)
            logger.info(f"[LLM_RANKER] Ranking successful, ranked {len(rankings.ranked_results)} results")
            return rankings
        except Exception as e:
            logger.error(f"[LLM_RANKER] Failed to parse rankings: {e}")
            logger.error(f"[LLM_RANKER] LLM ranking failed, returning unranked results")
            return RankingResult(
                ranked_results=[
                    RankedResult(
                        evidence_record=er,
                        rank_score=0.5,
                        relevance="uncertain",
                        validation="uncertain",
                        reasoning=f"Ranking parse failed: {e}",
                        query_variation=query_variations[idx] if query_variations and idx < len(query_variations) else "",
                    )
                    for idx, er in enumerate(evidence_records)
                ],
                ranking_metadata={"status": "failed", "error": str(e)},
            )
    
    async def select_top_results(
        self,
        ranking_result: RankingResult,
        entity_name: str,
        max_results: Optional[int] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> List[EvidenceRecord]:
        """Select top results from a ranking using LLM validation.
        
        Args:
            ranking_result: The ranking result to select from
            entity_name: The entity being researched
            max_results: Maximum number of results to return
            client: Optional HTTP client for reuse
            
        Returns:
            List of selected evidence records
        """
        if not ranking_result.ranked_results:
            return []
        
        if not self.api_key:
            # Without LLM, just return top results by score
            sorted_results = sorted(
                ranking_result.ranked_results,
                key=lambda r: r.rank_score,
                reverse=True
            )
            return [r.evidence_record for r in sorted_results[:max_results or self.max_results]]
        
        # Prepare data for selection
        ranked_data = []
        for idx, rr in enumerate(ranking_result.ranked_results):
            ranked_data.append({
                "index": idx,
                "url": rr.evidence_record.url,
                "rank_score": rr.rank_score,
                "relevance": rr.relevance,
                "validation": rr.validation,
                "reasoning": rr.reasoning,
            })
        
        max_select = max_results or self.max_results
        prompt = self.SELECTION_PROMPT.format(max_results=max_select) + \
                f"\n\nEntity: {entity_name}\n\n" + \
                f"Ranked results:\n{json.dumps(ranked_data, ensure_ascii=False)}\n\n" + \
                "Return your selection as JSON."
        
        response = await self._call_llm(prompt, client=client)
        if not response:
            # Fallback to score-based selection
            sorted_results = sorted(
                ranking_result.ranked_results,
                key=lambda r: r.rank_score,
                reverse=True
            )
            return [r.evidence_record for r in sorted_results[:max_select]]
        
        # Parse selection
        try:
            selection = json.loads(response)
            selected_indices = selection.get("selected_indices", [])
            
            # Get selected results in the order specified by LLM
            selected = []
            for idx in selected_indices:
                if 0 <= idx < len(ranking_result.ranked_results):
                    selected.append(ranking_result.ranked_results[idx])
            
            # Return in the order the LLM specified (by index order)
            return [r.evidence_record for r in selected[:max_select]]
        except Exception as e:
            logger.error(f"[LLM_RANKER] Failed to parse selection: {e}")
            # Fallback to score-based selection
            sorted_results = sorted(
                ranking_result.ranked_results,
                key=lambda r: r.rank_score,
                reverse=True
            )
            return [r.evidence_record for r in sorted_results[:max_select]]
    
    def _parse_rankings(
        self,
        response: str,
        evidence_records: Sequence[EvidenceRecord],
        query_variations: Optional[List[str]] = None,
    ) -> RankingResult:
        """Parse LLM response into RankingResult."""
        try:
            # Try to extract JSON from response
            # Handle case where response has markdown code block
            if "```json" in response:
                response = response.split("```json")[1].split("```")[0].strip()
            elif "```" in response:
                response = response.split("```")[1].split("```")[0].strip()
            
            data = json.loads(response)
            rankings = data.get("rankings", [])
            
            ranked_results = []
            for rank_data in rankings:
                idx = rank_data.get("index", 0)
                if 0 <= idx < len(evidence_records):
                    query_var = ""
                    if query_variations and idx < len(query_variations):
                        query_var = query_variations[idx]
                    
                    ranked_result = RankedResult(
                        evidence_record=evidence_records[idx],
                        rank_score=float(rank_data.get("rank_score", 0.5)),
                        relevance=rank_data.get("relevance", "medium"),
                        validation=rank_data.get("validation", "uncertain"),
                        reasoning=rank_data.get("reasoning", ""),
                        query_variation=query_var,
                    )
                    ranked_results.append(ranked_result)
            
            # Sort by rank score
            ranked_results.sort(key=lambda r: r.rank_score, reverse=True)
            
            # Separate top and rejected
            top_results = [
                r for r in ranked_results
                if r.relevance in ("high", "medium") and r.validation in ("valid", "partial")
            ]
            rejected_results = [
                r for r in ranked_results
                if r.relevance in ("low", "irrelevant") or r.validation in ("invalid", "uncertain")
            ]
            
            return RankingResult(
                ranked_results=ranked_results,
                top_results=top_results[:self.max_results],
                rejected_results=rejected_results,
            )
        except Exception as e:
            logger.error(f"[LLM_RANKER] Failed to parse response: {e}")
            # Return default ranking
            return RankingResult(
                ranked_results=[
                    RankedResult(
                        evidence_record=er,
                        rank_score=0.5,
                        relevance="medium",
                        validation="uncertain",
                        reasoning=f"Parse error: {e}",
                        query_variation=query_variations[idx] if query_variations and idx < len(query_variations) else "",
                    )
                    for idx, er in enumerate(evidence_records)
                ],
            )
    
    async def _call_llm(
        self,
        prompt: str,
        client: Optional[httpx.AsyncClient] = None,
    ) -> Optional[str]:
        """Call Mistral API with canonical response normalization."""
        from app.services.research.mistral_response import extract_mistral_message_content
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0,
            "top_p": 1.0,
            "response_format": {"type": "json_object"},
        }
        
        try:
            if client is not None:
                response = await client.post(
                    "https://api.mistral.ai/v1/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=30.0,
                )
            else:
                async with httpx.AsyncClient(headers=headers, timeout=30.0) as http_client:
                    response = await http_client.post(
                        "https://api.mistral.ai/v1/chat/completions",
                        json=payload,
                    )
            
            response.raise_for_status()
            data = response.json()
            
            # Use canonical normalization
            content = extract_mistral_message_content(data, context="LLM_RANKER")
            
            if content is not None:
                logger.info(f"[LLM_RANKER] LLM_RESPONSE_TYPE=str LLM_NORMALIZED_TEXT_LENGTH={len(content)}")
            else:
                logger.warning(f"[LLM_RANKER] LLM_NORMALIZATION_RESULT=None")
            
            return content
            
        except Exception as e:
            logger.error(f"[LLM_RANKER] LLM call failed: {e}")
            return None


async def rank_and_select_evidence(
    entity_name: str,
    evidence_records: Sequence[EvidenceRecord],
    query_variations: Optional[List[str]] = None,
    context: Optional[Dict[str, Any]] = None,
    max_results: int = 10,
    client: Optional[httpx.AsyncClient] = None,
) -> Tuple[List[EvidenceRecord], Dict[str, Any]]:
    """Convenience function to rank and select evidence using LLM.
    
    This is the main entry point for LLM-based evidence ranking.
    
    Args:
        entity_name: The entity being researched
        evidence_records: Evidence records to rank and select from
        query_variations: Query variations that were used
        context: Optional context
        max_results: Maximum results to return
        client: Optional HTTP client
        
    Returns:
        Tuple of (selected_evidence, ranking_metadata)
    """
    ranker = LLMRanker(max_results=max_results)
    
    # Rank results
    ranking_result = await ranker.rank_results(
        entity_name,
        evidence_records,
        query_variations,
        context,
        client=client,
    )
    
    # Select top results
    selected = await ranker.select_top_results(
        ranking_result,
        entity_name,
        max_results,
        client=client,
    )
    
    # Build metadata
    metadata = {
        "total_ranked": len(ranking_result.ranked_results),
        "top_selected": len(selected),
        "rejected": len(ranking_result.rejected_results),
        "ranking_result": ranking_result,
    }
    
    return selected, metadata
