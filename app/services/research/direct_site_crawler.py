"""Direct site crawler for authoritative entity information.

This provider crawls known official websites to extract information directly,
bypassing search engines entirely.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.services.research.search_provider import SearchProvider
from app.logging import logger


class DirectSiteCrawler(SearchProvider):
    """Crawls official websites directly for entity information.
    
    This provider is used when we already know the official domain of an entity
    (e.g., from Wikidata, Wikipedia, or previous research) and want to extract
    information directly from the source.
    """

    def __init__(
        self,
        timeout: float = 15.0,
        user_agent: str = "Mozilla/5.0 (compatible; NORAResearchBot/1.0; +https://github.com/tmakiriyado1-arch/atis-node-builder)",
        max_pages: int = 5,
        max_depth: int = 1,
        crawl_timeout: float = 10.0,
    ) -> None:
        self.timeout = timeout
        self.crawl_timeout = crawl_timeout
        self.headers = {"User-Agent": user_agent, "Accept": "text/html"}
        self.max_pages = max_pages
        self.max_depth = max_depth

    async def search(
        self,
        query: str,
        max_results: int = 10,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Crawl official sites related to the query.
        
        This provider first discovers official URLs from the query, then crawls them.
        
        Args:
            query: The entity name or known URL
            max_results: Maximum number of results to return
            context: Optional context containing known URLs
            
        Returns:
            List of result dictionaries with title, url, snippet
        """
        # If query is already a URL, crawl it directly
        if self._is_url(query):
            results = await self._crawl_url(query)
            return results[:max_results]
        
        # Otherwise, try to discover official URLs from the query
        official_urls = self._discover_official_urls(query, context)
        
        if not official_urls:
            # Try common URL patterns
            official_urls = self._generate_common_urls(query)
        
        # Crawl all discovered URLs
        all_results = []
        for url in official_urls[:self.max_pages]:
            try:
                results = await self._crawl_url(url)
                all_results.extend(results)
                if len(all_results) >= max_results:
                    break
            except Exception as e:
                logger.warning(f"[DIRECT_CRAWL] Failed to crawl {url}: {e}")
                continue
        
        return all_results[:max_results]

    async def crawl_site(
        self,
        base_url: str,
        max_pages: int = 10,
        max_depth: int = 2,
    ) -> List[Dict[str, Any]]:
        """Crawl a site starting from a base URL.
        
        Args:
            base_url: The base URL to start crawling from
            max_pages: Maximum pages to crawl
            max_depth: Maximum depth to crawl
            
        Returns:
            List of result dictionaries
        """
        visited = set()
        results = []
        queue = [(base_url, 0)]  # (url, depth)
        
        while queue and len(results) < max_pages:
            url, depth = queue.pop(0)
            
            if depth > max_depth:
                continue
            
            if url in visited:
                continue
            visited.add(url)
            
            try:
                page_results = await self._crawl_url(url)
                results.extend(page_results)
                
                if len(results) >= max_pages:
                    break
                
                # Extract links for further crawling
                if depth < max_depth:
                    links = await self._extract_links(url)
                    for link in links:
                        if link not in visited:
                            queue.append((link, depth + 1))
            except Exception as e:
                logger.warning(f"[DIRECT_CRAWL] Failed to crawl {url}: {e}")
                continue
        
        return results[:max_pages]

    async def _crawl_url(self, url: str) -> List[Dict[str, Any]]:
        """Crawl a single URL and extract information."""
        try:
            async with httpx.AsyncClient(headers=self.headers, timeout=self.crawl_timeout) as client:
                response = await client.get(url)
                response.raise_for_status()
                
                content_type = response.headers.get("Content-Type", "").lower()
                if "text/html" not in content_type:
                    # Not HTML, skip
                    return []
                
                html = response.text
                soup = BeautifulSoup(html, "html.parser")
                
                # Remove unwanted elements
                for element in soup(["script", "style", "nav", "footer", "head", "iframe", "svg"]):
                    element.decompose()
                
                # Extract page title
                title = soup.title.string if soup.title else url
                
                # Extract main content
                main_content = self._extract_main_content(soup)
                
                if not main_content:
                    # Fallback to body text
                    body = soup.find("body")
                    if body:
                        main_content = body.get_text().strip()
                
                if not main_content:
                    return []
                
                # Create result
                result = {
                    "title": str(title)[:200],
                    "url": url,
                    "snippet": str(main_content)[:2000],
                    "source": "direct_crawl",
                }
                
                return [result]
                
        except Exception as e:
            logger.warning(f"[DIRECT_CRAWL] Failed to crawl {url}: {e}")
            return []

    async def _extract_links(self, url: str) -> List[str]:
        """Extract links from a URL."""
        try:
            async with httpx.AsyncClient(headers=self.headers, timeout=self.crawl_timeout) as client:
                response = await client.get(url)
                response.raise_for_status()
                
                html = response.text
                soup = BeautifulSoup(html, "html.parser")
                
                links = []
                for a in soup.find_all("a", href=True):
                    href = a["href"].strip()
                    if not href or href.startswith("#"):
                        continue
                    
                    # Make absolute URL
                    absolute_url = urljoin(url, href)
                    
                    # Filter for same domain and interesting paths
                    if self._is_interesting_link(absolute_url, url):
                        links.append(absolute_url)
                
                return links[:50]  # Limit to 50 links
                
        except Exception as e:
            logger.warning(f"[DIRECT_CRAWL] Failed to extract links from {url}: {e}")
            return []

    def _extract_main_content(self, soup: Any) -> str:
        """Extract main content from a BeautifulSoup object."""
        # Try to find main content section
        main = soup.find("main") or soup.find("article") or soup.find(class_=re.compile("main|content|body"))
        
        if main:
            text = main.get_text().strip()
            if len(text) > 100:  # Only return if substantial
                return self._clean_text(text)
        
        # Try to find paragraph tags
        paragraphs = soup.find_all("p")
        if paragraphs:
            text = "\n".join(p.get_text().strip() for p in paragraphs[:20])
            if len(text) > 100:
                return self._clean_text(text)
        
        return ""

    def _clean_text(self, text: str) -> str:
        """Clean extracted text."""
        # Remove excessive whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        # Remove non-printable characters
        text = ''.join(char for char in text if char.isprintable() or char.isspace())
        # Limit length
        return text[:5000]

    def _is_url(self, query: str) -> bool:
        """Check if a query is a URL."""
        try:
            result = urlparse(query)
            return all([result.scheme, result.netloc])
        except Exception:
            return False

    def _is_interesting_link(self, url: str, base_url: str) -> bool:
        """Check if a link is interesting to crawl."""
        # Same domain check
        base_domain = urlparse(base_url).netloc
        link_domain = urlparse(url).netloc
        
        if link_domain != base_domain:
            return False
        
        # Check for interesting paths
        interesting_keywords = [
            "about", "who", "what", "mission", "vision", "history",
            "publication", "report", "document", "paper", "pdf",
            "member", "partner", "client", "customer", "stakeholder",
            "service", "product", "solution", "offering",
            "contact", "address", "location", "office",
            "news", "press", "media", "announcement",
            "annual", "financial", "strategy", "plan",
        ]
        
        path = urlparse(url).path.lower()
        for keyword in interesting_keywords:
            if keyword in path:
                return True
        
        # Default: only follow links that look like content pages
        # (not images, CSS, JS, etc.)
        if any(path.endswith(ext) for ext in ['.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx']):
            return True
        
        if any(ext in path for ext in ['.css', '.js', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico']):
            return False
        
        return True

    def _discover_official_urls(self, query: str, context: Optional[Dict[str, Any]]) -> List[str]:
        """Discover official URLs from query and context."""
        urls = []
        
        # Check context for known URLs
        if context:
            if "official_website" in context:
                urls.append(context["official_website"])
            if "urls" in context:
                urls.extend(context["urls"])
            if "sources" in context:
                urls.extend(context["sources"])
        
        # Try to extract URL from query if it's a URL
        if self._is_url(query):
            urls.append(query)
        
        # Try common patterns for official websites
        acronym = self._extract_acronym(query)
        base_name = self._remove_acronym(query)
        
        if acronym:
            urls.extend([
                f"https://{acronym.lower()}.org/",
                f"https://{acronym.lower()}.com/",
                f"https://www.{acronym.lower()}.org/",
                f"https://www.{acronym.lower()}.com/",
            ])
        
        # Clean and deduplicate
        urls = list(set(urls))
        return [url for url in urls if self._is_url(url)]

    def _generate_common_urls(self, query: str) -> List[str]:
        """Generate common URL patterns for the query.
        
        For African entities, prioritize .co.zw, .za, .gov.zw domains.
        For international entities, try .org, .com, .int, .gov.
        """
        acronym = self._extract_acronym(query)
        base_name = self._remove_acronym(query)
        
        urls = []
        
        # African country-specific domains (Zimbabwe uses .co.zw)
        african_domains = [
            f"https://{acronym.lower()}.co.zw/" if acronym else None,
            f"https://www.{acronym.lower()}.co.zw/" if acronym else None,
            f"https://{base_name.lower().replace(' ', '-')}.co.zw/",
            f"https://www.{base_name.lower().replace(' ', '-')}.co.zw/",
            f"https://{acronym.lower()}.gov.zw/" if acronym else None,
            f"https://{base_name.lower().replace(' ', '-')}.gov.zw/",
        ]
        
        # SADC and African regional organizations
        sadc_domains = [
            f"https://{acronym.lower()}.sadc.int/" if acronym else None,
            f"https://www.{acronym.lower()}.sadc.int/" if acronym else None,
            f"https://sadc.int/",
        ]
        
        # International domains
        international_domains = [
            f"https://{acronym.lower()}.org/" if acronym else None,
            f"https://www.{acronym.lower()}.org/" if acronym else None,
            f"https://{acronym.lower()}.com/" if acronym else None,
            f"https://www.{acronym.lower()}.com/" if acronym else None,
            f"https://{base_name.lower().replace(' ', '-')}.org/",
            f"https://www.{base_name.lower().replace(' ', '-')}.org/",
            f"https://{base_name.lower().replace(' ', '-')}.com/",
        ]
        
        # Combine all domains
        all_domains = african_domains + sadc_domains + international_domains
        
        # Filter out None values and deduplicate
        urls = list(set([d for d in all_domains if d is not None]))
        return [url for url in urls if self._is_url(url)]

    def _extract_acronym(self, name: str) -> Optional[str]:
        """Extract acronym from parentheses at end of name."""
        match = re.search(r"\s*\(([A-Z]{2,})\)\s*$", name.strip())
        if match:
            return match.group(1).strip()
        return None

    def _remove_acronym(self, name: str) -> str:
        """Remove acronym in parentheses from end of name."""
        return re.sub(r"\s*\([^)]+\)\s*$", "", name.strip())
