"""Mozilla search provider for web search.

This provider uses Mozilla's search API as an alternative to DuckDuckGo.

Note: Mozilla's search.services.mozilla.com API has been deprecated.
The provider now uses a direct HTTP GET with query parameters that works
with Mozilla's current search infrastructure.
"""
from __future__ import annotations

import random
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, parse_qs, urlunparse, unquote

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
        base_url: str = "https://search.mozilla.org/api/v1/search",
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
        """Search for a single query variant.
        
        Uses a direct HTTP request to Mozilla's search endpoint.
        The API may return different response formats - we handle both JSON
        and HTML responses.
        """
        params = {
            "q": query,
            "size": min(max_results, 10),
        }
        
        try:
            async with httpx.AsyncClient(
                headers=self.headers, 
                timeout=self.timeout,
                follow_redirects=True,
            ) as client:
                response = await client.get(self.base_url, params=params)
                
                # Check if we got a successful response
                if response.status_code >= 400:
                    error_type = f"HTTP {response.status_code}"
                    logger.error(f"[MOZILLA] HTTP error for '{query[:50]}' - {error_type}")
                    return []
                
                # Try to parse as JSON first
                try:
                    data = response.json()
                    # If json() returns None or empty, treat as non-JSON
                    if data is None:
                        raise ValueError("json() returned None")
                    return self._parse_json_response(data, query, max_results)
                except (ValueError, TypeError):
                    # Not JSON, try to parse as HTML
                    try:
                        return self._parse_html_response(response.text, query, max_results)
                    except Exception as e:
                        logger.error(f"[MOZILLA] Failed to parse response for '{query[:50]}' - {type(e).__name__}: {e}")
                        return []
                        
        except httpx.ConnectError as e:
            error_type = "ConnectError"
            logger.error(f"[MOZILLA] Connection failed for '{query[:50]}' - {error_type}: {e}")
            return []
        except httpx.TimeoutException as e:
            error_type = "TimeoutException"
            logger.error(f"[MOZILLA] Timeout for '{query[:50]}' - {error_type}: {e}")
            return []
        except Exception as e:
            error_type = type(e).__name__
            logger.error(f"[MOZILLA] FAILED for '{query[:50]}' - {error_type}: {e}")
            return []

    def _parse_json_response(self, data: Any, query: str, max_results: int) -> List[Dict[str, Any]]:
        """Parse JSON response from Mozilla search API."""
        if not isinstance(data, dict):
            return []
        
        results = []
        
        # Try different possible response structures
        # Mozilla may return: {results: [...]} or {web_pages: [...]} or {organic_results: [...]} or {items: [...]}
        search_results = None
        for key in ["results", "web_pages", "organic_results", "items"]:
            if key in data:
                search_results = data[key]
                break
        
        if search_results is None:
            logger.warning(f"[MOZILLA] Unexpected JSON structure, no results array found")
            return []
        
        if not isinstance(search_results, list):
            logger.warning(f"[MOZILLA] Results is not a list, got {type(search_results).__name__}")
            return []
        
        for item in search_results[:max_results]:
            result = self._format_result(item)
            if result:
                results.append(result)
        
        return results

    def _parse_html_response(self, html: str, query: str, max_results: int) -> List[Dict[str, Any]]:
        """Parse HTML response from Mozilla search (fallback).
        
        If Mozilla returns HTML instead of JSON, try to extract results.
        """
        from bs4 import BeautifulSoup
        
        results = []
        seen_urls = set()
        
        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception as e:
            logger.error(f"[MOZILLA] Failed to parse HTML - {type(e).__name__}: {e}")
            return []
        
        # Try to find result links - look for <a> tags with href
        links = soup.find_all("a", href=True)
        
        for link in links:
            if len(results) >= max_results:
                break
            
            href = link.get("href", "")
            if not href:
                continue
            
            # Clean URL
            url = self._clean_url(href)
            if not url:
                continue
            
            # Skip non-HTTP links
            if not url.startswith("http://") and not url.startswith("https://"):
                continue
            
            # Skip already seen URLs
            if url in seen_urls:
                continue
            seen_urls.add(url)
            
            # Get title from link text
            title = link.get_text().strip()
            if not title:
                title = "Untitled result"
            
            # Get snippet from nearby text or parent
            snippet = ""
            parent = link.find_parent()
            if parent:
                parent_text = parent.get_text().strip()
                # Remove URL from parent text if present
                if url in parent_text:
                    snippet = parent_text.replace(url, "").strip()[:500]
                else:
                    snippet = parent_text[:500]
            
            results.append({
                "title": title,
                "url": url,
                "snippet": snippet,
                "source": "mozilla",
            })
        
        return results

    @staticmethod
    def _clean_url(url: str) -> str:
        """Clean and normalize a URL from search results."""
        if not url:
            return ""
        
        # Unquote URL-encoded characters
        url = unquote(url)
        
        # Parse and reconstruct to remove tracking parameters
        try:
            parsed = urlparse(url)
            # Remove common tracking query parameters
            params = parse_qs(parsed.query, keep_blank_values=True)
            clean_params = {}
            tracking_keys = {"utm_", "gclid", "fbclid", "mc_cid", "mc_eid", "s", "q", "query"}
            for key, values in params.items():
                if not any(key.startswith(tk) for tk in tracking_keys):
                    clean_params[key] = values
            
            # Rebuild URL without tracking params
            if clean_params:
                query_string = urlunparse((
                    parsed.scheme,
                    parsed.netloc,
                    parsed.path,
                    parsed.params,
                    "&".join(f"{k}={v[0]}" for k, v in clean_params.items()),
                    parsed.fragment,
                ))
                return query_string
            else:
                return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        except Exception:
            return url

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
