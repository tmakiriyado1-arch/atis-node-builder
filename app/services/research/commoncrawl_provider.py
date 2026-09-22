"""Common Crawl provider for deep web archive fallback.

This provider queries the Common Crawl index to find archived web pages
when other search providers fail. It provides access to historical web content
without relying on live search engines.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urljoin

import httpx

from app.services.research.search_provider import SearchProvider
from app.logging import logger


class CommonCrawlProvider(SearchProvider):
    """Search provider for Common Crawl web archive.
    
    Uses the Common Crawl CDXJ index API to find archived pages.
    This is the deep fallback when all other providers fail.
    """

    def __init__(
        self,
        index_url: str = "https://index.commoncrawl.org",
        timeout: float = 30.0,
        user_agent: str = "NORAResearchBot/1.0 (+https://github.com/tmakiriyado1-arch/atis-node-builder)",
        max_results: int = 10,
    ) -> None:
        self.index_url = index_url
        self.timeout = timeout
        self.headers = {"User-Agent": user_agent, "Accept": "application/json"}
        self.max_results = max_results

    async def search(
        self,
        query: str,
        max_results: int = 10,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Search Common Crawl for archived pages matching the query.
        
        Args:
            query: The search query (entity name or URL pattern)
            max_results: Maximum number of results to return
            context: Optional context for query expansion
            
        Returns:
            List of result dictionaries with title, url, snippet
        """
        cleaned_query = (query or "").strip()
        if not cleaned_query:
            return []

        logger.info(f"[COMMONCRAWL] Searching for '{cleaned_query[:100]}'")
        
        # Try multiple approaches
        results = []
        
        # 1. Try URL-based search (if query looks like a domain)
        url_results = await self._search_by_url(cleaned_query, max_results)
        results.extend(url_results)
        
        # 2. Try text-based search
        if len(results) < max_results:
            text_results = await self._search_by_text(cleaned_query, max_results - len(results))
            results.extend(text_results)
        
        # 3. Try with extracted domain
        if len(results) < max_results:
            domain = self._extract_domain(cleaned_query)
            if domain:
                domain_results = await self._search_by_url(domain, max_results - len(results))
                results.extend(domain_results)
        
        # Deduplicate by URL
        seen_urls = set()
        unique_results = []
        for result in results:
            url = result.get("url", "")
            if url not in seen_urls:
                seen_urls.add(url)
                unique_results.append(result)
        
        logger.info(f"[COMMONCRAWL] Found {len(unique_results)} results")
        return unique_results[:max_results]

    async def _search_by_url(self, url: str, max_results: int) -> List[Dict[str, Any]]:
        """Search Common Crawl by URL pattern."""
        try:
            # Normalize URL for CC search
            search_url = self._normalize_for_cc(url)
            if not search_url:
                return []
            
            # Use CDXJ API to find captures
            params = {
                "url": search_url,
                "output": "json",
                "limit": str(min(max_results, 50)),
            }
            
            async with httpx.AsyncClient(headers=self.headers, timeout=self.timeout) as client:
                response = await client.get(self.index_url, params=params)
                response.raise_for_status()
                
                data = response.json()
                if not isinstance(data, list):
                    return []
                
                results = []
                for item in data[:max_results]:
                    result = self._format_cc_result(item)
                    if result:
                        results.append(result)
                
                return results
                
        except Exception as e:
            logger.warning(f"[COMMONCRAWL] URL search failed for '{url}': {e}")
            return []

    async def _search_by_text(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        """Search Common Crawl by text content (using full-text search)."""
        try:
            # This uses the CC full-text search endpoint
            # Note: This may not always be available, so we fall back
            search_url = f"https://index.commoncrawl.org/CC-MAIN-{self._get_latest_crawl()}-text-index"
            
            params = {
                "q": query,
                "output": "json",
                "limit": str(min(max_results, 50)),
            }
            
            async with httpx.AsyncClient(headers=self.headers, timeout=self.timeout) as client:
                response = await client.get(search_url, params=params)
                response.raise_for_status()
                
                data = response.json()
                if not isinstance(data, list):
                    return []
                
                results = []
                for item in data[:max_results]:
                    result = self._format_cc_result(item)
                    if result:
                        results.append(result)
                
                return results
                
        except Exception as e:
            logger.warning(f"[COMMONCRAWL] Text search failed for '{query}': {e}")
            return []

    def _format_cc_result(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Format a Common Crawl result into standard format."""
        try:
            url = item.get("url", "")
            if not url:
                return None
            
            # Extract timestamp
            timestamp = item.get("timestamp", "")
            
            # Extract fetch time
            fetch_time = item.get("fetchTime", "")
            
            # Build snippet from available info
            snippet_parts = []
            if timestamp:
                snippet_parts.append(f"Captured: {timestamp}")
            if fetch_time:
                snippet_parts.append(f"Fetched: {fetch_time}")
            
            # Try to get page title from URL
            title = self._extract_title_from_url(url)
            
            return {
                "title": title or url,
                "url": url,
                "snippet": " | ".join(snippet_parts) if snippet_parts else "Archived page from Common Crawl",
                "source": "common_crawl",
            }
            
        except Exception as e:
            logger.warning(f"[COMMONCRAWL] Failed to format result: {e}")
            return None

    def _normalize_for_cc(self, url: str) -> str:
        """Normalize URL for Common Crawl search."""
        url = url.strip()
        
        # Remove protocol
        if url.startswith("https://"):
            url = url[8:]
        elif url.startswith("http://"):
            url = url[7:]
        
        # Remove www. prefix
        if url.startswith("www."):
            url = url[4:]
        
        # Remove path and query
        url = url.split("/")[0]
        url = url.split("?")[0]
        url = url.split("#")[0]
        
        # Remove port
        url = url.split(":")[0]
        
        return url.strip()

    def _extract_domain(self, query: str) -> Optional[str]:
        """Extract domain from query."""
        # Try to find a domain pattern
        import re
        
        # Look for patterns like "sapp.co.zw" or "sapp.org"
        match = re.search(r'(?:https?://)?(?:www\.)?([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', query)
        if match:
            return match.group(1)
        
        return None

    def _extract_title_from_url(self, url: str) -> str:
        """Extract a reasonable title from a URL."""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            path = parsed.path.strip("/")
            
            if path:
                # Use the last part of the path as title
                parts = path.split("/")
                if parts:
                    title = parts[-1].replace("-", " ").replace("_", " ")
                    # Capitalize
                    title = title.title()
                    return title[:200]
            
            # Use domain
            domain = parsed.netloc
            if domain.startswith("www."):
                domain = domain[4:]
            return domain.replace(".", " ").title()
            
        except Exception:
            return ""

    def _get_latest_crawl(self) -> str:
        """Get the latest Common Crawl index identifier."""
        # This is a simplified version - in production you'd want to
        # query the available crawls or use a known latest one
        # Format is typically like "2024-51" (year-week)
        import datetime
        now = datetime.datetime.now()
        year = now.year
        week = now.isocalendar()[1]
        return f"{year}-{week:02d}"
