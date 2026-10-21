"""Page crawler for acquiring full content from discovered URLs.

This module provides functionality to crawl web pages and extract their content
for use as research evidence. It handles HTML pages and can be extended to support
other content types (PDF, documents, etc.).

Key improvements:
- Streaming HTTP retrieval with bounded content length enforcement
- Proper HTTP status classification with raise_for_status()
- Consistent error handling with proper RetrievalStatus/ExtractionQuality/EvidenceStatus
- HTTP client lifecycle management with connection reuse
- Enhanced timeout policy with explicit connect/read/write/pool timeouts
- Better diagnostic logging with failure phase identification
"""
from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup

from app.logging_config import logger
from app.services.research.evidence import (
    ExtractionQuality,
    RetrievalStatus,
    EvidenceStatus,
    classify_extraction_quality,
    classify_evidence_status,
)


# Common tracking parameters to remove from URLs
_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "mc_cid", "mc_eid", "msclkid",
    "_ga", "_gid", "_gl", "_hsenc", "_openstat",
    "__s", "click_id", "cust", "ref", "source", "campaign",
}

# Non-content file extensions to skip
_NON_CONTENT_EXTENSIONS = {
    ".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
    ".woff", ".woff2", ".ttf", ".eot", ".mp3", ".mp4", ".avi",
    ".mov", ".wmv", ".flv", ".zip", ".tar", ".gz", ".rar",
}

# Default timeout configuration
DEFAULT_TIMEOUT_CONFIG = httpx.Timeout(
    connect=5.0,
    read=10.0,
    write=5.0,
    pool=5.0,
)

# Maximum content length to stream (100KB)
DEFAULT_MAX_CONTENT_LENGTH = 100000


@dataclass
class CrawlResult:
    """Result of crawling a single URL."""
    url: str
    final_url: str  # After following redirects
    status_code: int
    success: bool
    content: str
    content_type: str
    title: str
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    # Quality classification fields
    retrieval_status: RetrievalStatus = RetrievalStatus.SUCCESS
    extraction_quality: ExtractionQuality = ExtractionQuality.SUBSTANTIVE
    evidence_status: EvidenceStatus = EvidenceStatus.USABLE


@dataclass
class CrawlStats:
    """Statistics for a crawl operation."""
    urls_attempted: int = 0
    urls_succeeded: int = 0
    urls_failed: int = 0
    urls_skipped: int = 0
    failure_reasons: Dict[str, int] = field(default_factory=dict)


class PageCrawler:
    """Crawls web pages and extracts content for research evidence.
    
    This crawler is designed to:
    - Fetch and follow redirects
    - Extract meaningful text content from HTML
    - Preserve provenance (source URL, final URL, discovery metadata)
    - Handle failures gracefully without stopping other crawls
    - Normalize URLs to avoid duplicate crawling
    - Use streaming to enforce content length limits during download
    
    Key architectural decisions:
    - HTTP client is created per crawl_url() call for backward compatibility
    - For multi-URL crawling (crawl_urls), a single client is reused across all URLs
    - Content length is enforced during streaming, not after buffering
    - HTTP status codes are explicitly checked with raise_for_status()
    - All failure paths set consistent retrieval_status, extraction_quality, and evidence_status
    """

    def __init__(
        self,
        timeout: float = 15.0,
        max_content_length: int = DEFAULT_MAX_CONTENT_LENGTH,
        user_agent: str = "Mozilla/5.0 (compatible; NORAResearchBot/1.0; +https://github.com/tmakiriyado1-arch/atis-node-builder)",
        max_concurrent: int = 5,
    ) -> None:
        """Initialize the page crawler.
        
        Args:
            timeout: Overall timeout for requests (used as default for all timeout components)
            max_content_length: Maximum bytes to download per page
            user_agent: User-Agent string for HTTP requests
            max_concurrent: Maximum concurrent crawls
        """
        self.timeout = timeout
        self.max_content_length = max_content_length
        self.user_agent = user_agent
        self.max_concurrent = max_concurrent
        
        # Build timeout config from single timeout value for backward compatibility
        self.timeout_config = httpx.Timeout(
            connect=min(timeout, 5.0),
            read=min(timeout, 10.0),
            write=min(timeout, 5.0),
            pool=min(timeout, 5.0),
        )
        
        # Overall per-URL deadline (covers entire request lifecycle)
        self.overall_timeout = timeout
        
        self.headers = {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }

    async def _fetch_with_streaming(
        self,
        client: httpx.AsyncClient,
        url: str,
    ) -> Tuple[httpx.Response, str, int, bool]:
        """Fetch URL with streaming and enforce content length limit.
        
        This method:
        1. Sends the request and gets the response headers
        2. Checks Content-Length header if present and rejects if too large
        3. Streams the response body while enforcing the byte limit
        4. Returns (response, content, bytes_received, was_truncated)
        
        Args:
            client: HTTPX async client
            url: URL to fetch
            
        Returns:
            Tuple of (response, content, bytes_received, was_truncated)
            
        Raises:
            httpx.HTTPStatusError: If HTTP status is not 2xx
            httpx.TimeoutException: If timeout occurs
            httpx.ConnectError: If connection fails
            ValueError: If Content-Length exceeds limit before streaming
        """
        start_time = time.monotonic()
        
        # Send request to get headers
        response = await client.send(
            httpx.Request("GET", url, headers=self.headers),
            stream=True,
        )
        
        # Check for HTTP errors explicitly
        # This will raise httpx.HTTPStatusError for 4xx/5xx responses
        response.raise_for_status()
        
        # Get final URL after redirects
        final_url = str(response.url)
        status_code = response.status_code
        content_type = response.headers.get("Content-Type", "").lower()
        
        # Check Content-Length header first
        content_length_header = response.headers.get("Content-Length")
        if content_length_header is not None:
            try:
                content_length = int(content_length_header)
                if content_length > self.max_content_length:
                    # Reject before reading body - header indicates it's too large
                    logger.warning(
                        f"[PAGE_CRAWLER] Content-Length {content_length} exceeds limit {self.max_content_length} for {url}"
                    )
                    return response, "", 0, True
            except (ValueError, TypeError):
                # Invalid Content-Length header, continue with streaming
                pass
        
        # Stream the response with byte limit
        content_bytes = b""
        bytes_received = 0
        was_truncated = False
        
        async for chunk in response.aiter_bytes():
            if bytes_received >= self.max_content_length:
                was_truncated = True
                break
            
            content_bytes += chunk
            bytes_received += len(chunk)
            
            if bytes_received >= self.max_content_length:
                was_truncated = True
                break
        
        # Decode content using HTTPX's response encoding behavior
        # Try to get encoding from response
        encoding = response.encoding
        if encoding is None:
            # Try to detect from content-type header
            charset = response.headers.get("Content-Type", "")
            if "charset=" in charset.lower():
                encoding = charset.split("charset=")[1].split(";")[0].strip()
            else:
                encoding = "utf-8"
        
        try:
            content = content_bytes.decode(encoding, errors="replace")
        except (UnicodeDecodeError, LookupError):
            # Fallback to utf-8 with replace
            try:
                content = content_bytes.decode("utf-8", errors="replace")
            except Exception:
                content = content_bytes.decode("latin-1", errors="replace")
        
        elapsed_ms = (time.monotonic() - start_time) * 1000
        logger.debug(
            f"[PAGE_CRAWLER] Fetched {url} -> {final_url} "
            f"status={status_code} bytes={bytes_received} "
            f"truncated={was_truncated} elapsed_ms={elapsed_ms:.0f}"
        )
        
        return response, content, bytes_received, was_truncated

    async def crawl_url(
        self,
        url: str,
        discovery_metadata: Optional[Dict[str, Any]] = None,
    ) -> CrawlResult:
        """Crawl a single URL and extract its content.
        
        Args:
            url: The URL to crawl
            discovery_metadata: Optional metadata about how this URL was discovered
                (e.g., search provider, rank, query)
            
        Returns:
            CrawlResult with the page content or failure information
        """
        # Normalize URL first
        normalized_url = normalize_url(url)
        if not normalized_url:
            return CrawlResult(
                url=url,
                final_url="",
                status_code=0,
                success=False,
                content="",
                content_type="",
                title="",
                error="Invalid URL",
                metadata=discovery_metadata or {},
                retrieval_status=RetrievalStatus.CONNECTION_ERROR,
                extraction_quality=ExtractionQuality.EMPTY,
                evidence_status=EvidenceStatus.UNUSABLE,
            )
        
        # Create a new HTTP client for this single URL crawl
        # This ensures proper cleanup and isolation
        try:
            start_time = time.monotonic()
            
            async with httpx.AsyncClient(
                headers=self.headers,
                timeout=self.timeout_config,
                follow_redirects=True,
                limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
            ) as client:
                try:
                    # Use overall timeout wrapper
                    response, raw_content, bytes_received, was_truncated = await asyncio.wait_for(
                        self._fetch_with_streaming(client, normalized_url),
                        timeout=self.overall_timeout,
                    )
                    
                    # Get final URL and status from response
                    final_url = str(response.url)
                    status_code = response.status_code
                    content_type = response.headers.get("Content-Type", "").lower()
                    
                    elapsed_ms = (time.monotonic() - start_time) * 1000
                    
                    # Check if we should process this content type
                    if not self._should_crawl_content_type(content_type):
                        logger.info(
                            f"[PAGE_CRAWLER] Rejected content type {content_type} for {url} "
                            f"elapsed_ms={elapsed_ms:.0f}"
                        )
                        return CrawlResult(
                            url=url,
                            final_url=final_url,
                            status_code=status_code,
                            success=False,
                            content="",
                            content_type=content_type,
                            title="",
                            error=f"Unsupported content type: {content_type}",
                            metadata=discovery_metadata or {},
                            retrieval_status=RetrievalStatus.CONTENT_TYPE_REJECTED,
                            extraction_quality=ExtractionQuality.EMPTY,
                            evidence_status=EvidenceStatus.UNUSABLE,
                        )
                    
                    # Check for non-content URLs (images, etc.)
                    if self._is_non_content_url(final_url):
                        logger.info(
                            f"[PAGE_CRAWLER] Rejected non-content URL {final_url} "
                            f"elapsed_ms={elapsed_ms:.0f}"
                        )
                        return CrawlResult(
                            url=url,
                            final_url=final_url,
                            status_code=status_code,
                            success=False,
                            content="",
                            content_type=content_type,
                            title="",
                            error="Non-content URL (image, stylesheet, etc.)",
                            metadata=discovery_metadata or {},
                            retrieval_status=RetrievalStatus.CONTENT_TYPE_REJECTED,
                            extraction_quality=ExtractionQuality.EMPTY,
                            evidence_status=EvidenceStatus.UNUSABLE,
                        )
                    
                    # Check if content was truncated due to size limit
                    if was_truncated and not raw_content:
                        # Content-Length exceeded limit before streaming
                        logger.warning(
                            f"[PAGE_CRAWLER] Content-Length exceeded limit for {url} "
                            f"elapsed_ms={elapsed_ms:.0f}"
                        )
                        return CrawlResult(
                            url=url,
                            final_url=final_url,
                            status_code=status_code,
                            success=False,
                            content="",
                            content_type=content_type,
                            title="",
                            error=f"Content too large: Content-Length exceeds {self.max_content_length} bytes",
                            metadata=discovery_metadata or {},
                            retrieval_status=RetrievalStatus.CONTENT_TYPE_REJECTED,
                            extraction_quality=ExtractionQuality.EMPTY,
                            evidence_status=EvidenceStatus.UNUSABLE,
                        )
                    
                    # Check if we have any content at all
                    if not raw_content:
                        logger.warning(
                            f"[PAGE_CRAWLER] Empty content received for {url} "
                            f"status={status_code} elapsed_ms={elapsed_ms:.0f}"
                        )
                        return CrawlResult(
                            url=url,
                            final_url=final_url,
                            status_code=status_code,
                            success=False,
                            content="",
                            content_type=content_type,
                            title="",
                            error="Empty response body",
                            metadata=discovery_metadata or {},
                            retrieval_status=RetrievalStatus.HTTP_ERROR,
                            extraction_quality=ExtractionQuality.EMPTY,
                            evidence_status=EvidenceStatus.UNUSABLE,
                        )
                    
                    # Extract title and content
                    title, content, html_content = self._extract_content(
                        raw_content, content_type, final_url
                    )
                    
                    # Classify extraction quality
                    extraction_quality = classify_extraction_quality(
                        content, 
                        html_content if html_content else raw_content,
                        final_url,
                        status_code
                    )
                    
                    # For HTTP success (2xx), mark as success
                    # For 4xx/5xx, we would have raised HTTPStatusError above
                    # So if we get here with a response, it's a 2xx status
                    retrieval_status = RetrievalStatus.SUCCESS
                    
                    # Classify evidence status
                    evidence_status = classify_evidence_status(
                        extraction_quality,
                        retrieval_status
                    )
                    
                    # Log size limit truncation if it happened
                    if was_truncated:
                        logger.info(
                            f"[PAGE_CRAWLER] Content truncated to {self.max_content_length} bytes for {url} "
                            f"elapsed_ms={elapsed_ms:.0f}"
                        )
                        # Add metadata about truncation
                        metadata = (discovery_metadata or {}).copy()
                        metadata["content_truncated"] = True
                        metadata["bytes_received"] = bytes_received
                        metadata["max_content_length"] = self.max_content_length
                        
                        return CrawlResult(
                            url=url,
                            final_url=final_url,
                            status_code=status_code,
                            success=True,
                            content=content,
                            content_type=content_type,
                            title=title,
                            metadata=metadata,
                            retrieval_status=retrieval_status,
                            extraction_quality=extraction_quality,
                            evidence_status=evidence_status,
                        )
                    
                    return CrawlResult(
                        url=url,
                        final_url=final_url,
                        status_code=status_code,
                        success=True,
                        content=content,
                        content_type=content_type,
                        title=title,
                        metadata=discovery_metadata or {},
                        retrieval_status=retrieval_status,
                        extraction_quality=extraction_quality,
                        evidence_status=evidence_status,
                    )
                    
                except asyncio.TimeoutError as e:
                    elapsed_ms = (time.monotonic() - start_time) * 1000
                    logger.error(
                        f"[PAGE_CRAWLER] Timeout (overall deadline) crawling {url}: {e} "
                        f"elapsed_ms={elapsed_ms:.0f}"
                    )
                    return CrawlResult(
                        url=url,
                        final_url="",
                        status_code=0,
                        success=False,
                        content="",
                        content_type="",
                        title="",
                        error=f"Timeout after {self.overall_timeout}s: {e}",
                        metadata=discovery_metadata or {},
                        retrieval_status=RetrievalStatus.TIMEOUT,
                        extraction_quality=ExtractionQuality.EMPTY,
                        evidence_status=EvidenceStatus.UNUSABLE,
                    )
                    
        except httpx.TimeoutException as e:
            elapsed_ms = (time.monotonic() - start_time) * 1000
            # Determine which phase timed out
            timeout_type = type(e).__name__
            logger.error(
                f"[PAGE_CRAWLER] HTTPX timeout ({timeout_type}) crawling {url}: {e} "
                f"elapsed_ms={elapsed_ms:.0f}"
            )
            return CrawlResult(
                url=url,
                final_url="",
                status_code=0,
                success=False,
                content="",
                content_type="",
                title="",
                error=f"HTTPX timeout ({timeout_type}): {e}",
                metadata=discovery_metadata or {},
                retrieval_status=RetrievalStatus.TIMEOUT,
                extraction_quality=ExtractionQuality.EMPTY,
                evidence_status=EvidenceStatus.UNUSABLE,
            )
            
        except httpx.HTTPStatusError as e:
            elapsed_ms = (time.monotonic() - start_time) * 1000
            status_code = e.response.status_code if e.response else 0
            final_url = str(e.response.url) if e.response else ""
            logger.error(
                f"[PAGE_CRAWLER] HTTP {status_code} crawling {url}: "
                f"final_url={final_url} elapsed_ms={elapsed_ms:.0f}"
            )
            return CrawlResult(
                url=url,
                final_url=final_url,
                status_code=status_code,
                success=False,
                content="",
                content_type="",
                title="",
                error=f"HTTP {status_code}" if status_code else "HTTP error",
                metadata=discovery_metadata or {},
                retrieval_status=RetrievalStatus.HTTP_ERROR,
                extraction_quality=ExtractionQuality.EMPTY,
                evidence_status=EvidenceStatus.UNUSABLE,
            )
            
        except httpx.ConnectError as e:
            elapsed_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                f"[PAGE_CRAWLER] Connection error crawling {url}: {e} "
                f"elapsed_ms={elapsed_ms:.0f}"
            )
            return CrawlResult(
                url=url,
                final_url="",
                status_code=0,
                success=False,
                content="",
                content_type="",
                title="",
                error=f"Connection failed: {e}",
                metadata=discovery_metadata or {},
                retrieval_status=RetrievalStatus.CONNECTION_ERROR,
                extraction_quality=ExtractionQuality.EMPTY,
                evidence_status=EvidenceStatus.UNUSABLE,
            )
            
        except httpx.RequestError as e:
            # Catch other HTTPX request errors (e.g., TooManyRedirects)
            elapsed_ms = (time.monotonic() - start_time) * 1000
            error_type = type(e).__name__
            logger.error(
                f"[PAGE_CRAWLER] Request error ({error_type}) crawling {url}: {e} "
                f"elapsed_ms={elapsed_ms:.0f}"
            )
            
            # Check for redirect loop
            if "redirect" in error_type.lower() or "too many redirects" in str(e).lower():
                retrieval_status = RetrievalStatus.REDIRECT_LOOP
            else:
                retrieval_status = RetrievalStatus.CONNECTION_ERROR
                
            return CrawlResult(
                url=url,
                final_url="",
                status_code=0,
                success=False,
                content="",
                content_type="",
                title="",
                error=f"{error_type}: {e}",
                metadata=discovery_metadata or {},
                retrieval_status=retrieval_status,
                extraction_quality=ExtractionQuality.EMPTY,
                evidence_status=EvidenceStatus.UNUSABLE,
            )
            
        except ValueError as e:
            # URL validation errors, etc.
            elapsed_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                f"[PAGE_CRAWLER] Value error crawling {url}: {e} "
                f"elapsed_ms={elapsed_ms:.0f}"
            )
            # ValueError could be from URL parsing or other validation
            # Classify as HTTP_ERROR to distinguish from connection failures
            return CrawlResult(
                url=url,
                final_url="",
                status_code=0,
                success=False,
                content="",
                content_type="",
                title="",
                error=str(e),
                metadata=discovery_metadata or {},
                retrieval_status=RetrievalStatus.HTTP_ERROR,
                extraction_quality=ExtractionQuality.EMPTY,
                evidence_status=EvidenceStatus.UNUSABLE,
            )
            
        except Exception as e:
            elapsed_ms = (time.monotonic() - start_time) * 1000
            error_type = type(e).__name__
            logger.error(
                f"[PAGE_CRAWLER] Unexpected error ({error_type}) crawling {url}: {e} "
                f"elapsed_ms={elapsed_ms:.0f}"
            )
            # Do NOT classify as connection error - this could be parsing, programming, etc.
            # Use a generic error status but NOT CONNECTION_ERROR
            return CrawlResult(
                url=url,
                final_url="",
                status_code=0,
                success=False,
                content="",
                content_type="",
                title="",
                error=f"{error_type}: {e}",
                metadata=discovery_metadata or {},
                retrieval_status=RetrievalStatus.HTTP_ERROR,  # Generic error for unexpected exceptions
                extraction_quality=ExtractionQuality.EMPTY,
                evidence_status=EvidenceStatus.UNUSABLE,
            )

    async def crawl_urls(
        self,
        urls: List[str],
        discovery_metadata_map: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> List[CrawlResult]:
        """Crawl multiple URLs concurrently with connection reuse.
        
        This method:
        - Creates a single HTTPX client for all URLs to reuse connections
        - Processes URLs in batches to limit concurrency
        - Ensures failures of individual URLs don't stop other crawls
        - Properly cleans up the HTTP client
        
        Args:
            urls: List of URLs to crawl
            discovery_metadata_map: Optional dict mapping URLs to their discovery metadata
            
        Returns:
            List of CrawlResults in the same order as input URLs
        """
        if not urls:
            return []
        
        results = []
        
        # Create a single HTTP client for all URLs to reuse connections
        async with httpx.AsyncClient(
            headers=self.headers,
            timeout=self.timeout_config,
            follow_redirects=True,
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
        ) as shared_client:
            
            # Process in batches to limit concurrency
            for i in range(0, len(urls), self.max_concurrent):
                batch = urls[i:i + self.max_concurrent]
                
                # Get metadata for each URL in batch
                batch_metadata = {}
                if discovery_metadata_map:
                    for url in batch:
                        batch_metadata[url] = discovery_metadata_map.get(url, {})
                
                # Create tasks for this batch
                # Each task uses the shared client
                batch_tasks = []
                for url in batch:
                    metadata = batch_metadata.get(url, {})
                    # Create a task that uses the shared client
                    task = asyncio.create_task(
                        self._crawl_url_with_client(
                            shared_client, url, metadata
                        )
                    )
                    batch_tasks.append(task)
                
                # Wait for batch to complete
                batch_results = await asyncio.gather(
                    *batch_tasks, 
                    return_exceptions=False
                )
                results.extend(batch_results)
        
        return results

    async def _crawl_url_with_client(
        self,
        client: httpx.AsyncClient,
        url: str,
        discovery_metadata: Optional[Dict[str, Any]] = None,
    ) -> CrawlResult:
        """Crawl a single URL using a shared HTTP client.
        
        This is used by crawl_urls() to reuse connections across URLs.
        
        Args:
            client: Shared HTTPX async client
            url: The URL to crawl
            discovery_metadata: Optional metadata about how this URL was discovered
            
        Returns:
            CrawlResult with the page content or failure information
        """
        # Normalize URL first
        normalized_url = normalize_url(url)
        if not normalized_url:
            return CrawlResult(
                url=url,
                final_url="",
                status_code=0,
                success=False,
                content="",
                content_type="",
                title="",
                error="Invalid URL",
                metadata=discovery_metadata or {},
                retrieval_status=RetrievalStatus.CONNECTION_ERROR,
                extraction_quality=ExtractionQuality.EMPTY,
                evidence_status=EvidenceStatus.UNUSABLE,
            )
        
        start_time = time.monotonic()
        
        try:
            # Use overall timeout wrapper
            response, raw_content, bytes_received, was_truncated = await asyncio.wait_for(
                self._fetch_with_streaming(client, normalized_url),
                timeout=self.overall_timeout,
            )
            
            # Get final URL and status from response
            final_url = str(response.url)
            status_code = response.status_code
            content_type = response.headers.get("Content-Type", "").lower()
            
            elapsed_ms = (time.monotonic() - start_time) * 1000
            
            # Check if we should process this content type
            if not self._should_crawl_content_type(content_type):
                logger.info(
                    f"[PAGE_CRAWLER] Rejected content type {content_type} for {url} "
                    f"elapsed_ms={elapsed_ms:.0f}"
                )
                return CrawlResult(
                    url=url,
                    final_url=final_url,
                    status_code=status_code,
                    success=False,
                    content="",
                    content_type=content_type,
                    title="",
                    error=f"Unsupported content type: {content_type}",
                    metadata=discovery_metadata or {},
                    retrieval_status=RetrievalStatus.CONTENT_TYPE_REJECTED,
                    extraction_quality=ExtractionQuality.EMPTY,
                    evidence_status=EvidenceStatus.UNUSABLE,
                )
            
            # Check for non-content URLs (images, etc.)
            if self._is_non_content_url(final_url):
                logger.info(
                    f"[PAGE_CRAWLER] Rejected non-content URL {final_url} "
                    f"elapsed_ms={elapsed_ms:.0f}"
                )
                return CrawlResult(
                    url=url,
                    final_url=final_url,
                    status_code=status_code,
                    success=False,
                    content="",
                    content_type=content_type,
                    title="",
                    error="Non-content URL (image, stylesheet, etc.)",
                    metadata=discovery_metadata or {},
                    retrieval_status=RetrievalStatus.CONTENT_TYPE_REJECTED,
                    extraction_quality=ExtractionQuality.EMPTY,
                    evidence_status=EvidenceStatus.UNUSABLE,
                )
            
            # Check if content was truncated due to size limit
            if was_truncated and not raw_content:
                logger.warning(
                    f"[PAGE_CRAWLER] Content-Length exceeded limit for {url} "
                    f"elapsed_ms={elapsed_ms:.0f}"
                )
                return CrawlResult(
                    url=url,
                    final_url=final_url,
                    status_code=status_code,
                    success=False,
                    content="",
                    content_type=content_type,
                    title="",
                    error=f"Content too large: Content-Length exceeds {self.max_content_length} bytes",
                    metadata=discovery_metadata or {},
                    retrieval_status=RetrievalStatus.CONTENT_TYPE_REJECTED,
                    extraction_quality=ExtractionQuality.EMPTY,
                    evidence_status=EvidenceStatus.UNUSABLE,
                )
            
            # Check if we have any content at all
            if not raw_content:
                logger.warning(
                    f"[PAGE_CRAWLER] Empty content received for {url} "
                    f"status={status_code} elapsed_ms={elapsed_ms:.0f}"
                )
                return CrawlResult(
                    url=url,
                    final_url=final_url,
                    status_code=status_code,
                    success=False,
                    content="",
                    content_type=content_type,
                    title="",
                    error="Empty response body",
                    metadata=discovery_metadata or {},
                    retrieval_status=RetrievalStatus.HTTP_ERROR,
                    extraction_quality=ExtractionQuality.EMPTY,
                    evidence_status=EvidenceStatus.UNUSABLE,
                )
            
            # Extract title and content
            title, content, html_content = self._extract_content(
                raw_content, content_type, final_url
            )
            
            # Classify extraction quality
            extraction_quality = classify_extraction_quality(
                content, 
                html_content if html_content else raw_content,
                final_url,
                status_code
            )
            
            # For HTTP success (2xx), mark as success
            retrieval_status = RetrievalStatus.SUCCESS
            
            # Classify evidence status
            evidence_status = classify_evidence_status(
                extraction_quality,
                retrieval_status
            )
            
            # Log size limit truncation if it happened
            if was_truncated:
                logger.info(
                    f"[PAGE_CRAWLER] Content truncated to {self.max_content_length} bytes for {url} "
                    f"elapsed_ms={elapsed_ms:.0f}"
                )
                metadata = (discovery_metadata or {}).copy()
                metadata["content_truncated"] = True
                metadata["bytes_received"] = bytes_received
                metadata["max_content_length"] = self.max_content_length
                
                return CrawlResult(
                    url=url,
                    final_url=final_url,
                    status_code=status_code,
                    success=True,
                    content=content,
                    content_type=content_type,
                    title=title,
                    metadata=metadata,
                    retrieval_status=retrieval_status,
                    extraction_quality=extraction_quality,
                    evidence_status=evidence_status,
                )
            
            return CrawlResult(
                url=url,
                final_url=final_url,
                status_code=status_code,
                success=True,
                content=content,
                content_type=content_type,
                title=title,
                metadata=discovery_metadata or {},
                retrieval_status=retrieval_status,
                extraction_quality=extraction_quality,
                evidence_status=evidence_status,
            )
            
        except asyncio.TimeoutError as e:
            elapsed_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                f"[PAGE_CRAWLER] Timeout (overall deadline) crawling {url}: {e} "
                f"elapsed_ms={elapsed_ms:.0f}"
            )
            return CrawlResult(
                url=url,
                final_url="",
                status_code=0,
                success=False,
                content="",
                content_type="",
                title="",
                error=f"Timeout after {self.overall_timeout}s: {e}",
                metadata=discovery_metadata or {},
                retrieval_status=RetrievalStatus.TIMEOUT,
                extraction_quality=ExtractionQuality.EMPTY,
                evidence_status=EvidenceStatus.UNUSABLE,
            )
            
        except httpx.TimeoutException as e:
            elapsed_ms = (time.monotonic() - start_time) * 1000
            timeout_type = type(e).__name__
            logger.error(
                f"[PAGE_CRAWLER] HTTPX timeout ({timeout_type}) crawling {url}: {e} "
                f"elapsed_ms={elapsed_ms:.0f}"
            )
            return CrawlResult(
                url=url,
                final_url="",
                status_code=0,
                success=False,
                content="",
                content_type="",
                title="",
                error=f"HTTPX timeout ({timeout_type}): {e}",
                metadata=discovery_metadata or {},
                retrieval_status=RetrievalStatus.TIMEOUT,
                extraction_quality=ExtractionQuality.EMPTY,
                evidence_status=EvidenceStatus.UNUSABLE,
            )
            
        except httpx.HTTPStatusError as e:
            elapsed_ms = (time.monotonic() - start_time) * 1000
            status_code = e.response.status_code if e.response else 0
            final_url = str(e.response.url) if e.response else ""
            logger.error(
                f"[PAGE_CRAWLER] HTTP {status_code} crawling {url}: "
                f"final_url={final_url} elapsed_ms={elapsed_ms:.0f}"
            )
            return CrawlResult(
                url=url,
                final_url=final_url,
                status_code=status_code,
                success=False,
                content="",
                content_type="",
                title="",
                error=f"HTTP {status_code}" if status_code else "HTTP error",
                metadata=discovery_metadata or {},
                retrieval_status=RetrievalStatus.HTTP_ERROR,
                extraction_quality=ExtractionQuality.EMPTY,
                evidence_status=EvidenceStatus.UNUSABLE,
            )
            
        except httpx.ConnectError as e:
            elapsed_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                f"[PAGE_CRAWLER] Connection error crawling {url}: {e} "
                f"elapsed_ms={elapsed_ms:.0f}"
            )
            return CrawlResult(
                url=url,
                final_url="",
                status_code=0,
                success=False,
                content="",
                content_type="",
                title="",
                error=f"Connection failed: {e}",
                metadata=discovery_metadata or {},
                retrieval_status=RetrievalStatus.CONNECTION_ERROR,
                extraction_quality=ExtractionQuality.EMPTY,
                evidence_status=EvidenceStatus.UNUSABLE,
            )
            
        except httpx.RequestError as e:
            elapsed_ms = (time.monotonic() - start_time) * 1000
            error_type = type(e).__name__
            logger.error(
                f"[PAGE_CRAWLER] Request error ({error_type}) crawling {url}: {e} "
                f"elapsed_ms={elapsed_ms:.0f}"
            )
            
            if "redirect" in error_type.lower() or "too many redirects" in str(e).lower():
                retrieval_status = RetrievalStatus.REDIRECT_LOOP
            else:
                retrieval_status = RetrievalStatus.CONNECTION_ERROR
                
            return CrawlResult(
                url=url,
                final_url="",
                status_code=0,
                success=False,
                content="",
                content_type="",
                title="",
                error=f"{error_type}: {e}",
                metadata=discovery_metadata or {},
                retrieval_status=retrieval_status,
                extraction_quality=ExtractionQuality.EMPTY,
                evidence_status=EvidenceStatus.UNUSABLE,
            )
            
        except Exception as e:
            elapsed_ms = (time.monotonic() - start_time) * 1000
            error_type = type(e).__name__
            logger.error(
                f"[PAGE_CRAWLER] Unexpected error ({error_type}) crawling {url}: {e} "
                f"elapsed_ms={elapsed_ms:.0f}"
            )
            # Do NOT classify as connection error
            return CrawlResult(
                url=url,
                final_url="",
                status_code=0,
                success=False,
                content="",
                content_type="",
                title="",
                error=f"{error_type}: {e}",
                metadata=discovery_metadata or {},
                retrieval_status=RetrievalStatus.HTTP_ERROR,
                extraction_quality=ExtractionQuality.EMPTY,
                evidence_status=EvidenceStatus.UNUSABLE,
            )

    def _should_crawl_content_type(self, content_type: str) -> bool:
        """Check if we should attempt to crawl this content type."""
        if not content_type:
            return True  # Assume text if no content type
        
        # Definitely crawl HTML and text
        if "text/html" in content_type:
            return True
        if "text/plain" in content_type:
            return True
        if "application/json" in content_type:
            return True  # JSON can contain useful data
        if "application/xml" in content_type:
            return True
        
        # PDF and other documents - for now, skip (can be added later)
        if "application/pdf" in content_type:
            return False
        if "application/msword" in content_type or "application/vnd" in content_type:
            return False
        
        # Skip binary content
        if "image/" in content_type:
            return False
        if "audio/" in content_type:
            return False
        if "video/" in content_type:
            return False
        
        # Skip archives
        if "application/zip" in content_type or "application/x-" in content_type:
            return False
        
        return True

    def _is_non_content_url(self, url: str) -> bool:
        """Check if URL points to non-content resource."""
        parsed = urlparse(url)
        path = parsed.path.lower()
        
        for ext in _NON_CONTENT_EXTENSIONS:
            if path.endswith(ext):
                return True
        
        return False

    def _extract_content(
        self,
        html: str,
        content_type: str,
        url: str,
    ) -> tuple[str, str, str]:
        """Extract title and main content from HTML.
        
        Returns:
            (title, content_text, html_content)
        """
        if "text/html" not in content_type:
            # For non-HTML, return as-is
            return url, html, html
        
        try:
            soup = BeautifulSoup(html, "html.parser")
            
            # Extract title BEFORE removing head
            title = soup.title.string if soup.title else url
            
            # Remove unwanted elements
            for element in soup(["script", "style", "nav", "footer", "iframe", "svg", "noscript", "form", "input", "button", "select", "textarea"]):
                element.decompose()
            
            # Remove head separately to preserve title extraction
            head = soup.find("head")
            if head:
                head.decompose()
            
            # Try to find main content
            content = self._extract_main_content(soup)
            
            if not content:
                # Fallback to body text
                body = soup.find("body")
                if body:
                    content = body.get_text().strip()
            
            if not content:
                # Last resort: extract text from entire HTML
                content = soup.get_text().strip()
                if not content:
                    content = html[:1000]  # Absolute last resort
            
            # Clean the extracted content
            content = clean_text(content)
            
            return str(title).strip(), content.strip(), html
            
        except Exception as e:
            logger.error(f"[PAGE_CRAWLER] Failed to parse HTML from {url}: {e}")
            # Even in fallback, clean the HTML
            fallback_content = clean_text(html[:1000])
            return url, fallback_content, html  # Return cleaned fallback content

    def _extract_main_content(self, soup: Any) -> str:
        """Extract main content from BeautifulSoup object.
        
        This method extracts the main content from HTML pages while removing
        navigation artifacts, especially from Wikipedia pages and modern site
        builders like Wix, Squarespace, etc.
        """
        # First, remove Wikipedia-specific navigation and metadata elements
        self._remove_wikipedia_artifacts(soup)
        
        # Try to find main content section BEFORE removing site builder artifacts
        # This is important for Wix/Squarespace sites where the main content
        # is inside elements with wix classes
        main_selectors = [
            "main",
            "article",
            ".main-content",
            ".content",
            ".container",
            ".wrapper",
            "[role=main]",
            "#mw-content-text",  # Wikipedia main content
            ".mw-parser-output",  # Wikipedia content
            # Wix-specific selectors
            "#SITE_CONTAINER",
            ".WIX_ADS",
            "#COMPONENT_CONTAINER",
            # Common content selectors
            ".post-content",
            ".entry-content",
            ".page-content",
            ".site-content",
            ".main-article",
            ".article-body",
            ".content-wrapper",
            ".content-main",
        ]
        
        for selector in main_selectors:
            main = soup.select_one(selector)
            if main:
                text = main.get_text().strip()
                if len(text) > 100:  # Only return if substantial
                    return clean_text(text)
        
        # Remove site builder artifacts (Wix, Squarespace, etc.)
        self._remove_site_builder_artifacts(soup)
        
        # Try again after removing site builder artifacts
        for selector in main_selectors:
            main = soup.select_one(selector)
            if main:
                text = main.get_text().strip()
                if len(text) > 100:  # Only return if substantial
                    return clean_text(text)
        
        # Try to find paragraph tags
        paragraphs = soup.find_all("p")
        if paragraphs:
            text = "\n\n".join(p.get_text().strip() for p in paragraphs[:50])
            if len(text) > 100:
                return clean_text(text)
        
        # Try headings and their following content
        headings = soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])
        if headings:
            parts = []
            for heading in headings[:20]:
                parts.append(heading.get_text().strip())
                # Get next sibling text
                next_node = heading.next_sibling
                while next_node and next_node.name not in ["h1", "h2", "h3", "h4", "h5", "h6"]:
                    if next_node.name == "p":
                        parts.append(next_node.get_text().strip())
                        break
                    next_node = next_node.next_sibling
            if parts:
                return clean_text("\n\n".join(parts))
        
        return ""
    
    def _remove_wikipedia_artifacts(self, soup: Any) -> None:
        """Remove Wikipedia-specific navigation and metadata artifacts from HTML.
        
        This removes elements like:
        - "49 languages" links
        - "Edit links" navigation
        - "From Wikipedia" text
        - Sidebars, navigation boxes, and other non-content elements
        """
        # Remove Wikipedia language links (the "49 languages" sidebar)
        # Look for elements with class "interlanguage-link" or in the language sidebar
        for element in soup.find_all(class_=lambda x: x and ("interlanguage" in x or "language" in x.lower())):
            element.decompose()
        
        # Remove edit links (usually have class "mw-editsection")
        for element in soup.find_all(class_=lambda x: x and ("editsection" in x or "edit-link" in x.lower())):
            element.decompose()
        
        # Remove edit section links (text like "[edit]")
        for element in soup.find_all(string=lambda text: text and "[edit]" in text.lower()):
            if element.parent:
                element.parent.decompose()
        
        # Remove "From Wikipedia" text
        for element in soup.find_all(string=lambda text: text and "from wikipedia" in text.lower()):
            element.replace_with("")
        
        # Remove Wikipedia navigation boxes
        for element in soup.find_all(class_=lambda x: x and ("navbox" in x.lower() or "navbar" in x.lower() or "infobox" in x.lower())):
            element.decompose()
        
        # Remove Wikipedia sidebar
        for element in soup.find_all(id=lambda x: x and "mw-panel" in x):
            element.decompose()
        
        # Remove Wikipedia footer elements
        for element in soup.find_all(class_=lambda x: x and ("printfooter" in x.lower() or "catlinks" in x.lower() or "metadata" in x.lower())):
            element.decompose()
        
        # Remove Wikipedia "This page was last edited" text
        for element in soup.find_all(string=lambda text: text and ("this page was last edited" in text.lower() or "last edited on" in text.lower())):
            if element.parent:
                # Remove the parent container if it's a div or span
                if element.parent.name in ["div", "span", "p"]:
                    element.parent.decompose()
        
        # Remove Wikipedia "Available in X languages" text
        for element in soup.find_all(string=lambda text: text and ("available in" in text.lower() and "language" in text.lower() and "49" in text)):
            if element.parent:
                element.parent.decompose()
        
        # Remove any remaining elements with "49 languages" text
        for element in soup.find_all(string=lambda text: text and "49 languages" in text.lower()):
            if element.parent:
                element.parent.decompose()

    def _remove_site_builder_artifacts(self, soup: Any) -> None:
        """Remove artifacts from site builders like Wix, Squarespace, etc.
        
        This removes elements commonly found in site-builder generated pages
        that contain boilerplate, navigation, or non-content elements.
        """
        # Remove Wix-specific elements (but NOT data-testid elements which may contain content)
        for element in soup.find_all(class_=lambda x: x and ("wix" in x.lower() or "WIX" in x)):
            element.decompose()
        
        # Remove Squarespace-specific elements
        for element in soup.find_all(class_=lambda x: x and ("sqs" in x.lower() or "squarespace" in x.lower())):
            element.decompose()
        
        # Remove generic site builder header/footer elements
        for element in soup.find_all(class_=lambda x: x and ("header" in x.lower() or "footer" in x.lower() or "navbar" in x.lower() or "navigation" in x.lower())):
            element.decompose()
        
        # Remove social media and sharing widgets
        for element in soup.find_all(class_=lambda x: x and ("social" in x.lower() or "share" in x.lower() or "widget" in x.lower())):
            element.decompose()
        
        # Remove cookie banners and consent forms
        for element in soup.find_all(class_=lambda x: x and ("cookie" in x.lower() or "consent" in x.lower() or "privacy" in x.lower() or "gdpr" in x.lower())):
            element.decompose()
        
        # Remove modal and overlay elements
        for element in soup.find_all(class_=lambda x: x and ("modal" in x.lower() or "overlay" in x.lower() or "popup" in x.lower() or "dialog" in x.lower())):
            element.decompose()
        
        # Remove advertisement elements
        for element in soup.find_all(class_=lambda x: x and ("ad" in x.lower() or "advert" in x.lower() or "banner" in x.lower() or "sponsored" in x.lower())):
            element.decompose()


def normalize_url(url: str) -> str:
    """Normalize URL for deduplication.
    
    Handles:
    - Trailing slashes
    - URL fragments
    - Common tracking parameters
    - Case normalization
    - Equivalent canonical URLs
    """
    if not url or not isinstance(url, str):
        return ""
    
    url = url.strip()
    if not url:
        return ""
    
    try:
        parsed = urlparse(url)
    except ValueError:
        return url
    
    # Handle missing scheme (add https if no scheme)
    if not parsed.scheme:
        url = f"https://{url}"
        parsed = urlparse(url)
    
    # Normalize scheme and netloc to lowercase
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    
    # Remove default ports (80 for http, 443 for https)
    if ':' in netloc:
        host, port = netloc.rsplit(':', 1)
        if (scheme == 'http' and port == '80') or (scheme == 'https' and port == '443'):
            netloc = host
    
    # Only handle http/https
    if scheme not in ("http", "https"):
        return url
    
    # Normalize path (remove duplicate slashes, trailing slash)
    path = parsed.path
    if path and path != "/":
        # Remove duplicate slashes
        path = re.sub(r'/+', '/', path)
        # Remove trailing slash (except for root)
        if len(path) > 1 and path.endswith('/'):
            path = path.rstrip('/')
        # Normalize to lowercase for consistency
        path = path.lower()
    
    # Remove URL fragment
    fragment = ""
    
    # Remove tracking parameters from query string
    query = parsed.query
    if query:
        query_parts = []
        for param in query.split('&'):
            if '=' in param:
                key, _, _ = param.partition('=')
                if key.lower() not in _TRACKING_PARAMS:
                    query_parts.append(param)
            else:
                query_parts.append(param)
        query = '&'.join(query_parts)
    
    # Rebuild URL
    normalized = urlunparse((
        scheme,
        netloc,
        path,
        '',  # params
        query,
        fragment,
    ))
    
    return normalized


def clean_text(text: str) -> str:
    """Clean extracted text for research use."""
    if not text:
        return ""
    
    # Remove excessive whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    
    # Remove non-printable characters (except spaces and newlines)
    text = ''.join(
        char for char in text 
        if char.isprintable() or char in ('\n', '\r', '\t')
    )
    
    # Collapse multiple newlines
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    return text.strip()


def deduplicate_urls(urls: List[str]) -> List[str]:
    """Deduplicate URLs using normalization.
    
    Returns URLs in original order, but with duplicates removed.
    """
    seen: Set[str] = set()
    unique_urls: List[str] = []
    
    for url in urls:
        normalized = normalize_url(url)
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique_urls.append(url)
    
    return unique_urls
