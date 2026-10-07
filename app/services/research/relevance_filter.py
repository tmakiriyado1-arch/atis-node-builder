"""LLM-based relevance filtering for evidence records.

This module provides functionality to filter evidence records based on their
relevance to the target entity using an LLM. It helps eliminate irrelevant
URLs that may have been crawled but don't actually contain information about
the target entity.

The filtering happens AFTER crawling but BEFORE creating claims, ensuring
that only relevant evidence is processed.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import httpx

from app import config
from app.services.research.evidence import EvidenceRecord, EvidenceStatus, ExtractionQuality


# Minimum content length to consider for relevance filtering
MIN_CONTENT_LENGTH = 100

# Block page indicators (content that suggests the page is not accessible)
BLOCK_PAGE_INDICATORS = [
    "access denied",
    "forbidden",
    "you do not have permission",
    "permission denied",
    "not authorized",
    "unauthorized",
    "blocked",
    "cloudflare",
    "bot detected",
    "are you a robot",
    "please verify you are human",
    "captcha",
    "security check",
    "access temporarily blocked",
    "sorry, you have been blocked",
    "please turn on javascript",
    "javascript is required",
    "enable cookies",
    "browser verification",
]

# Error page indicators (pages that returned 200 but are actually errors)
ERROR_PAGE_INDICATORS = [
    "internal server error",
    "500 error",
    "404 not found",
    "page not found",
    "the page you are looking for",
    "this page doesn't exist",
    "error 404",
    "error 500",
    "error 502",
    "error 503",
    "service unavailable",
    "server error",
    "application error",
]


@dataclass
class RelevanceResult:
    """Result of relevance filtering for a single evidence item."""
    url: str
    relevant: bool
    reason: str
    confidence: float
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "relevant": self.relevant,
            "reason": self.reason,
            "confidence": self.confidence,
        }


@dataclass
class RelevanceFilterResult:
    """Result of filtering a batch of evidence records."""
    relevant_evidence: List[EvidenceRecord]
    irrelevant_evidence: List[EvidenceRecord]
    results: List[RelevanceResult]
    filtered_count: int
    kept_count: int
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "filtered_count": self.filtered_count,
            "kept_count": self.kept_count,
            "results": [r.to_dict() for r in self.results],
        }


class RelevanceFilter:
    """LLM-based relevance filter for evidence records.
    
    This filter uses an LLM to determine which evidence items are actually
    about the target entity. It helps eliminate:
    - Irrelevant URLs (e.g., personal profiles, unrelated organizations)
    - Block pages (access denied, captcha, etc.)
    - Error pages (404, 500, etc.)
    - Thin content (pages with insufficient meaningful text)
    """

    RELEVANCE_FILTER_PROMPT = """You are NORA's semantic source-relevance classifier.

Your task is to determine whether a crawled webpage is genuinely relevant
to research about the TARGET ENTITY.

The target entity does NOT need to be mentioned literally in the page body.

Use all supplied evidence:
1. canonical entity name
2. URL
3. domain
4. page title
5. extracted page content

A page may be relevant even when the canonical entity name does not
appear in the body. For example, a page on the official domain whose title
and content clearly describe the institution may be relevant even if the
institution's full name is omitted from the body.

Do not use outside knowledge to invent identity. Only use the information
provided in the evidence text.

Do not mark a page relevant merely because it contains a generic topic
associated with the entity. The page must be ABOUT the target entity.

Distinguish:
- "about the target" vs "mentions the target"
- "same organization/domain" vs "unrelated organization"

For each evidence item, return:
- url: the URL
- relevant: true/false (is this page genuinely about the target entity?)
- reason: brief explanation of why
- confidence: 0.0-1.0 (how confident are you?)
- identity_basis: brief explanation of identity assessment (e.g., "official-domain + title + institutional context", "page content describes the same institution using an abbreviated name", "unrelated organization despite similar terminology")

Return as JSON array of objects.

Entity: {entity_name}

Evidence items:
{evidence_items}

Rules:
- Be strict but not rigid: a page can be relevant without literal name match
- Consider URL, domain, title, and content together
- Look for direct mentions, descriptions, aliases, abbreviations, or clear contextual identity
- Mark as irrelevant if the page is a block page, error page, or has no meaningful content
- Mark as irrelevant if the page is about a different person, organization, or topic
- Only use the evidence provided, do not invent facts from pretrained knowledge"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        min_content_length: int = MIN_CONTENT_LENGTH,
        batch_size: int = 10,
    ):
        """Initialize the relevance filter.
        
        Args:
            api_key: Mistral API key for LLM filtering
            model: Mistral model to use
            min_content_length: Minimum content length to consider for filtering
            batch_size: Number of evidence items to filter in one LLM call
        """
        self.api_key = api_key or config.MISTRAL_API_KEY
        self.model = model or config.MISTRAL_MODEL or "mistral-large-latest"
        self.min_content_length = min_content_length
        self.batch_size = batch_size

    def _format_evidence_items(
        self,
        evidence_records: Sequence[EvidenceRecord],
    ) -> str:
        """Format evidence records for the LLM prompt."""
        items = []
        for idx, record in enumerate(evidence_records):
            if not record or not record.url:
                continue
            
            # Use normalized_text if available, otherwise content, otherwise snippet
            text = getattr(record, 'normalized_text', None) or \
                  getattr(record, 'content', None) or \
                  record.snippet or ""
            
            # Truncate for prompt length
            if len(text) > 2000:
                text = text[:2000] + "..."
            
            items.append(
                f"  {idx + 1}. URL: {record.url}\n"
                f"     Title: {record.title or 'No title'}\n"
                f"     Content: {text[:500] if text else 'No content'}{'...' if len(text) > 500 else ''}"
            )
        
        return "\n".join(items)

    def _pre_filter_by_quality(
        self,
        evidence_records: Sequence[EvidenceRecord],
    ) -> tuple[List[EvidenceRecord], List[EvidenceRecord]]:
        """Pre-filter evidence by quality metrics before LLM filtering.
        
        Deterministic rejection BEFORE the LLM should be limited to clearly unusable material:
        - completely empty content
        - explicit access-denied/block page
        - explicit 404/error page
        - obvious CAPTCHA/security challenge
        - genuinely unusable crawler output
        
        Do NOT reject merely because:
        - the content is short
        - the target name isn't present
        - the page was classified SOFT_404 solely because of a simplistic heuristic
        
        A short page may still contain useful identity information through:
        - URL
        - title
        - domain
        - content
        
        The LLM must be allowed to evaluate those signals.
        
        Returns:
            (filtered_out, kept_for_llm)
        """
        filtered_out = []
        kept = []
        
        for record in evidence_records:
            if not record or not record.url:
                filtered_out.append(record)
                continue
            
            # Get content for checks
            text = getattr(record, 'normalized_text', None) or \
                  getattr(record, 'content', None) or \
                  record.snippet or ""
            
            # Check for completely empty content
            if not text or not text.strip():
                filtered_out.append(record)
                continue
            
            text_lower = text.lower()
            
            # Check for explicit block page content
            is_block_page = any(indicator in text_lower for indicator in BLOCK_PAGE_INDICATORS)
            
            # Check for explicit error page content
            is_error_page = any(indicator in text_lower for indicator in ERROR_PAGE_INDICATORS)
            
            # Only filter out if explicitly a block or error page
            # Do NOT filter based on extraction quality classifications alone
            if is_block_page or is_error_page:
                filtered_out.append(record)
                continue
            
            # Keep all other evidence for LLM evaluation
            # This includes short content, SOFT_404, etc. - the LLM should decide
            kept.append(record)
        
        return filtered_out, kept

    async def filter(
        self,
        entity_name: str,
        evidence_records: Sequence[EvidenceRecord],
        client: Optional[httpx.AsyncClient] = None,
    ) -> RelevanceFilterResult:
        """Filter evidence records by relevance to the target entity.
        
        Args:
            entity_name: The target entity name
            evidence_records: List of evidence records to filter
            client: Optional HTTP client for LLM API calls
            
        Returns:
            RelevanceFilterResult with filtered evidence and results
        """
        from app.logging import logger
        
        if not evidence_records:
            return RelevanceFilterResult(
                relevant_evidence=[],
                irrelevant_evidence=[],
                results=[],
                filtered_count=0,
                kept_count=0,
            )
        
        logger.info(f"[RELEVANCE_FILTER] entity={entity_name} input={len(evidence_records)}")
        
        # Step 1: Pre-filter by quality
        quality_filtered, for_llm = self._pre_filter_by_quality(evidence_records)
        
        # Log quality filter results
        if quality_filtered:
            for record in quality_filtered:
                if record:
                    text = getattr(record, 'normalized_text', None) or \
                          getattr(record, 'content', None) or \
                          record.snippet or ""
                    logger.info(f"[RELEVANCE_FILTER] QUALITY_FILTERED url={record.url[:80]} content_length={len(text)} reason=block_or_error_page")
        
        # If all filtered by quality, return early
        if not for_llm:
            logger.info(f"[RELEVANCE_FILTER] All evidence filtered by quality, returning early")
            return RelevanceFilterResult(
                relevant_evidence=[],
                irrelevant_evidence=list(evidence_records),
                results=[
                    RelevanceResult(
                        url=record.url if record else "",
                        relevant=False,
                        reason="Quality filter: low content or unusable",
                        confidence=1.0,
                    )
                    for record in evidence_records
                ],
                filtered_count=len(evidence_records),
                kept_count=0,
            )
        
        # Step 2: LLM-based relevance filtering in batches
        relevant_evidence = []
        irrelevant_evidence = list(quality_filtered)
        results = []
        
        # Process in batches
        for i in range(0, len(for_llm), self.batch_size):
            batch = list(for_llm[i:i + self.batch_size])
            batch_results = await self._filter_batch(entity_name, batch, client)
            
            for result in batch_results:
                results.append(result)
                if result.relevant:
                    # Find the corresponding evidence record
                    for record in batch:
                        if record.url == result.url:
                            relevant_evidence.append(record)
                            break
                else:
                    # Find the corresponding evidence record
                    for record in batch:
                        if record.url == result.url:
                            irrelevant_evidence.append(record)
                            break
        
        # Log final results
        logger.info(f"[RELEVANCE_FILTER] llm_evaluated={len(for_llm)} relevant={len(relevant_evidence)} irrelevant={len(irrelevant_evidence)}")
        
        for result in results:
            logger.info(f"[RELEVANCE_FILTER] url={result.url[:80]} relevant={result.relevant} confidence={result.confidence:.2f} reason={result.reason}")
        
        return RelevanceFilterResult(
            relevant_evidence=relevant_evidence,
            irrelevant_evidence=irrelevant_evidence,
            results=results,
            filtered_count=len(irrelevant_evidence),
            kept_count=len(relevant_evidence),
        )

    async def _filter_batch(
        self,
        entity_name: str,
        batch: List[EvidenceRecord],
        client: Optional[httpx.AsyncClient] = None,
    ) -> List[RelevanceResult]:
        """Filter a batch of evidence records using LLM.
        
        Args:
            entity_name: The target entity name
            batch: List of evidence records to filter
            client: Optional HTTP client
            
        Returns:
            List of RelevanceResult objects
        """
        if not self.api_key:
            # If no API key, mark all as relevant (fallback behavior)
            return [
                RelevanceResult(
                    url=record.url if record else "",
                    relevant=True,
                    reason="No API key available for relevance filtering",
                    confidence=0.5,
                )
                for record in batch
            ]
        
        # Build prompt
        evidence_items = self._format_evidence_items(batch)
        prompt = self.RELEVANCE_FILTER_PROMPT.format(
            entity_name=entity_name,
            evidence_items=evidence_items,
        )
        
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0,
            "top_p": 1.0,
            "response_format": {"type": "json_object"},
        }
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
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
            
            json_response = response.json()
            
            # Use canonical normalization
            from app.services.research.mistral_response import extract_mistral_message_content
            raw_content = extract_mistral_message_content(json_response, context="RELEVANCE_FILTER")
            
            if raw_content is None:
                logger.warning(f"[RELEVANCE_FILTER] LLM_NORMALIZATION_RESULT=None, cannot parse response")
                logger.warning(f"[RELEVANCE_FILTER] LLM filtering failed, returning fallback")
                # Do NOT mark as relevant=True - this is an LLM failure
                # Return a result that clearly indicates failure
                return [
                    RelevanceResult(
                        url=record.url if record else "",
                        relevant=False,
                        reason="LLM filtering failed: no content returned",
                        confidence=0.0,
                    )
                    for record in batch
                ]
            
            # Parse JSON response
            try:
                parsed = json.loads(raw_content)
                logger.info(f"[RELEVANCE_FILTER] JSON_PARSE_RESULT=success")
            except (TypeError, ValueError) as e:
                logger.warning(f"[RELEVANCE_FILTER] JSON_PARSE_RESULT=failure error={e}")
                logger.warning(f"[RELEVANCE_FILTER] LLM filtering failed, returning fallback")
                # Do NOT mark as relevant=True - this is an LLM failure
                return [
                    RelevanceResult(
                        url=record.url if record else "",
                        relevant=False,
                        reason=f"LLM filtering failed: invalid JSON ({e})",
                        confidence=0.0,
                    )
                    for record in batch
                ]
            
            # Parse results
            if not isinstance(parsed, list):
                logger.warning(f"[RELEVANCE_FILTER] LLM returned non-array response: type={type(parsed).__name__}")
                logger.warning(f"[RELEVANCE_FILTER] LLM filtering failed, returning fallback")
                # Do NOT mark as relevant=True - this is an LLM failure
                return [
                    RelevanceResult(
                        url=record.url if record else "",
                        relevant=False,
                        reason="LLM filtering failed: non-array response",
                        confidence=0.0,
                    )
                    for record in batch
                ]
            
            results = []
            for item in parsed:
                if not isinstance(item, dict):
                    continue
                
                url = str(item.get("url") or "").strip()
                relevant = bool(item.get("relevant", True))
                reason = str(item.get("reason") or "").strip() or "No reason provided"
                confidence = float(item.get("confidence") or 0.5)
                
                results.append(RelevanceResult(
                    url=url,
                    relevant=relevant,
                    reason=reason,
                    confidence=confidence,
                ))
            
            # If we got fewer results than batch size, fill in defaults
            if len(results) < len(batch):
                batch_urls = {record.url for record in batch if record.url}
                returned_urls = {r.url for r in results}
                missing_urls = batch_urls - returned_urls
                
                for url in missing_urls:
                    results.append(RelevanceResult(
                        url=url,
                        relevant=True,
                        reason="Not evaluated by LLM",
                        confidence=0.5,
                    ))
            
            return results
            
        except Exception as e:
            # On any error, fallback to marking all as relevant
            return [
                RelevanceResult(
                    url=record.url if record else "",
                    relevant=True,
                    reason=f"LLM filtering failed: {str(e)}",
                    confidence=0.5,
                )
                for record in batch
            ]


async def filter_relevant_evidence(
    entity_name: str,
    evidence_records: Sequence[EvidenceRecord],
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    min_content_length: int = MIN_CONTENT_LENGTH,
    batch_size: int = 10,
    client: Optional[httpx.AsyncClient] = None,
) -> RelevanceFilterResult:
    """Convenience function to filter evidence by relevance.
    
    Args:
        entity_name: The target entity name
        evidence_records: List of evidence records to filter
        api_key: Mistral API key for LLM filtering
        model: Mistral model to use
        min_content_length: Minimum content length to consider
        batch_size: Number of evidence items to filter in one LLM call
        client: Optional HTTP client
        
    Returns:
        RelevanceFilterResult with filtered evidence
    """
    filter_obj = RelevanceFilter(
        api_key=api_key,
        model=model,
        min_content_length=min_content_length,
        batch_size=batch_size,
    )
    return await filter_obj.filter(entity_name, evidence_records, client)
