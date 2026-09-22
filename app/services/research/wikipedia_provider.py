"""Wikipedia/MediaWiki search provider for authoritative entity information.

This provider uses the MediaWiki API to retrieve authoritative information
about entities, including official names, descriptions, and links.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx

from app.services.research.search_provider import SearchProvider
from app.logging import logger


# List of Wikipedia domain variations for different regions
WIKIPEDIA_DOMAINS = [
    "en.wikipedia.org",
    "www.wikipedia.org",
]


class WikipediaProvider(SearchProvider):
    """Search provider for Wikipedia/MediaWiki content.
    
    Uses the MediaWiki API to retrieve page information, summaries,
    and search results with full provenance.
    """

    def __init__(
        self,
        base_url: str = "https://en.wikipedia.org/w/api.php",
        rest_base_url: str = "https://en.wikipedia.org/api/rest_v1",
        timeout: float = 15.0,
        user_agent: str = "NORAResearchBot/1.0 (+https://github.com/tmakiriyado1-arch/atis-node-builder)",
    ) -> None:
        self.base_url = base_url
        self.rest_base_url = rest_base_url
        self.timeout = timeout
        self.headers = {"User-Agent": user_agent, "Accept": "application/json"}

    async def search(
        self,
        query: str,
        max_results: int = 10,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Search Wikipedia for the query.
        
        Args:
            query: The search query
            max_results: Maximum number of results to return
            context: Optional context for query expansion
            
        Returns:
            List of result dictionaries with title, url, snippet
        """
        cleaned_query = (query or "").strip()
        if not cleaned_query:
            return []

        logger.info(f"[WIKIPEDIA] Searching for '{cleaned_query[:100]}'")
        
        results = []
        
        # Generate query variants for better matching
        query_variants = self._generate_query_variants(cleaned_query, context)
        
        # Try each variant for direct page lookup
        for variant in query_variants:
            if len(results) >= max_results:
                break
            direct_result = await self._try_direct_page(variant)
            if direct_result:
                results.append(direct_result)
                logger.info(f"[WIKIPEDIA] Found direct page: {direct_result.get('title', '')}")
        
        # If we don't have enough results, try search with original query
        if len(results) < max_results:
            search_results = await self._search_api(cleaned_query, max_results - len(results))
            for result in search_results:
                if result not in results:
                    results.append(result)
        
        # If still not enough, try search with variants
        if len(results) < max_results:
            for variant in query_variants:
                if len(results) >= max_results:
                    break
                search_results = await self._search_api(variant, max_results - len(results))
                for result in search_results:
                    if result not in results:
                        results.append(result)
        
        # Limit results
        return results[:max_results]

    async def _try_direct_page(self, query: str) -> Optional[Dict[str, Any]]:
        """Try to fetch a page directly by its title."""
        # Clean the query to be a valid page title
        page_title = self._clean_page_title(query)
        
        # Try to get page summary via REST API (preferred - more reliable)
        try:
            result = await self._get_page_summary_rest(page_title)
            if result:
                return result
        except Exception as e:
            logger.warning(f"[WIKIPEDIA] REST API failed for '{page_title}': {e}")
        
        # Fallback to action API
        try:
            result = await self._get_page_summary_action(page_title)
            if result:
                return result
        except Exception as e:
            logger.warning(f"[WIKIPEDIA] Action API failed for '{page_title}': {e}")
        
        return None

    async def _search_api(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        """Search Wikipedia using the OpenSearch API."""
        params = {
            "action": "opensearch",
            "search": query,
            "limit": min(max_results, 10),
            "namespace": 0,  # Main namespace only
            "format": "json",
            "suggest": "",
        }
        
        try:
            async with httpx.AsyncClient(headers=self.headers, timeout=self.timeout) as client:
                response = await client.get(self.base_url, params=params)
                response.raise_for_status()
                data = response.json()
        except Exception as e:
            logger.warning(f"[WIKIPEDIA] OpenSearch failed for '{query[:50]}': {e}")
            return []
        
        if not isinstance(data, list) or len(data) < 2:
            return []
        
        results = []
        for i, title in enumerate(data[1]):
            if i >= max_results:
                break
            url = data[3][i] if i < len(data[3]) else None
            snippet = data[2][i] if i < len(data[2]) else ""
            
            if title and url:
                results.append({
                    "title": str(title),
                    "url": str(url),
                    "snippet": str(snippet),
                    "source": "wikipedia",
                })
        
        return results

    async def _get_page_summary_rest(self, page_title: str) -> Optional[Dict[str, Any]]:
        """Get page summary via REST API."""
        url = f"{self.rest_base_url}/page/summary/{quote(page_title)}"
        
        try:
            async with httpx.AsyncClient(headers=self.headers, timeout=self.timeout) as client:
                response = await client.get(url)
                
                if response.status_code == 404:
                    return None
                
                response.raise_for_status()
                data = response.json()
        except Exception as e:
            logger.warning(f"[WIKIPEDIA] REST summary failed for '{page_title}': {e}")
            return None
        
        if not isinstance(data, dict):
            return None
        
        title = data.get("title") or page_title
        extract = data.get("extract") or data.get("description") or ""
        
        # Build the canonical URL
        page_url = f"https://en.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}"
        
        return {
            "title": str(title),
            "url": page_url,
            "snippet": str(extract)[:1000] if extract else "",
            "source": "wikipedia",
        }

    async def _get_page_summary_action(self, page_title: str) -> Optional[Dict[str, Any]]:
        """Get page summary via Action API."""
        params = {
            "action": "query",
            "format": "json",
            "prop": "extracts|info",
            "titles": page_title,
            "exintro": "",
            "explaintext": "",
            "inprop": "url",
        }
        
        try:
            async with httpx.AsyncClient(headers=self.headers, timeout=self.timeout) as client:
                response = await client.get(self.base_url, params=params)
                response.raise_for_status()
                data = response.json()
        except Exception as e:
            logger.warning(f"[WIKIPEDIA] Action API summary failed for '{page_title}': {e}")
            return None
        
        if not isinstance(data, dict):
            return None
        
        pages = data.get("query", {}).get("pages", {})
        if not pages:
            return None
        
        # Get the first page
        page_id, page_data = next(iter(pages.items()))
        
        if page_id == "-1":  # Page doesn't exist
            return None
        
        title = page_data.get("title") or page_title
        extract = page_data.get("extract") or ""
        full_url = page_data.get("fullurl") or f"https://en.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}"
        
        return {
            "title": str(title),
            "url": str(full_url),
            "snippet": str(extract)[:1000] if extract else "",
            "source": "wikipedia",
        }

    def _generate_query_variants(self, query: str, context: Optional[Dict[str, Any]] = None) -> List[str]:
        """Generate query variants for better matching."""
        variants = [query]
        
        # Extract acronym from parentheses
        acronym = self._extract_acronym(query)
        base_name = self._remove_acronym(query)
        
        if base_name and base_name != query:
            variants.append(base_name)
        if acronym:
            variants.append(acronym)
        
        # Add context-based variants if available
        if context:
            country = context.get("country", "")
            if country:
                variants.append(f"{base_name} {country}")
                if acronym:
                    variants.append(f"{acronym} {country}")
        
        # Deduplicate while preserving order
        seen = set()
        unique = []
        for v in variants:
            if v not in seen:
                seen.add(v)
                unique.append(v)
        return unique

    def _clean_page_title(self, query: str) -> str:
        """Clean a query to be a valid Wikipedia page title."""
        # Remove parentheses and their contents
        cleaned = re.sub(r'\s*\([^)]*\)\s*', '', query)
        # Remove common prefixes
        cleaned = re.sub(r'^(The|A|An)\s+', '', cleaned, flags=re.IGNORECASE)
        # Normalize whitespace
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        return cleaned

    @staticmethod
    def _extract_acronym(name: str) -> Optional[str]:
        """Extract acronym from parentheses at end of name."""
        match = re.search(r"\s*\(([A-Z]{2,})\)\s*$", name.strip())
        if match:
            return match.group(1).strip()
        return None

    @staticmethod
    def _remove_acronym(name: str) -> str:
        """Remove acronym in parentheses from end of name."""
        return re.sub(r"\s*\([^)]+\)\s*$", "", name.strip())
