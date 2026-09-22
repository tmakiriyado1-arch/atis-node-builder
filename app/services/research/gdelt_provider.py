"""GDELT provider for news and document coverage.

This provider queries the GDELT DOC API to retrieve news articles and documents
mentioning the entity, with sentence-level context.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx

from app.services.research.search_provider import SearchProvider
from app.logging import logger


class GDELTProvider(SearchProvider):
    """Search provider for GDELT news/document coverage.
    
    Uses the GDELT DOC API to search for articles mentioning the entity.
    Provides sentence-level context and provenance.
    """

    def __init__(
        self,
        base_url: str = "https://api.gdeltproject.org/api/v2/doc/doc",
        timeout: float = 15.0,
        user_agent: str = "NORAResearchBot/1.0 (+https://github.com/tmakiriyado1-arch/atis-node-builder)",
        max_days_back: int = 365,
    ) -> None:
        self.base_url = base_url
        self.timeout = timeout
        self.headers = {"User-Agent": user_agent, "Accept": "application/json"}
        self.max_days_back = max_days_back

    async def search(
        self,
        query: str,
        max_results: int = 10,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Search GDELT for articles mentioning the entity.
        
        Args:
            query: The entity name to search for
            max_results: Maximum number of results to return
            context: Optional context for query expansion
            
        Returns:
            List of result dictionaries with title, url, snippet
        """
        cleaned_query = (query or "").strip()
        if not cleaned_query:
            return []

        logger.info(f"[GDELT] Searching for '{cleaned_query[:100]}'")
        
        # Build GDELT query with OR for acronyms
        # Extract acronym from parentheses if present
        acronym = self._extract_acronym(cleaned_query)
        base_name = self._remove_acronym(cleaned_query)
        
        # Build query with OR
        query_parts = [f'"{cleaned_query}"']
        if acronym:
            query_parts.append(f'"{acronym}"')
        if base_name != cleaned_query:
            query_parts.append(f'"{base_name}"')
        
        gdelt_query = " OR ".join(query_parts)
        
        # Calculate date range (last year by default)
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=self.max_days_back)
        
        params = {
            "query": gdelt_query,
            "mode": "artlist",
            "format": "json",
            "maxrecords": min(max_results, 50),
            "startdate": start_date.strftime("%Y%m%d"),
            "enddate": end_date.strftime("%Y%m%d"),
            "sort": "dateasc",
        }
        
        try:
            async with httpx.AsyncClient(headers=self.headers, timeout=self.timeout) as client:
                response = await client.get(self.base_url, params=params)
                
                # GDELT may return 429 (rate limit) or other errors
                if response.status_code != 200:
                    if response.status_code == 429:
                        logger.warning(f"[GDELT] Rate limited for query '{cleaned_query[:50]}'")
                        return []
                    logger.warning(f"[GDELT] API error {response.status_code} for '{cleaned_query[:50]}'")
                    return []
                
                data = response.json()
        except Exception as e:
            logger.warning(f"[GDELT] Search failed for '{cleaned_query[:50]}': {e}")
            return []
        
        if not isinstance(data, dict):
            return []
        
        articles = data.get("articles", [])
        if not articles:
            return []
        
        results = []
        for article in articles[:max_results]:
            result = self._format_article(article, cleaned_query)
            if result:
                results.append(result)
        
        logger.info(f"[GDELT] Found {len(results)} articles")
        return results

    def _format_article(self, article: Dict[str, Any], query: str) -> Optional[Dict[str, Any]]:
        """Format a GDELT article as a search result."""
        try:
            url = article.get("url") or article.get("articleurl")
            title = article.get("title") or article.get("headline") or "Untitled"
            date = article.get("date") or article.get("seendate")
            
            if not url:
                return None
            
            # Get the first sentence or description
            snippet = article.get("leadparagraph") or article.get("description") or ""
            
            # If snippet is empty, use the first few words of the title
            if not snippet and title:
                snippet = title[:200]
            
            return {
                "title": str(title)[:200],
                "url": str(url),
                "snippet": str(snippet)[:500],
                "source": "gdelt",
                "published_date": str(date) if date else None,
            }
        except Exception as e:
            logger.warning(f"[GDELT] Failed to format article: {e}")
            return None

    def _extract_acronym(self, name: str) -> Optional[str]:
        """Extract acronym from parentheses at end of name."""
        import re
        match = re.search(r"\s*\(([A-Z]{2,})\)\s*$", name.strip())
        if match:
            return match.group(1).strip()
        return None

    def _remove_acronym(self, name: str) -> str:
        """Remove acronym in parentheses from end of name."""
        import re
        return re.sub(r"\s*\([^)]+\)\s*$", "", name.strip())
