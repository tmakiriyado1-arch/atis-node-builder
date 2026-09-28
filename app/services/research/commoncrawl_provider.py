"""Common Crawl provider for deep web archive fallback.

This provider queries the Common Crawl index to find archived web pages
when other search providers fail. It provides access to historical web content
without relying on live search engines.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlparse

import httpx
from bs4 import BeautifulSoup

from app.services.research.search_provider import ProviderRole, SearchProvider, SearchResult
from app.logging import logger


class CommonCrawlProvider(SearchProvider):
    """Search provider for Common Crawl web archive.
    
    Uses the Common Crawl CDXJ index API to find archived pages.
    This is the deep fallback when all other providers fail.
    """

    role = ProviderRole.DEEP_ARCHIVE

    def __init__(
        self,
        index_url: str = "https://index.commoncrawl.org",
        timeout: float = 15.0,
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
        
        # Convert to SearchResult format
        search_results = []
        for idx, result in enumerate(unique_results[:max_results]):
            search_result = SearchResult(
                provider=self.__class__.__name__,
                query=cleaned_query,
                page=1,
                rank=idx + 1,
                title=result.get("title", ""),
                url=result.get("url", ""),
                snippet=result.get("snippet", None),
                metadata={"source": "common_crawl"},
            )
            search_results.append(search_result)
        
        return search_results

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
            
            # Try multiple crawl indexes if the first one fails
            # Use async version to properly discover available indexes
            latest_crawl = await self._get_latest_crawl_async()
            crawl_indexes = [latest_crawl]
            
            for crawl_index in crawl_indexes:
                params = {
                    "url": search_url,
                    "output": "json",
                    "limit": str(min(max_results, 50)),
                }
                
                # Try with this crawl index
                index_url = f"https://index.commoncrawl.org/{crawl_index}"
                
                async with httpx.AsyncClient(headers=self.headers, timeout=self.timeout) as client:
                    response = await client.get(index_url, params=params)
                    
                    # If we get a 404 or 400, this crawl index doesn't exist, try next
                    if response.status_code in (404, 400, 500, 502, 503):
                        logger.error(f"[COMMONCRAWL] Crawl index {crawl_index} not available, trying next")
                        continue
                    
                    response.raise_for_status()
                    
                    # Handle empty or invalid JSON response
                    try:
                        data = response.json()
                    except Exception:
                        continue
                    
                    if not isinstance(data, list):
                        continue
                    
                    results = []
                    for item in data[:max_results]:
                        result = self._format_cc_result(item)
                        if result:
                            results.append(result)
                    
                    if results:
                        return results
            
            return []
                
        except Exception as e:
            logger.error(f"[COMMONCRAWL] URL search failed for '{url}': {e}")
            return []

    async def _search_by_text(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        """Search Common Crawl by text content (using full-text search)."""
        try:
            # Get the latest crawl identifier
            latest_crawl = self._get_latest_crawl()
            
            # Build the text index URL correctly
            # The URL should be: https://index.commoncrawl.org/{crawl_id}-text-index
            # where crawl_id is like "CC-MAIN-2026-40"
            # The text index suffix is "-text-index", not part of the crawl_id
            search_url = f"https://index.commoncrawl.org/{latest_crawl}-text-index"
            
            logger.info(f"[COMMONCRAWL] Text search URL: {search_url}")
            
            params = {
                "q": query,
                "output": "json",
                "limit": str(min(max_results, 50)),
            }
            
            async with httpx.AsyncClient(headers=self.headers, timeout=self.timeout) as client:
                response = await client.get(search_url, params=params)
                
                # Handle redirects properly
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("location", "")
                    logger.info(f"[COMMONCRAWL] Redirect response '{response.status_code} Redirect' for url: {search_url}")
                    logger.info(f"[COMMONCRAWL] Redirect location: {location}")
                    # Follow the redirect by making a new request to the location
                    # But only if it's a valid Common Crawl URL
                    if location and location.startswith("https://index.commoncrawl.org/"):
                        redirect_response = await client.get(location, params=params)
                        response = redirect_response
                    else:
                        logger.error(f"[COMMONCRAWL] Redirect to non-CC URL: {location}, skipping")
                        return []
                
                response.raise_for_status()
                
                # Handle empty or invalid JSON response
                try:
                    data = response.json()
                except Exception:
                    return []
                
                if not isinstance(data, list):
                    return []
                
                results = []
                for item in data[:max_results]:
                    result = self._format_cc_result(item)
                    if result:
                        results.append(result)
                
                return results
                
        except Exception as e:
            logger.error(f"[COMMONCRAWL] Text search failed for '{query}': {e}")
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
            logger.error(f"[COMMONCRAWL] Failed to format result: {e}")
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

    async def _get_available_crawl_indexes(self) -> List[str]:
        """Get list of available Common Crawl index identifiers.
        
        Attempts to discover actually available indexes by checking the CDXJ API.
        Returns list of available indexes sorted by recency (newest first).
        """
        import datetime
        
        # Try to get list of available crawls from Common Crawl
        # The index is at https://index.commoncrawl.org/ and lists available crawls
        try:
            async with httpx.AsyncClient(headers=self.headers, timeout=self.timeout) as client:
                # Try to fetch the main index page which lists available crawls
                response = await client.get("https://index.commoncrawl.org/", timeout=10.0)
                response.raise_for_status()
                
                # Parse the HTML to find available crawl links
                html = response.text
                soup = BeautifulSoup(html, "html.parser")
                
                # Look for links that match crawl index pattern (CC-MAIN-YYYY-WW)
                crawl_pattern = re.compile(r'CC-MAIN-(\d{4})-(\d{1,2})')
                available_crawls = []
                
                for a in soup.find_all("a", href=True):
                    href = a["href"].strip()
                    match = crawl_pattern.search(href)
                    if match:
                        # Extract the crawl identifier
                        crawl_id = match.group(0)
                        if crawl_id not in available_crawls:
                            available_crawls.append(crawl_id)
                
                # Sort by year and week (newest first)
                def sort_key(crawl_id: str) -> tuple:
                    # Extract year and week from CC-MAIN-YYYY-WW
                    match = crawl_pattern.search(crawl_id)
                    if match:
                        year = int(match.group(1))
                        week = int(match.group(2))
                        return (year, week)
                    return (0, 0)
                
                available_crawls.sort(key=sort_key, reverse=True)
                
                if available_crawls:
                    logger.info(f"[COMMONCRAWL] Found {len(available_crawls)} available crawls: {available_crawls[:5]}")
                    return available_crawls
                
        except Exception as e:
            logger.error(f"[COMMONCRAWL] Failed to discover available crawls: {e}")
        
        # Fallback: try a few recent crawls
        # Start from current date and go backwards
        now = datetime.datetime.now()
        fallback_crawls = []
        
        for weeks_back in range(0, 10):  # Try up to 10 weeks back
            test_date = now - datetime.timedelta(weeks=weeks_back)
            year = test_date.year
            week = test_date.isocalendar()[1]
            crawl_id = f"{year}-{week:02d}"
            fallback_crawls.append(f"CC-MAIN-{crawl_id}")
        
        logger.info(f"[COMMONCRAWL] Using fallback crawls: {fallback_crawls[:3]}")
        return fallback_crawls
    
    async def _get_latest_crawl_async(self) -> str:
        """Get the latest Common Crawl index identifier asynchronously.
        
        This method tries to discover available crawls by checking the CDXJ API.
        If discovery fails, it falls back to trying recent crawls.
        """
        import datetime
        
        # Try to discover available crawls
        available = await self._get_available_crawl_indexes()
        if available:
            return available[0]  # Return the newest
        
        # Fallback: try recent crawls
        now = datetime.datetime.now()
        year = now.year
        week = now.isocalendar()[1]
        
        # Try this week and previous weeks
        for weeks_back in range(0, 10):
            test_week = week - weeks_back
            if test_week < 1:
                # Wrap to previous year
                year -= 1
                test_week = 52  # Last week of previous year
            crawl_id = f"CC-MAIN-{year}-{test_week:02d}"
            
            # Try to verify this index exists
            try:
                async with httpx.AsyncClient(headers=self.headers, timeout=5.0) as client:
                    # Try a simple query to see if the index exists
                    test_url = f"https://index.commoncrawl.org/{crawl_id}"
                    response = await client.get(test_url, params={"url": "example.com", "output": "json", "limit": "1"})
                    
                    # If we get a valid response (not 404/400), this index exists
                    if response.status_code not in (404, 400, 500, 502, 503):
                        logger.info(f"[COMMONCRAWL] Verified available crawl index: {crawl_id}")
                        return crawl_id
            except Exception:
                continue
        
        # Ultimate fallback - return the most recent format
        return f"CC-MAIN-{year}-{week:02d}"
    
    def _get_latest_crawl(self) -> str:
        """Get the latest Common Crawl index identifier.
        
        Synchronous version for backward compatibility.
        Returns a reasonable guess based on current date.
        """
        import datetime
        
        now = datetime.datetime.now()
        year = now.year
        week = now.isocalendar()[1]
        
        # Try this week and previous weeks
        for weeks_back in range(0, 5):
            test_week = week - weeks_back
            if test_week < 1:
                # Wrap to previous year
                year -= 1
                test_week = 52  # Last week of previous year
            crawl_id = f"CC-MAIN-{year}-{test_week:02d}"
            return crawl_id
        
        return f"CC-MAIN-{year}-{week:02d}"
