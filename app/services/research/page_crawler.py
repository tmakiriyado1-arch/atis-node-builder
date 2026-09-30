"""Page crawler for acquiring full content from discovered URLs.

This module provides functionality to crawl web pages and extract their content
for use as research evidence. It handles HTML pages and can be extended to support
other content types (PDF, documents, etc.).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urljoin, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup

from app.logging import logger
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
    """

    def __init__(
        self,
        timeout: float = 15.0,
        max_content_length: int = 100000,  # 100KB max per page
        user_agent: str = "Mozilla/5.0 (compatible; NORAResearchBot/1.0; +https://github.com/tmakiriyado1-arch/atis-node-builder)",
        max_concurrent: int = 5,
    ) -> None:
        self.timeout = timeout
        self.max_content_length = max_content_length
        self.user_agent = user_agent
        self.max_concurrent = max_concurrent
        self.headers = {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }

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
        
        try:
            async with httpx.AsyncClient(
                headers=self.headers,
                timeout=self.timeout,
                follow_redirects=True,
                limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
            ) as client:
                response = await client.get(normalized_url)
                
                # Get final URL after redirects
                final_url = str(response.url)
                status_code = response.status_code
                content_type = response.headers.get("Content-Type", "").lower()
                
                # Check if we should process this content type
                if not self._should_crawl_content_type(content_type):
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
                    )
                
                # Check for non-content URLs (images, etc.)
                if self._is_non_content_url(final_url):
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
                
                # Get raw content
                raw_content = response.text
                
                # Limit content size
                if len(raw_content) > self.max_content_length:
                    raw_content = raw_content[:self.max_content_length]
                
                # Extract title and content
                title, content, html_content = self._extract_content(raw_content, content_type, final_url)
                
                # Classify extraction quality
                extraction_quality = classify_extraction_quality(
                    content, 
                    html_content if html_content else raw_content,
                    final_url,
                    status_code
                )
                
                # Classify evidence status
                evidence_status = classify_evidence_status(
                    extraction_quality,
                    RetrievalStatus.SUCCESS
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
                    retrieval_status=RetrievalStatus.SUCCESS,
                    extraction_quality=extraction_quality,
                    evidence_status=evidence_status,
                )
                
        except httpx.TimeoutException as e:
            logger.error(f"[PAGE_CRAWLER] Timeout crawling {url}: {e}")
            return CrawlResult(
                url=url,
                final_url="",
                status_code=0,
                success=False,
                content="",
                content_type="",
                title="",
                error=f"Timeout: {e}",
                metadata=discovery_metadata or {},
                retrieval_status=RetrievalStatus.TIMEOUT,
                extraction_quality=ExtractionQuality.EMPTY,
                evidence_status=EvidenceStatus.UNUSABLE,
            )
            
        except httpx.HTTPStatusError as e:
            logger.error(f"[PAGE_CRAWLER] HTTP error crawling {url}: {e.response.status_code}")
            status_code = e.response.status_code if e.response else 0
            return CrawlResult(
                url=url,
                final_url=str(e.response.url) if e.response else "",
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
            logger.error(f"[PAGE_CRAWLER] Connection error crawling {url}: {e}")
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
            
        except Exception as e:
            logger.error(f"[PAGE_CRAWLER] Error crawling {url}: {e}")
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
                retrieval_status=RetrievalStatus.CONNECTION_ERROR,
                extraction_quality=ExtractionQuality.EMPTY,
                evidence_status=EvidenceStatus.UNUSABLE,
            )

    async def crawl_urls(
        self,
        urls: List[str],
        discovery_metadata_map: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> List[CrawlResult]:
        """Crawl multiple URLs concurrently.
        
        Args:
            urls: List of URLs to crawl
            discovery_metadata_map: Optional dict mapping URLs to their discovery metadata
            
        Returns:
            List of CrawlResults in the same order as input URLs
        """
        import asyncio
        
        results = []
        
        # Process in batches to limit concurrency
        for i in range(0, len(urls), self.max_concurrent):
            batch = urls[i:i + self.max_concurrent]
            
            # Get metadata for each URL in batch
            batch_metadata = {}
            if discovery_metadata_map:
                for url in batch:
                    batch_metadata[url] = discovery_metadata_map.get(url, {})
            
            # Crawl batch concurrently
            batch_tasks = [
                self.crawl_url(url, batch_metadata.get(url)) 
                for url in batch
            ]
            
            batch_results = await asyncio.gather(*batch_tasks, return_exceptions=False)
            results.extend(batch_results)
        
        return results

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
                content = html[:1000]  # Last resort: first 1000 chars
            
            # Clean the extracted content
            content = clean_text(content)
            
            return str(title).strip(), content.strip(), html
            
        except Exception as e:
            logger.error(f"[PAGE_CRAWLER] Failed to parse HTML from {url}: {e}")
            return url, html[:1000], html  # Return raw content as fallback

    def _extract_main_content(self, soup: Any) -> str:
        """Extract main content from BeautifulSoup object.
        
        This method extracts the main content from HTML pages while removing
        navigation artifacts, especially from Wikipedia pages and modern site
        builders like Wix, Squarespace, etc.
        """
        # First, remove Wikipedia-specific navigation and metadata elements
        self._remove_wikipedia_artifacts(soup)
        
        # Remove site builder artifacts (Wix, Squarespace, etc.)
        self._remove_site_builder_artifacts(soup)
        
        # Try to find main content section
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
        # Remove Wix-specific elements
        for element in soup.find_all(class_=lambda x: x and ("wix" in x.lower() or "WIX" in x)):
            element.decompose()
        
        # Remove Wix data elements
        for element in soup.find_all(attrs={"data-testid": True}):
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
