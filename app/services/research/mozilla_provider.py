"""Mozilla search provider for web search.

This provider uses Mozilla's search API as an alternative to DuckDuckGo.
"""
from __future__ import annotations

import random
import re
from typing import Any, Dict, List, Optional

import httpx

from app.services.research.search_provider import ProviderRole, SearchProvider, SearchResult
from app.logging import logger


class MozillaProvider(SearchProvider):
    """Search provider using Mozilla's search API.
    
    This is an alternative to DuckDuckGo that may work better from Render IPs.
    """

    role = ProviderRole.SECONDARY_WEB_SEARCH

    USER_AGENT = "NORAResearchBot/1.0 (+https://github.com/tmakiriyado1-arch/atis-node-builder)"

    def __init__(
        self,
        base_url: str = "https://search.services.mozilla.com/v1/search",
        timeout: float = 15.0,
        user_agent: Optional[str] = None,
        max_results: int = 10,
    ) -> None:
        self.base_url = base_url
        self.timeout = timeout
        self.user_agent = user_agent or self.USER_AGENT
        self.headers = {"User-Agent": self.user_agent, "Accept": "application/json"}
        self.max_results = max_results

    async def search(
        self,
        query: str,
        max_results: int = 10,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Search using Mozilla's search API.
        
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

        logger.info(f"[MOZILLA] Searching for '{cleaned_query[:100]}'")
        
        # Generate query variants
        query_variants = self._generate_query_variants(cleaned_query, context)
        
        all_results = []
        seen_urls = set()
        
        for variant in query_variants:
            if len(all_results) >= max_results:
                break
            
            results = await self._search_variant(variant, max_results - len(all_results))
            for result in results:
                url = result.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_results.append(result)
        
        logger.info(f"[MOZILLA] Found {len(all_results)} results")
        
        # Convert to SearchResult format
        search_results = []
        for idx, result in enumerate(all_results[:max_results]):
            search_result = SearchResult(
                provider=self.__class__.__name__,
                query=cleaned_query,
                page=1,
                rank=idx + 1,
                title=result.get("title", ""),
                url=result.get("url", ""),
                snippet=result.get("snippet", None),
                metadata={},
            )
            search_results.append(search_result)
        
        return search_results

    async def _search_variant(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        """Search for a single query variant."""
        params = {
            "q": query,
            "size": min(max_results, 10),
        }
        
        try:
            async with httpx.AsyncClient(headers=self.headers, timeout=self.timeout) as client:
                response = await client.get(self.base_url, params=params)
                response.raise_for_status()
                
                data = response.json()
        except Exception as e:
            error_type = type(e).__name__
            logger.error(f"[MOZILLA] FAILED for '{query[:50]}' - {error_type}: {e}")
            return []
        
        if not isinstance(data, dict):
            return []
        
        results = []
        
        # Mozilla returns results in a "results" array
        search_results = data.get("results", [])
        if not isinstance(search_results, list):
            return []
        
        for item in search_results[:max_results]:
            result = self._format_result(item)
            if result:
                results.append(result)
        
        return results

    def _format_result(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Format a Mozilla search result."""
        try:
            title = item.get("title", "")
            url = item.get("url", "")
            snippet = item.get("description", "") or item.get("snippet", "")
            
            if not title or not url:
                return None
            
            return {
                "title": str(title),
                "url": str(url),
                "snippet": str(snippet),
                "source": "mozilla",
            }
        except Exception:
            return None

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
            entity_type = context.get("entity_type", "")
            
            if country:
                variants.append(f"{base_name} {country}")
                if acronym:
                    variants.append(f"{acronym} {country}")
            
            if entity_type:
                variants.append(f"{base_name} {entity_type}")
                if acronym:
                    variants.append(f"{acronym} {entity_type}")
        
        # Deduplicate while preserving order
        seen = set()
        unique = []
        for v in variants:
            if v not in seen:
                seen.add(v)
                unique.append(v)
        return unique

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
