"""Canonical evidence records for NORA search provenance."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


_TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
    "msclkid",
    "mc_cid",
    "mc_eid",
}


@dataclass
class EvidenceRecord:
    """Canonical representation of discovered evidence from a search result."""

    url: str
    title: str
    snippet: str
    source: str = "public_web_search"
    query: str = ""
    entity_id: Optional[str] = None
    entity_name: str = ""
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    original_url: Optional[str] = None
    queries: List[str] = field(default_factory=list)
    metadata: Optional[Dict[str, Any]] = field(default_factory=dict)


def normalize_url(raw_url: Any) -> str:
    """Normalize obvious duplicate URL variants while preserving meaningful query parameters."""
    if raw_url is None:
        return ""

    value = str(raw_url).strip()
    if not value:
        return ""

    try:
        parsed = urlsplit(value)
    except ValueError:
        return ""

    if parsed.scheme.lower() not in {"http", "https"}:
        return ""
    if not parsed.netloc:
        return ""

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        return ""

    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1]

    filtered = [
        (key, val)
        for key, val in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in _TRACKING_PARAMS
    ]
    query = urlencode(filtered, doseq=True)

    normalized = urlunsplit(
        (
            parsed.scheme.lower(),
            hostname if ":" not in hostname else parsed.netloc.lower(),
            path,
            query,
            "",
        )
    )
    return normalized


def normalize_search_result(
    result: Any,
    *,
    entity_id: Optional[str] = None,
    entity_name: str = "",
    query: str = "",
    source: str = "public_web_search",
    retrieved_at: Optional[datetime] = None,
) -> Optional[EvidenceRecord]:
    """Convert a provider result that looks like title/url/snippet into a canonical evidence record."""
    if result is None or not isinstance(result, Mapping):
        return None

    raw_url = result.get("url") or result.get("link") or result.get("href") or ""
    if not isinstance(raw_url, str):
        raw_url = str(raw_url or "").strip()
    if not raw_url:
        return None

    canonical_url = normalize_url(raw_url)
    if not canonical_url:
        return None

    title = result.get("title") or result.get("name") or "Untitled result"
    title_text = str(title).strip() or "Untitled result"
    snippet = result.get("snippet") or result.get("description") or result.get("text") or title_text
    snippet_text = str(snippet).strip() or title_text

    evidence_query = str(query or entity_name or "").strip()
    record = EvidenceRecord(
        url=canonical_url,
        title=title_text,
        snippet=snippet_text,
        source=source,
        query=evidence_query,
        entity_id=entity_id,
        entity_name=str(entity_name or "").strip(),
        retrieved_at=retrieved_at or datetime.now(timezone.utc),
        original_url=raw_url.strip(),
        queries=[evidence_query] if evidence_query else [],
    )
    return record


def deduplicate_evidence(records: Iterable[EvidenceRecord]) -> List[EvidenceRecord]:
    """Deduplicate evidence by canonical URL while preserving provenance across queries."""
    deduped: Dict[str, EvidenceRecord] = {}
    for record in records:
        if not record or not record.url:
            continue
        existing = deduped.get(record.url)
        if existing is None:
            deduped[record.url] = record
            continue

        if record.query and record.query not in existing.queries:
            existing.queries.append(record.query)
        if record.original_url and record.original_url != existing.original_url:
            existing.original_url = record.original_url
        if record.entity_name and not existing.entity_name:
            existing.entity_name = record.entity_name
        if record.entity_id and not existing.entity_id:
            existing.entity_id = record.entity_id
    return list(deduped.values())
