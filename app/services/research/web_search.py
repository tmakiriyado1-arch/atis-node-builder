"""Public, HTTP-based search provider backed by DuckDuckGo instant answer JSON."""
from __future__ import annotations

import json
from typing import Any, Dict, List

import httpx

from app.services.research.search_provider import SearchProvider


class WebSearchProvider(SearchProvider):
    """Small public search provider that does not require a paid API key."""

    def __init__(
        self,
        base_url: str = "https://api.duckduckgo.com/",
        timeout: float = 10.0,
        user_agent: str = "NORAResearchBot/1.0 (+https://example.com)",
    ) -> None:
        self.base_url = base_url
        self.timeout = timeout
        self.headers = {"User-Agent": user_agent, "Accept": "application/json"}

    async def search(
        self,
        query: str,
        max_results: int = 10,
    ) -> List[Dict[str, Any]]:
        cleaned_query = (query or "").strip()
        if not cleaned_query:
            return []

        params = {
            "q": cleaned_query,
            "format": "json",
            "no_redirect": "1",
            "no_html": "1",
            "skip_disambig": "1",
        }

        try:
            async with httpx.AsyncClient(headers=self.headers, timeout=self.timeout) as client:
                response = await client.get(self.base_url, params=params)
                response.raise_for_status()
        except (httpx.HTTPError, ValueError, TypeError):
            return []

        try:
            payload = response.json()
        except (ValueError, TypeError):
            return []

        if not isinstance(payload, dict):
            return []

        results: List[Dict[str, Any]] = []
        seen: set[str] = set()

        for item in payload.get("RelatedTopics", []):
            if isinstance(item, dict):
                result = self._coerce_item(item)
                if result:
                    url = str(result.get("url") or "").strip()
                    if url and url not in seen:
                        seen.add(url)
                        results.append(result)
            elif isinstance(item, list):
                for nested in item:
                    if not isinstance(nested, dict):
                        continue
                    result = self._coerce_item(nested)
                    if result:
                        url = str(result.get("url") or "").strip()
                        if url and url not in seen:
                            seen.add(url)
                            results.append(result)

        # Also check Results
        for item in payload.get("Results", []):
            if isinstance(item, dict):
                result = self._coerce_item(item)
                if result:
                    url = str(result.get("url") or "").strip()
                    if url and url not in seen:
                        seen.add(url)
                        results.append(result)

        # Check Definition
        definition_text = payload.get("Definition")
        definition_url = payload.get("DefinitionSource") or payload.get("DefinitionURL")
        if definition_text and definition_url:
            if definition_url not in seen:
                seen.add(definition_url)
                results.append(
                    {
                        "title": "Definition",
                        "url": str(definition_url),
                        "snippet": str(definition_text),
                    }
                )

        # Check Abstract
        if not results:
            abstract_text = payload.get("AbstractText")
            abstract_url = payload.get("AbstractURL")
            abstract_source = payload.get("Heading") or "Result"
            if abstract_url:
                if abstract_url not in seen:
                    seen.add(abstract_url)
                    results.append(
                        {
                            "title": str(abstract_source),
                            "url": str(abstract_url),
                            "snippet": str(abstract_text or ""),
                        }
                    )
            elif abstract_text:
                # If no URL but we have text, create a placeholder
                results.append(
                    {
                        "title": str(abstract_source),
                        "url": f"https://example.com/search?q={cleaned_query}",
                        "snippet": str(abstract_text),
                    }
                )

        return results[:max_results]

    @staticmethod
    def _coerce_item(item: Dict[str, Any]) -> Dict[str, Any]:
        try:
            title = str(item.get("Text") or item.get("Name") or item.get("title") or "Untitled result").strip()
            url = str(item.get("FirstURL") or item.get("URL") or item.get("url") or "").strip()
            snippet = str(item.get("Text") or item.get("snippet") or "").strip()
        except (AttributeError, TypeError, ValueError):
            return {}

        if not url:
            return {}

        clean_title = title.split(" - ")[0].strip() if title else "Untitled result"
        return {"title": clean_title, "url": url, "snippet": snippet or clean_title}
