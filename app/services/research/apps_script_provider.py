"""Google Apps Script Search Gateway provider for NORA research.

This is the ONLY search provider. It queries a Google Apps Script web app that acts
as a search gateway, aggregating results from multiple search engines (DuckDuckGo,
Bing, etc.) and returning them in a unified JSON format.

Configuration:
    APPS_SCRIPT_SEARCH_URL: The base URL of the Apps Script gateway deployment

Example endpoint format:
    https://script.google.com/macros/s/<DEPLOYMENT_ID>/exec

At runtime, the query is appended as a URL parameter:
    https://script.google.com/macros/s/<DEPLOYMENT_ID>/exec?q=<URL_ENCODED_QUERY>
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

import httpx

from app import config
from app.services.research.search_provider import ProviderRole, SearchProvider
from app.logging import logger


class AppsScriptSearchProvider(SearchProvider):
    """Search provider using a Google Apps Script search gateway.
    
    This is the ONLY search provider for NORA. The Apps Script gateway is an
    external discovery service that aggregates results from multiple search engines.
    
    Gateway response format:
    {
        "ok": true,
        "qualityOk": true,
        "query": "...",
        "count": 10,
        "results": [
            {
                "rank": 1,
                "score": 18.3,
                "url": "https://example.com"
            },
            ...
        ],
        "diagnostics": {...},
        "rawCandidateCount": 10,
        "qualityCount": 10
    }
    """

    role = ProviderRole.WEB_DISCOVERY

    USER_AGENT = "NORAResearchBot/1.0 (+https://github.com/tmakiriyado1-arch/atis-node-builder)"

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: float = 15.0,
        user_agent: Optional[str] = None,
        max_results: int = 10,
    ) -> None:
        """Initialize the Apps Script search provider.
        
        Args:
            base_url: Base URL of the Apps Script gateway. If not provided,
                     uses APPS_SCRIPT_SEARCH_URL from config.
            timeout: Request timeout in seconds
            user_agent: User-Agent string for HTTP requests
            max_results: Maximum number of results to return per query
        """
        if base_url:
            self.base_url = base_url.rstrip("/")
        else:
            self.base_url = getattr(config, 'APPS_SCRIPT_SEARCH_URL', None)
        
        if self.base_url:
            self.base_url = self.base_url.rstrip("/")
        
        if not self.base_url:
            logger.warning(
                "[APPS_SCRIPT] No APPS_SCRIPT_SEARCH_URL configured. "
                "Provider will return empty results."
            )
        
        self.timeout = timeout
        self.user_agent = user_agent or self.USER_AGENT
        self.max_results = max_results
        self.headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        }
        
        logger.info(f"[APPS_SCRIPT] Provider initialized with base_url={self.base_url or 'None'}, timeout={self.timeout}s")

    async def search(
        self,
        query: str,
        max_results: int = 10,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Search using the Google Apps Script search gateway.
        
        Args:
            query: The search query string
            max_results: Maximum number of results to return
            context: Optional context for query expansion (not used for basic search)
            
        Returns:
            List of result dictionaries with title, url, snippet, and metadata
            Returns empty list on any error - does NOT raise exceptions
        """
        cleaned_query = (query or "").strip()
        if not cleaned_query:
            logger.warning(f"[APPS_SCRIPT] Empty query received, returning empty results")
            return []
        
        if not self.base_url:
            logger.warning(f"[APPS_SCRIPT] No base_url configured, returning empty results")
            return []
        
        effective_max = min(max_results, self.max_results, 20)
        logger.info(f"[APPS_SCRIPT] Searching for '{cleaned_query[:100]}' (max_results={effective_max})")
        
        try:
            params = {"q": quote_plus(cleaned_query)}
            url = f"{self.base_url}?q={quote_plus(cleaned_query)}"
            
            logger.info(f"[APPS_SCRIPT] Request to base_url: {self.base_url}")
            
            async with httpx.AsyncClient(
                headers=self.headers,
                timeout=self.timeout,
                follow_redirects=True,
            ) as client:
                response = await client.get(url, params=params)
                
                if response.status_code != 200:
                    logger.warning(
                        f"[APPS_SCRIPT] HTTP {response.status_code} for query '{cleaned_query[:50]}'"
                    )
                    return []
                
                try:
                    data = response.json()
                except (ValueError, TypeError) as e:
                    logger.warning(
                        f"[APPS_SCRIPT] Invalid JSON response for '{cleaned_query[:50]}' - {type(e).__name__}: {e}"
                    )
                    return []
                
                results = self._parse_apps_script_response(data, cleaned_query, effective_max)
                logger.info(f"[APPS_SCRIPT] Returning {len(results)} results for '{cleaned_query[:50]}'")
                return results
                
        except httpx.ConnectError as e:
            logger.error(f"[APPS_SCRIPT] Connection failed for '{cleaned_query[:50]}' - {type(e).__name__}: {e}")
            return []
        except httpx.TimeoutException as e:
            logger.error(f"[APPS_SCRIPT] Timeout for '{cleaned_query[:50]}' - {type(e).__name__}: {e}")
            return []
        except httpx.HTTPStatusError as e:
            logger.error(f"[APPS_SCRIPT] HTTP error for '{cleaned_query[:50]}' - HTTP {e.response.status_code}: {e}")
            return []
        except httpx.HTTPError as e:
            logger.error(f"[APPS_SCRIPT] HTTP error for '{cleaned_query[:50]}' - {type(e).__name__}: {e}")
            return []
        except Exception as e:
            logger.error(f"[APPS_SCRIPT] Unexpected error for '{cleaned_query[:50]}' - {type(e).__name__}: {e}")
            return []

    def _parse_apps_script_response(
        self,
        data: Any,
        query: str,
        max_results: int,
    ) -> List[Dict[str, Any]]:
        """Parse Google Apps Script gateway JSON response into normalized result dictionaries."""
        results: List[Dict[str, Any]] = []
        
        if not isinstance(data, dict):
            logger.warning(f"[APPS_SCRIPT] Response is not a dict, got {type(data).__name__}")
            return []
        
        if data.get("ok") is False:
            error_msg = data.get("error", "Unknown gateway error")
            logger.warning(f"[APPS_SCRIPT] Gateway error: {error_msg}")
            return []
        
        if "results" not in data:
            logger.warning(f"[APPS_SCRIPT] Missing 'results' key in response - invalid gateway format")
            return []
        
        raw_results = data["results"]
        
        if not isinstance(raw_results, list):
            logger.warning(f"[APPS_SCRIPT] 'results' is not a list, got {type(raw_results).__name__}")
            return []
        
        if len(raw_results) == 0:
            logger.info(f"[APPS_SCRIPT] Valid response with empty results array (no matches found)")
            return []
        
        seen_urls: set[str] = set()
        for idx, item in enumerate(raw_results[:max_results]):
            if not isinstance(item, dict):
                continue
            
            url = (item.get("url") or "").strip()
            
            if not url:
                continue
            
            if url in seen_urls:
                continue
            seen_urls.add(url)
            
            rank = item.get("rank", idx + 1)
            score = item.get("score", 0.0)
            
            title = (item.get("title") or "").strip()
            if not title:
                title = url
            
            snippet = None
            
            metadata: Dict[str, Any] = {
                "gateway_rank": rank,
                "gateway_score": score,
                "quality_ok": data.get("qualityOk", False),
                "raw_candidate_count": data.get("rawCandidateCount", 0),
                "quality_count": data.get("qualityCount", 0),
            }
            
            result = {
                "title": title,
                "url": url,
                "snippet": snippet,
                "source": "apps_script",
                "metadata": metadata,
            }
            results.append(result)
        
        return results
