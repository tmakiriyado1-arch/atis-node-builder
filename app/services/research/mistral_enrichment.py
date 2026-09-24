"""Single Mistral enrichment path for candidate research claims."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Iterable, List, Sequence

import httpx

from app import config
from app.services.research.evidence import EvidenceRecord, EvidenceStatus, ExtractionQuality


def _canonical_url_map(evidence_records: Sequence[EvidenceRecord]) -> dict[str, EvidenceRecord]:
    mapping: dict[str, EvidenceRecord] = {}
    for record in evidence_records:
        if not record or not record.url:
            continue
        mapping[record.url] = record
    return mapping


def _dedupe_claim_texts(claims: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    deduped: List[str] = []
    for claim in claims:
        normalized = str(claim).strip()
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
    return deduped


def _create_evidence_chunks(
    evidence_records: Sequence[EvidenceRecord],
    max_chunk_size: int = 2000,
    overlap: int = 200,
) -> List[Dict[str, Any]]:
    """Create deterministic chunks from evidence content.
    
    This function creates overlapping chunks from the full content of evidence records,
    ensuring that Mistral receives substantive evidence rather than just the first 2000 chars.
    
    Args:
        evidence_records: List of evidence records with full content
        max_chunk_size: Maximum size of each chunk (default 2000 chars)
        overlap: Number of overlapping characters between chunks (default 200)
        
    Returns:
        List of chunk dicts with provenance information
    """
    chunks = []
    
    for record in evidence_records:
        if not record or not record.url:
            continue
        
        # Use full content if available, otherwise fall back to snippet
        content = getattr(record, 'content', None) or record.snippet or ""
        
        # Skip if content is empty or evidence is unusable
        if not content.strip():
            continue
        
        # Skip if evidence is marked as unusable
        if hasattr(record, 'evidence_status') and record.evidence_status == EvidenceStatus.UNUSABLE:
            continue
        
        # If content is short enough, use as single chunk
        if len(content) <= max_chunk_size:
            chunks.append({
                "url": record.url,
                "title": record.title,
                "content": content,
                "source": record.source,
                "query": record.query,
                "chunk_index": 0,
                "total_chunks": 1,
            })
            continue
        
        # Split long content into overlapping chunks
        start = 0
        chunk_index = 0
        while start < len(content):
            end = min(start + max_chunk_size, len(content))
            chunk = content[start:end]
            
            chunks.append({
                "url": record.url,
                "title": record.title,
                "content": chunk,
                "source": record.source,
                "query": record.query,
                "chunk_index": chunk_index,
                "total_chunks": (len(content) + max_chunk_size - overlap - 1) // (max_chunk_size - overlap),
            })
            
            # Move to next chunk with overlap
            start = end - overlap if end > overlap else end
            chunk_index += 1
    
    return chunks


async def enrich_evidence_with_mistral(
    entity_name: str,
    evidence_records: Sequence[EvidenceRecord],
    api_key: str | None = None,
    model: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> List[ResearchClaim]:
    """Convert supplied evidence into candidate ResearchClaim objects using Mistral JSON output."""
    if not evidence_records:
        return []

    key = (api_key or config.MISTRAL_API_KEY or "").strip()
    if not key:
        return []

    url_map = _canonical_url_map(evidence_records)
    
    # Create deterministic chunks from full content
    evidence_chunks = _create_evidence_chunks(evidence_records)
    
    # Build evidence context with full content chunks
    evidence_context = []
    for chunk in evidence_chunks:
        evidence_context.append({
            "title": chunk["title"],
            "url": chunk["url"],
            "content": chunk["content"],
            "source": chunk["source"],
            "query": chunk["query"],
            "chunk_index": chunk["chunk_index"],
            "total_chunks": chunk["total_chunks"],
        })

    prompt = (
        "You are extracting candidate research claims from full evidence content.\n"
        "You receive an entity and evidence content chunks (from full page crawls).\n"
        "Rules:\n"
        "- Only use the supplied evidence content.\n"
        "- Do not use outside knowledge.\n"
        "- Do not guess.\n"
        "- Do not invent URLs.\n"
        "- Do not fabricate facts.\n"
        "- If evidence is insufficient, return no claim.\n"
        "- Each claim must be traceable to the source URL(s) provided.\n"
        "- Return JSON only.\n\n"
        f"Entity: {entity_name or 'unknown'}\n"
        f"Evidence: {json.dumps(evidence_context, ensure_ascii=False)}\n\n"
        "Required JSON response: {\"claims\":[{\"subject\":\"\",\"predicate\":\"\",\"object\":\"\",\"claim_text\":\"\",\"evidence_urls\":[\"\"]}]}"
    )

    payload = {
        "model": model or config.MISTRAL_MODEL or "mistral-large-latest",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "top_p": 1.0,
        "response_format": {"type": "json_object"},
    }

    headers = {
        "Authorization": f"Bearer {key}",
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
    except Exception:
        return []

    try:
        json_response = response.json()
    except (ValueError, TypeError):
        return []

    choices = json_response.get("choices") or []
    if not isinstance(choices, list) or not choices:
        return []

    raw_content = choices[0].get("message", {}).get("content") if isinstance(choices[0], dict) else ""
    if not isinstance(raw_content, str):
        return []

    try:
        parsed = json.loads(raw_content)
    except (TypeError, ValueError):
        return []

    claims_payload = parsed.get("claims") if isinstance(parsed, dict) else None
    if not isinstance(claims_payload, list) or not claims_payload:
        return []

    from app.services.research_engine import ResearchClaim

    accepted: List[ResearchClaim] = []
    seen_claims: set[str] = set()

    for item in claims_payload:
        if not isinstance(item, dict):
            continue

        claim_text = str(item.get("claim_text") or "").strip()
        evidence_urls = item.get("evidence_urls") or []
        if not claim_text or not isinstance(evidence_urls, list) or not evidence_urls:
            continue

        valid_urls: List[str] = []
        for candidate in evidence_urls:
            value = str(candidate or "").strip()
            if not value or value not in url_map:
                continue
            valid_urls.append(value)
        if not valid_urls:
            continue

        normalized_text = claim_text.casefold()
        if normalized_text in seen_claims:
            continue
        seen_claims.add(normalized_text)

        first_url = valid_urls[0]
        source_record = url_map.get(first_url)
        accepted.append(
            ResearchClaim(
                claim=claim_text,
                field_name="candidate_claim",
                source_url=first_url,
                source_title=source_record.title if source_record else None,
                evidence_passage=source_record.snippet if source_record else "",
                source_type="webpage",
                confidence=0.0,
                extraction_method="mistral",
                extracted_at=datetime.now(timezone.utc),
            )
        )

    return accepted
