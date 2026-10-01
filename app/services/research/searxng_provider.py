"""SearXNG metasearch engine provider for NORA research.

This provider queries a SearXNG instance (self-hosted metasearch engine) and
returns normalized search results compatible with NORA's SearchResult schema.

SearXNG aggregates results from multiple search engines (Wikipedia, Brave, Google CSE,
Wikidata, etc.) and returns them in a unified JSON format.

Configuration:
    SEARXNG_BASE_URL: The base URL of the SearXNG instance
    SEARXNG_LOCAL_ENABLED: Enable local SearXNG instance (default: True)
    SEARXNG_LOCAL_PORT: Port for local SearXNG (default: 8888)
    SEARXNG_REPO_PATH: Path to atis-searxng repository

The provider handles:
    - HTTP errors (connection, timeout, status codes)
    - Malformed JSON responses
    - Missing or invalid 'results' array
    - Empty result sets
    - Result normalization to SearchResult format
    - Local SearXNG instance management with fallback to external URL
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

import httpx

from app import config
from app.services.research.search_provider import ProviderRole, SearchProvider, SearchResult
from app.services.research.searxng_manager import get_searxng_manager
from app.logging import logger


class SearXNGProvider(SearchProvider):
    """Search provider using a SearXNG metasearch engine instance.
    
    SearXNG is a free, open-source metasearch engine that aggregates results
    from multiple search engines. This provider queries a configured SearXNG
    instance and normalizes the results for NORA's research pipeline.
    
    The provider is designed to be resilient - failures return empty results
    rather than raising exceptions, allowing the orchestrator to continue with
    other providers.
    """

    role = ProviderRole.WEB_DISCOVERY

    USER_AGENT = "NORAResearchBot/1.0 (+https://github.com/tmakiriyado1-arch/atis-node-builder)"

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: float = 15.0,
        user_agent: Optional[str] = None,
        max_results: int = 10,
        use_local: Optional[bool] = None,
        local_port: int = 8888,
    ) -> None:
        """Initialize the SearXNG provider.
        
        Args:
            base_url: Base URL of the SearXNG instance. If not provided,
                     uses SEARXNG_BASE_URL from config or tries local instance
            timeout: Request timeout in seconds
            user_agent: User-Agent string for HTTP requests
            max_results: Maximum number of results to return per query
            use_local: Whether to try local SearXNG first (default: from config)
            local_port: Port for local SearXNG instance
        """
        # Determine if we should use local SearXNG
        # Default to False to use atis-searxng.onrender.com (the remote instance)
        self.use_local = use_local if use_local is not None else getattr(config, 'SEARXNG_LOCAL_ENABLED', False)
        self.local_port = local_port
        
        # Try to determine base_url in this order:
        # 1. Provided base_url
        # 2. SEARXNG_BASE_URL from config
        # 3. Local SearXNG manager's base_url (only if local is enabled and available)
        # 4. Default external URL (fallback)
        
        self._external_base_url = base_url or getattr(config, 'SEARXNG_BASE_URL', None)
        
        # Check if local SearXNG is available (only if use_local is True)
        self._local_available = False
        self._base_url_from_manager: Optional[str] = None
        
        if self.use_local:
            manager = get_searxng_manager()
            if manager.enabled and manager.repo_path:
                self._base_url_from_manager = manager.base_url
                self._local_available = True
        
        # Determine final base_url
        # Priority: external URL > local manager URL > fallback
        if self._external_base_url:
            self.base_url = self._external_base_url
        elif self._base_url_from_manager:
            self.base_url = self._base_url_from_manager
        else:
            # Fallback to config default or hardcoded
            # atis-searxng.onrender.com is the primary remote SearXNG instance
            self.base_url = getattr(config, 'SEARXNG_BASE_URL', "https://atis-searxng.onrender.com")
        
        # Ensure base_url doesn't have trailing slash
        self.base_url = self.base_url.rstrip("/")
        
        self.timeout = timeout
        self.user_agent = user_agent or self.USER_AGENT
        self.max_results = max_results
        self.headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        }
        
        # Log the normalized endpoint being used (without secrets)
        logger.info(f"[SEARXNG] Provider initialized with base_url={self.base_url}, timeout={self.timeout}s")
        logger.info(f"[SEARXNG] Local SearXNG enabled: {self.use_local}, available: {self._local_available}")
        logger.info(f"[SEARXNG] Normalized SearXNG endpoint: {self.base_url}/search")

    async def search(
        self,
        query: str,
        max_results: int = 10,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Search using the SearXNG metasearch engine.
        
        This method will:
        1. Try to use the configured base_url (external or local)
        2. If using local and not yet started, attempt to start local SearXNG
        3. If local start fails, fall back to external URL
        4. If all SearXNG options fail, return empty list (not an error)
        5. Return empty list on any error (does NOT raise exceptions)
        
        The provider is designed to be resilient - failures return empty results
        rather than raising exceptions, allowing the orchestrator to continue with
        other providers.
        
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
            logger.warning(f"[SEARXNG] Empty query received, returning empty results")
            return []
        
        # Limit results to reasonable bounds
        effective_max = min(max_results, self.max_results, 20)
        
        logger.info(f"[SEARXNG] Searching for '{cleaned_query[:100]}' (max_results={effective_max})")
        
        # Get current base_url
        # When use_local is False (default), we skip all local SearXNG management
        # and use the external URL from config (SEARXNG_BASE_URL)
        current_base_url = self.base_url
        
        # Only attempt local SearXNG if explicitly enabled
        local_started = False
        if self.use_local:
            manager = get_searxng_manager()
            if manager.enabled:
                if not manager.is_running:
                    logger.info(f"[SEARXNG] Local SearXNG not running, attempting to start...")
                    if await manager.start():
                        local_started = True
                        current_base_url = manager.base_url
                        logger.info(f"[SEARXNG] Local SearXNG started at {current_base_url}")
                    else:
                        logger.warning(f"[SEARXNG] Failed to start local SearXNG, using configured URL: {current_base_url}")
                elif manager.is_running:
                    # Use the manager's base_url if it's running
                    current_base_url = manager.base_url
        else:
            # use_local is False - use external URL only, no local startup
            logger.debug(f"[SEARXNG] Local SearXNG disabled, using external URL: {current_base_url}")
        
        try:
            # Build the search URL with proper URL encoding
            # The base_url should already be normalized without trailing slash
            search_path = f"/search?q={quote_plus(cleaned_query)}&format=json"
            url = f"{current_base_url}{search_path}"
            
            # Log the exact URL being requested (without the API key which is in headers)
            logger.info(f"[SEARXNG] Request URL: {url}")
            
            async with httpx.AsyncClient(
                headers=self.headers,
                timeout=self.timeout,
                follow_redirects=False,  # Don't follow redirects - we want to detect them
            ) as client:
                response = await client.get(url)
                
                # Check for redirect responses
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("location", "")
                    logger.warning(
                        f"[SEARXNG] Redirect detected: {response.status_code} -> {location}"
                    )
                    # Don't follow redirects to arbitrary hosts
                    return []
                
                # Handle non-200 responses
                if response.status_code != 200:
                    logger.warning(
                        f"[SEARXNG] HTTP {response.status_code} for query '{cleaned_query[:50]}'"
                    )
                    # If we started local SearXNG and it's not working, stop it
                    if local_started:
                        logger.warning(f"[SEARXNG] Local SearXNG returned error, stopping it")
                        await manager.stop()
                    # Return empty - this is expected when SearXNG is unavailable
                    return []
                
                # Parse JSON response
                try:
                    data = response.json()
                except (ValueError, TypeError) as e:
                    logger.warning(
                        f"[SEARXNG] Invalid JSON response for '{cleaned_query[:50]}' - {type(e).__name__}: {e}"
                    )
                    return []
                
                # Validate and parse SearXNG response
                # The _parse_searxng_response method already validates structure
                results = self._parse_searxng_response(data, cleaned_query, effective_max)
                logger.info(f"[SEARXNG] Returning {len(results)} results for '{cleaned_query[:50]}'")
                return results
                
        except httpx.ConnectError as e:
            logger.error(f"[SEARXNG] Connection failed for '{cleaned_query[:50]}' - {type(e).__name__}: {e}")
            # If we started local and it's not connecting, stop it
            if local_started:
                await manager.stop()
            return []
        except httpx.TimeoutException as e:
            logger.error(f"[SEARXNG] Timeout for '{cleaned_query[:50]}' - {type(e).__name__}: {e}")
            if local_started:
                await manager.stop()
            return []
        except httpx.HTTPStatusError as e:
            # HTTP status error (4xx, 5xx) - application-level failure
            logger.error(f"[SEARXNG] HTTP error for '{cleaned_query[:50]}' - HTTP {e.response.status_code}: {e}")
            if local_started:
                await manager.stop()
            return []
        except httpx.HTTPError as e:
            logger.error(f"[SEARXNG] HTTP error for '{cleaned_query[:50]}' - {type(e).__name__}: {e}")
            if local_started:
                await manager.stop()
            return []
        except Exception as e:
            logger.error(f"[SEARXNG] Unexpected error for '{cleaned_query[:50]}' - {type(e).__name__}: {e}")
            if local_started:
                await manager.stop()
            return []

    def _parse_searxng_response(
        self,
        data: Any,
        query: str,
        max_results: int,
    ) -> List[Dict[str, Any]]:
        """Parse SearXNG JSON response into normalized result dictionaries.
        
        SearXNG response format:
        {
            "query": "...",
            "results": [
                {
                    "title": "...",
                    "url": "...",
                    "content": "...",  # snippet/description
                    "engine": "wikipedia",
                    "parsed_url": [...],
                    "engines": ["wikipedia", "brave", ...],
                    ...
                },
                ...
            ],
            ...
        }
        
        Args:
            data: Parsed JSON from SearXNG response
            query: The original search query
            max_results: Maximum number of results to return
            
        Returns:
            List of normalized result dictionaries
        """
        results: List[Dict[str, Any]] = []
        
        # Validate response structure - must be a dict
        if not isinstance(data, dict):
            logger.warning(f"[SEARXNG] Response is not a dict, got {type(data).__name__}")
            return []
        
        # Check for 'results' key - required for valid SearXNG response
        if "results" not in data:
            logger.warning(f"[SEARXNG] Missing 'results' key in response - invalid SearXNG format")
            return []
        
        raw_results = data["results"]
        
        # Validate that 'results' is a list
        if not isinstance(raw_results, list):
            logger.warning(f"[SEARXNG] 'results' is not a list, got {type(raw_results).__name__}")
            return []
        
        # Empty results array is valid - return empty list (not an error)
        # This means the query returned no results, which is different from a failure
        if len(raw_results) == 0:
            logger.info(f"[SEARXNG] Valid response with empty results array (no matches found)")
            return []
        
        # Process each result
        seen_urls: set[str] = set()
        for idx, item in enumerate(raw_results[:max_results]):
            if not isinstance(item, dict):
                continue
            
            # Extract fields with safe defaults
            title = (item.get("title") or "").strip()
            url = (item.get("url") or "").strip()
            
            # Skip empty URLs
            if not url:
                continue
            
            # Skip duplicate URLs
            if url in seen_urls:
                continue
            seen_urls.add(url)
            
            # Get snippet from 'content' or 'snippet' fields
            snippet = None
            content = item.get("content")
            if isinstance(content, str) and content.strip():
                snippet = content.strip()[:1000]  # Limit snippet size
            if not snippet:
                snippet = item.get("snippet")
                if isinstance(snippet, str):
                    snippet = snippet.strip()[:1000]
            
            # Extract engine information
            engine = item.get("engine", "unknown")
            engines = item.get("engines", [])
            if isinstance(engines, list) and engines:
                # Use the first engine if available
                if not engine or engine == "unknown":
                    engine = engines[0] if engines else "unknown"
            
            # Build metadata
            metadata: Dict[str, Any] = {
                "engine": engine,
                "engines": engines if isinstance(engines, list) else [],
                "searxng_score": item.get("score"),
                "searxng_position": idx + 1,
            }
            
            # Add parsed_url if available
            parsed_url = item.get("parsed_url")
            if parsed_url:
                metadata["parsed_url"] = parsed_url
            
            result = {
                "title": title,
                "url": url,
                "snippet": snippet,
                "source": "searxng",
                "metadata": metadata,
            }
            results.append(result)
        
        return results
