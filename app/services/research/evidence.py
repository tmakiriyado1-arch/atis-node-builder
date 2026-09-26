"""Canonical evidence records for NORA search provenance."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Iterable, List, Mapping, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


class SourceType(str, Enum):
    """Classification of source provenance for evidence weighting."""
    OFFICIAL = "official"           # Official organization/government website
    GOVERNMENT = "government"       # Government domain
    REGULATOR = "regulator"         # Regulatory authority website
    LEGISLATION = "legislation"       # Laws, regulations, official documents
    INSTITUTIONAL = "institutional" # Institutional publications
    ACADEMIC = "academic"           # Academic/research institutions
    INDUSTRY = "industry"           # Industry publications
    NEWS = "news"                   # News articles
    DIRECTORY = "directory"         # Business directories, listings
    SEARCH_DISCOVERED = "search_discovered"  # Discovered via search
    WIKIPEDIA = "Wikipedia"          # Wikipedia pages
    WIKIDATA = "Wikidata"           # Wikidata entries
    OTHER = "other"                 # Other sources


class RetrievalStatus(str, Enum):
    """Status of HTTP retrieval operation."""
    SUCCESS = "success"              # HTTP 2xx response received
    HTTP_ERROR = "http_error"        # HTTP 4xx or 5xx error
    TIMEOUT = "timeout"              # Request timeout
    CONNECTION_ERROR = "connection_error"  # Connection failed
    CONTENT_TYPE_REJECTED = "content_type_rejected"  # Unsupported content type
    REDIRECT_LOOP = "redirect_loop"  # Too many redirects
    

class ExtractionQuality(str, Enum):
    """Quality classification of extracted content."""
    SUBSTANTIVE = "substantive"      # Meaningful, detailed content
    THIN = "thin"                  # Very little content
    EMPTY = "empty"                # No content extracted
    BLOCK_PAGE = "block_page"      # Access denied/blocked page
    JS_SHELL = "js_shell"          # JavaScript-only page with no content
    ERROR_PAGE = "error_page"      # Server error page (returned with 200)
    NAVIGATION = "navigation"      # Navigation page only
    SOFT_404 = "soft_404"          # Page returns 200 but is actually a 404
    

class EvidenceStatus(str, Enum):
    """Overall evidence usability classification."""
    USABLE = "usable"               # Can be used as research evidence
    THIN = "thin"                  # Limited value but may be usable
    UNUSABLE = "unusable"           # Cannot be used as research evidence


# Authoritative source domains and patterns
AUTHORITATIVE_DOMAINS = {
    SourceType.OFFICIAL: [
        "sapp.co.zw",
        "zera.co.zw",
        "zesa.co.zw",
        "gov.zw",
        "go.zw",
    ],
    SourceType.GOVERNMENT: [
        "gov.",
        "go.",
        "parliament.",
        "ministry.",
        "department.",
    ],
    SourceType.REGULATOR: [
        "regulatory",
        "authority",
        "commission",
        "regulator",
    ],
    SourceType.LEGISLATION: [
        "act",
        "law",
        "statute",
        "gazette",
        "legislation",
    ],
    SourceType.INSTITUTIONAL: [
        "worldbank.org",
        "imf.org",
        "afdb.org",
        "sadc.int",
        "au.int",
        "un.org",
    ],
    SourceType.ACADEMIC: [
        "edu.",
        "ac.",
        "research",
        "university",
    ],
    SourceType.WIKIPEDIA: [
        "wikipedia.org",
    ],
    SourceType.WIKIDATA: [
        "wikidata.org",
    ],
}


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
    content: str = ""  # Full extracted content (not just snippet)
    source: str = "public_web_search"
    query: str = ""
    entity_id: Optional[str] = None
    entity_name: str = ""
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    original_url: Optional[str] = None
    queries: List[str] = field(default_factory=list)
    metadata: Optional[Dict[str, Any]] = field(default_factory=dict)
    # Quality classification fields
    retrieval_status: RetrievalStatus = RetrievalStatus.SUCCESS
    extraction_quality: ExtractionQuality = ExtractionQuality.SUBSTANTIVE
    evidence_status: EvidenceStatus = EvidenceStatus.USABLE
    # Provenance fields
    http_status: Optional[int] = None
    content_type: str = ""
    final_url: Optional[str] = None


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


def classify_source_type(url: str, title: str = "", snippet: str = "", metadata: Optional[Dict[str, Any]] = None) -> SourceType:
    """Classify the source type of a URL based on domain and content patterns.
    
    Args:
        url: The URL to classify
        title: Optional page title for additional context
        snippet: Optional page snippet for additional context
        metadata: Optional metadata dict that may contain source hints
        
    Returns:
        SourceType classification
    """
    url_lower = url.lower()
    
    # Check metadata first if available
    if metadata and isinstance(metadata, dict):
        source_hint = metadata.get("source_type") or metadata.get("source")
        if source_hint:
            source_hint_lower = str(source_hint).lower()
            for source_type in SourceType:
                if source_type.value.lower() == source_hint_lower:
                    return source_type
    
    # Check for Wikidata
    if "wikidata.org" in url_lower:
        return SourceType.WIKIDATA
    
    # Check for Wikipedia
    if "wikipedia.org" in url_lower:
        return SourceType.WIKIPEDIA
    
    # Check authoritative domains
    for source_type, domains in AUTHORITATIVE_DOMAINS.items():
        for domain in domains:
            if domain.lower() in url_lower:
                return source_type
    
    # Check for government patterns
    gov_patterns = ["gov.", "go.", "parliament.", "ministry.", "department."]
    for pattern in gov_patterns:
        if pattern in url_lower:
            return SourceType.GOVERNMENT
    
    # Check for regulator patterns in URL or title
    regulator_patterns = ["regulatory", "authority", "commission", "regulator"]
    for pattern in regulator_patterns:
        if pattern in url_lower or pattern in title.lower():
            return SourceType.REGULATOR
    
    # Check for legislation patterns
    legislation_patterns = ["act", "law", "statute", "gazette", "legislation"]
    for pattern in legislation_patterns:
        if pattern in url_lower or pattern in title.lower():
            return SourceType.LEGISLATION
    
    # Check for institutional domains
    institutional_domains = ["worldbank.org", "imf.org", "afdb.org", "sadc.int", "au.int", "un.org"]
    for domain in institutional_domains:
        if domain in url_lower:
            return SourceType.INSTITUTIONAL
    
    # Check for academic patterns
    academic_patterns = ["edu.", "ac.", "university", "research", "institute"]
    for pattern in academic_patterns:
        if pattern in url_lower:
            return SourceType.ACADEMIC
    
    # Check for news patterns
    news_patterns = ["news", "article", "press", "media", "journal"]
    for pattern in news_patterns:
        if pattern in url_lower or pattern in title.lower():
            return SourceType.NEWS
    
    # Check for directory patterns
    directory_patterns = ["directory", "listing", "yellow pages", "business directory"]
    for pattern in directory_patterns:
        if pattern in url_lower or pattern in title.lower():
            return SourceType.DIRECTORY
    
    # Default to search_discovered
    return SourceType.SEARCH_DISCOVERED


def classify_extraction_quality(content: str, html: str = "", url: str = "", status_code: int = 200) -> ExtractionQuality:
    """Classify the quality of extracted content.
    
    This function determines whether crawled content is substantive evidence
    or various forms of unusable content (block pages, JS shells, etc.)
    
    Args:
        content: The extracted text content
        html: The raw HTML (for detecting JS shells, etc.)
        url: The URL for context
        status_code: HTTP status code
        
    Returns:
        ExtractionQuality classification
    """
    if not content or not content.strip():
        return ExtractionQuality.EMPTY
    
    content_lower = content.lower()
    html_lower = html.lower() if html else ""
    
    # Check for block pages / access denied
    block_indicators = [
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
    
    for indicator in block_indicators:
        if indicator in content_lower or indicator in html_lower:
            return ExtractionQuality.BLOCK_PAGE
    
    # Check for error pages (returned with 200 but are actually errors)
    error_indicators = [
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
    
    for indicator in error_indicators:
        if indicator in content_lower or indicator in html_lower:
            return ExtractionQuality.ERROR_PAGE
    
    # Check for JavaScript shells (pages with almost no text content but lots of JS)
    # If HTML has many script tags but extracted text is minimal
    if html:
        # Count script tags vs text content
        script_count = html_lower.count("<script")
        text_length = len(content.strip())
        
        # If there are many scripts but very little text, it's likely a JS shell
        if script_count > 2 and text_length < 200:
            return ExtractionQuality.JS_SHELL
    
    # Check for navigation-only pages
    nav_indicators = [
        "navigation",
        "menu",
        "home",
        "about",
        "contact",
        "login",
        "sign in",
        "register",
    ]
    
    # If content is very short and mostly navigation links
    if len(content.strip()) < 100:
        # Check if it's mostly navigation terms
        words = content_lower.split()
        nav_words = sum(1 for w in words if any(nav in w for nav in nav_indicators))
        if nav_words > len(words) * 0.5:  # More than 50% are navigation words
            return ExtractionQuality.NAVIGATION
    
    # Check for soft 404 (page returns 200 but has no real content)
    # Very short content with generic messages
    soft_404_indicators = [
        "welcome",
        "hello",
        "index of",
        "apache",
        "nginx",
        "iis",
        "web server",
    ]
    
    if len(content.strip()) < 150:
        for indicator in soft_404_indicators:
            if indicator in content_lower:
                return ExtractionQuality.SOFT_404
    
    # Check for thin content
    if len(content.strip()) < 200:
        return ExtractionQuality.THIN
    
    # Default to substantive
    return ExtractionQuality.SUBSTANTIVE


def classify_evidence_status(
    extraction_quality: ExtractionQuality,
    retrieval_status: RetrievalStatus,
) -> EvidenceStatus:
    """Determine overall evidence usability from extraction quality and retrieval status.
    
    Args:
        extraction_quality: The quality of extracted content
        retrieval_status: The status of HTTP retrieval
        
    Returns:
        EvidenceStatus classification
    """
    # If retrieval failed, evidence is unusable
    if retrieval_status in (RetrievalStatus.HTTP_ERROR, RetrievalStatus.TIMEOUT, 
                            RetrievalStatus.CONNECTION_ERROR, RetrievalStatus.REDIRECT_LOOP):
        return EvidenceStatus.UNUSABLE
    
    # If extraction produced unusable content
    if extraction_quality in (ExtractionQuality.EMPTY, ExtractionQuality.BLOCK_PAGE,
                              ExtractionQuality.JS_SHELL, ExtractionQuality.ERROR_PAGE,
                              ExtractionQuality.NAVIGATION, ExtractionQuality.SOFT_404):
        return EvidenceStatus.UNUSABLE
    
    # Thin content is borderline
    if extraction_quality == ExtractionQuality.THIN:
        return EvidenceStatus.THIN
    
    # Substantive content is usable
    return EvidenceStatus.USABLE


def _canonicalize_content(content: str) -> str:
    """Conservatively canonicalize evidence content for duplicate detection.
    
    This normalization is semantically lossless and only addresses:
    - Leading/trailing whitespace
    - Normalized internal whitespace (multiple spaces -> single space)
    - Normalized line endings (CR/LF -> space)
    
    Does NOT:
    - Lowercase text
    - Remove punctuation
    - Remove stopwords
    - Remove any words
    
    Args:
        content: The raw evidence content string
        
    Returns:
        Canonicalized content string for hashing
    """
    if not content:
        return ""
    # Normalize line endings to spaces first
    content = content.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    # Normalize multiple whitespace to single space
    content = re.sub(r'\s+', ' ', content)
    # Trim leading/trailing whitespace
    return content.strip()


def _content_fingerprint(content: str) -> str:
    """Generate a deterministic fingerprint for evidence content.
    
    Uses SHA-256 hash of canonicalized content for exact duplicate detection.
    
    Args:
        content: The evidence content string
        
    Returns:
        Hex digest of SHA-256 hash
    """
    canonical = _canonicalize_content(content)
    if not canonical:
        return ""
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def deduplicate_evidence(records: Iterable[EvidenceRecord]) -> List[EvidenceRecord]:
    """Deduplicate evidence by canonical URL AND content fingerprint.
    
    This function performs two levels of deduplication:
    1. URL-level: Records with the same canonical URL are merged (preserves provenance)
    2. Content-level: Records with identical canonical content are deduplicated,
       retaining only the first occurrence.
    
    Content deduplication is CONSERVATIVE - only exact duplicates after
    canonicalization are removed. Different content, punctuation differences,
    or case differences are NOT treated as duplicates.
    
    Args:
        records: Iterable of EvidenceRecord objects
        
    Returns:
        List of deduplicated EvidenceRecord objects
    """
    # First pass: URL-level deduplication (existing behavior)
    # Use normalized URL as key to ensure URL normalization is respected
    url_deduped: Dict[str, EvidenceRecord] = {}
    for record in records:
        if not record or not record.url:
            continue
        
        # Normalize URL for deduplication key
        normalized_url = normalize_url(record.url)
        if not normalized_url:
            continue
            
        existing = url_deduped.get(normalized_url)
        if existing is None:
            # Add the record's own query to its queries list if not already present
            if record.query and record.query not in record.queries:
                record.queries.append(record.query)
            url_deduped[normalized_url] = record
            continue

        # Merge provenance from duplicate into existing
        if record.query and record.query not in existing.queries:
            existing.queries.append(record.query)
        if record.original_url and record.original_url != existing.original_url:
            existing.original_url = record.original_url
        if record.entity_name and not existing.entity_name:
            existing.entity_name = record.entity_name
        if record.entity_id and not existing.entity_id:
            existing.entity_id = record.entity_id
    
    # Second pass: Content-level deduplication
    # Use URL-deduped records as input, deduplicate by content fingerprint
    content_deduped: Dict[str, EvidenceRecord] = {}
    for record in url_deduped.values():
        if not record:
            continue
        
        # Use content for fingerprinting (prefer full content, fall back to snippet)
        content = getattr(record, 'content', None) or record.snippet or ""
        fingerprint = _content_fingerprint(content)
        
        if not fingerprint:
            # If no fingerprint (empty content), keep the record
            # Use URL as fallback key to preserve at least URL deduplication
            if record.url:
                content_deduped[record.url] = record
            continue
        
        existing = content_deduped.get(fingerprint)
        if existing is None:
            content_deduped[fingerprint] = record
            continue
        
        # Merge provenance from duplicate into existing record
        # Queries: accumulate all unique queries
        if record.query and record.query not in existing.queries:
            existing.queries.append(record.query)
        
        # Original URLs: keep first one (cannot merge multiple distinct original URLs)
        # This is a limitation - we retain the first record's original_url
        # If the duplicate has an original_url and the existing doesn't, use the duplicate's
        if not existing.original_url and record.original_url:
            existing.original_url = record.original_url
        
        # Entity name: prefer non-empty value
        if record.entity_name and not existing.entity_name:
            existing.entity_name = record.entity_name
        
        # Entity ID: prefer non-empty value
        if record.entity_id and not existing.entity_id:
            existing.entity_id = record.entity_id
    
    return list(content_deduped.values())
