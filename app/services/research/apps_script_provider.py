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

import time
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus, urlparse, urlunparse

import httpx

from app import config
from app.services.research.search_provider import ProviderRole, SearchProvider
from app.logging import logger


def _sanitize_url_for_logging(url: str) -> str:
    """Sanitize URL for logging by redacting sensitive query parameters.
    
    Preserves query parameters like 'q', 'max_results', 'action' but redacts
    any parameter values that look like secrets/tokens.
    """
    if not url:
        return url
    
    try:
        parsed = urlparse(url)
        query_params = parsed.query
        
        # Parameters to preserve as-is (these are safe to log)
        safe_params = {'q', 'max_results', 'action', 'provider', 'query', 'limit', 'offset', 'page'}
        
        # Parse query string
        from urllib.parse import parse_qs, urlencode
        params_dict = parse_qs(query_params, keep_blank_values=True)
        
        sanitized_params = {}
        for key, values in params_dict.items():
            if key.lower() in safe_params:
                # Preserve safe parameters
                sanitized_params[key] = values
            else:
                # Redact potentially sensitive parameters
                sanitized_params[key] = ['<redacted>'] * len(values)
        
        # Rebuild URL with sanitized query
        sanitized_query = urlencode(sanitized_params, doseq=True)
        sanitized_url = urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            sanitized_query,
            parsed.fragment
        ))
        return sanitized_url
    except Exception:
        # If parsing fails, return a redacted version
        return f"{url.split('?')[0]}?<query_params_redacted>"


def _get_elapsed_ms(start_time: float) -> int:
    """Get elapsed time in milliseconds from a start time."""
    return int((time.monotonic() - start_time) * 1000)


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
        # Generate instance identifier for tracking duplicate instances
        import uuid
        self._instance_id = f"{uuid.uuid4().hex[:8]}"
        
        # Set attributes first before logging
        self.timeout = timeout
        self.user_agent = user_agent or self.USER_AGENT
        self.max_results = max_results
        
        if base_url:
            self.base_url = base_url.rstrip("/")
        else:
            self.base_url = getattr(config, 'APPS_SCRIPT_SEARCH_URL', None)
        
        if self.base_url:
            self.base_url = self.base_url.rstrip("/")
        
        self.headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        }
        
        if not self.base_url:
            logger.warning(
                f"[APPS_SCRIPT] Provider initialized instance={self._instance_id} base_url=None "
                "Provider will return empty results."
            )
        else:
            logger.info(
                f"[APPS_SCRIPT] Provider initialized instance={self._instance_id} "
                f"base_url={_sanitize_url_for_logging(self.base_url)}, timeout={self.timeout}s"
            )

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
        request_start = time.monotonic()
        
        logger.info(
            f"[APPS_SCRIPT] REQUEST_START instance={self._instance_id} "
            f"query=\"{cleaned_query}\" max_results={max_results}"
        )
        
        if not cleaned_query:
            elapsed_ms = _get_elapsed_ms(request_start)
            logger.warning(
                f"[APPS_SCRIPT] REQUEST_EXCEPTION instance={self._instance_id} "
                f"elapsed_ms={elapsed_ms} type=ValueError message='Empty query'"
            )
            return []
        
        if not self.base_url:
            elapsed_ms = _get_elapsed_ms(request_start)
            logger.warning(
                f"[APPS_SCRIPT] REQUEST_EXCEPTION instance={self._instance_id} "
                f"elapsed_ms={elapsed_ms} type=ConfigurationError message='No base_url configured'"
            )
            return []
        
        effective_max = min(max_results, self.max_results, 20)
        logger.info(
            f"[APPS_SCRIPT] QUERY=\"{cleaned_query}\" MAX_RESULTS={effective_max} "
            f"TIMEOUT_SECONDS={self.timeout} instance={self._instance_id}"
        )
        
        try:
            params = {"q": quote_plus(cleaned_query)}
            url = f"{self.base_url}?q={quote_plus(cleaned_query)}"
            
            sanitized_url = _sanitize_url_for_logging(url)
            logger.info(f"[APPS_SCRIPT] REQUEST_URL={sanitized_url} instance={self._instance_id}")
            
            http_fetch_start = time.monotonic()
            logger.info(
                f"[APPS_SCRIPT] HTTP_FETCH_START instance={self._instance_id} "
                f"elapsed_ms={_get_elapsed_ms(request_start)}"
            )
            
            async with httpx.AsyncClient(
                headers=self.headers,
                timeout=self.timeout,
                follow_redirects=True,
            ) as client:
                try:
                    response = await client.get(url, params=params)
                    
                    http_fetch_elapsed = _get_elapsed_ms(http_fetch_start)
                    logger.info(
                        f"[APPS_SCRIPT] HTTP_FETCH_RETURN instance={self._instance_id} "
                        f"elapsed_ms={_get_elapsed_ms(request_start)} status={response.status_code}"
                    )
                    
                    # Log response metadata
                    content_type = response.headers.get('content-type', 'unknown')
                    body = response.content
                    body_length = len(body)
                    body_preview = body[:200].decode('utf-8', errors='replace') if body else ''
                    
                    logger.info(
                        f"[APPS_SCRIPT] RESPONSE instance={self._instance_id} "
                        f"elapsed_ms={_get_elapsed_ms(request_start)} "
                        f"status={response.status_code} content_type={content_type} "
                        f"body_length={body_length} body_preview={body_preview[:100]}"
                    )
                    
                    if response.status_code != 200:
                        elapsed_ms = _get_elapsed_ms(request_start)
                        logger.warning(
                            f"[APPS_SCRIPT] HTTP_ERROR instance={self._instance_id} "
                            f"elapsed_ms={elapsed_ms} status={response.status_code}"
                        )
                        return []
                    
                    parse_start = time.monotonic()
                    logger.info(
                        f"[APPS_SCRIPT] PARSE_START instance={self._instance_id} "
                        f"elapsed_ms={_get_elapsed_ms(request_start)}"
                    )
                    
                    try:
                        data = response.json()
                        
                        parse_elapsed = _get_elapsed_ms(parse_start)
                        logger.info(
                            f"[APPS_SCRIPT] RESPONSE_RECEIVED instance={self._instance_id} "
                            f"elapsed_ms={_get_elapsed_ms(request_start)} bytes={body_length}"
                        )
                        
                        # Validate response contract
                        self._validate_and_log_response_contract(data, request_start, self._instance_id)
                        
                        results = self._parse_apps_script_response(data, cleaned_query, effective_max)
                        
                        parse_success_elapsed = _get_elapsed_ms(request_start)
                        logger.info(
                            f"[APPS_SCRIPT] PARSE_SUCCESS instance={self._instance_id} "
                            f"elapsed_ms={parse_success_elapsed} results={len(results)}"
                        )
                        
                        request_end_elapsed = _get_elapsed_ms(request_start)
                        logger.info(
                            f"[APPS_SCRIPT] REQUEST_END instance={self._instance_id} "
                            f"elapsed_ms={request_end_elapsed} results={len(results)}"
                        )
                        
                        return results
                        
                    except (ValueError, TypeError) as e:
                        elapsed_ms = _get_elapsed_ms(request_start)
                        body_preview_500 = body[:500].decode('utf-8', errors='replace') if body else ''
                        logger.warning(
                            f"[APPS_SCRIPT] JSON_PARSE_FAILED instance={self._instance_id} "
                            f"elapsed_ms={elapsed_ms} body_length={body_length} "
                            f"body_preview={body_preview_500[:200]}"
                        )
                        logger.warning(
                            f"[APPS_SCRIPT] REQUEST_EXCEPTION instance={self._instance_id} "
                            f"elapsed_ms={elapsed_ms} type={type(e).__name__} "
                            f"message='Invalid JSON response'"
                        )
                        return []
                        
                except httpx.ConnectError as e:
                    elapsed_ms = _get_elapsed_ms(request_start)
                    logger.error(
                        f"[APPS_SCRIPT] HTTP_FETCH_EXCEPTION instance={self._instance_id} "
                        f"phase=http_fetch elapsed_ms={elapsed_ms} "
                        f"exception_type={type(e).__name__} message={str(e)[:200]}"
                    )
                    logger.error(
                        f"[APPS_SCRIPT] REQUEST_EXCEPTION instance={self._instance_id} "
                        f"elapsed_ms={elapsed_ms} type={type(e).__name__} "
                        f"message='Connection failed'"
                    )
                    return []
                except httpx.TimeoutException as e:
                    elapsed_ms = _get_elapsed_ms(request_start)
                    logger.error(
                        f"[APPS_SCRIPT] HTTP_FETCH_EXCEPTION instance={self._instance_id} "
                        f"phase=http_fetch elapsed_ms={elapsed_ms} "
                        f"exception_type={type(e).__name__} message={str(e)[:200]}"
                    )
                    logger.error(
                        f"[APPS_SCRIPT] REQUEST_EXCEPTION instance={self._instance_id} "
                        f"elapsed_ms={elapsed_ms} type={type(e).__name__} "
                        f"message='Request timed out'"
                    )
                    return []
                except httpx.HTTPStatusError as e:
                    elapsed_ms = _get_elapsed_ms(request_start)
                    logger.error(
                        f"[APPS_SCRIPT] HTTP_FETCH_EXCEPTION instance={self._instance_id} "
                        f"phase=http_fetch elapsed_ms={elapsed_ms} "
                        f"exception_type={type(e).__name__} "
                        f"message=HTTP {e.response.status_code}: {str(e)[:200]}"
                    )
                    logger.error(
                        f"[APPS_SCRIPT] REQUEST_EXCEPTION instance={self._instance_id} "
                        f"elapsed_ms={elapsed_ms} type={type(e).__name__} "
                        f"message='HTTP error'"
                    )
                    return []
                except httpx.HTTPError as e:
                    elapsed_ms = _get_elapsed_ms(request_start)
                    logger.error(
                        f"[APPS_SCRIPT] HTTP_FETCH_EXCEPTION instance={self._instance_id} "
                        f"phase=http_fetch elapsed_ms={elapsed_ms} "
                        f"exception_type={type(e).__name__} message={str(e)[:200]}"
                    )
                    logger.error(
                        f"[APPS_SCRIPT] REQUEST_EXCEPTION instance={self._instance_id} "
                        f"elapsed_ms={elapsed_ms} type={type(e).__name__} "
                        f"message='HTTP error'"
                    )
                    return []
                except Exception as e:
                    elapsed_ms = _get_elapsed_ms(request_start)
                    logger.error(
                        f"[APPS_SCRIPT] HTTP_FETCH_EXCEPTION instance={self._instance_id} "
                        f"phase=http_fetch elapsed_ms={elapsed_ms} "
                        f"exception_type={type(e).__name__} message={str(e)[:200]}"
                    )
                    logger.error(
                        f"[APPS_SCRIPT] REQUEST_EXCEPTION instance={self._instance_id} "
                        f"elapsed_ms={elapsed_ms} type={type(e).__name__} "
                        f"message={str(e)[:200]}"
                    )
                    return []
                    
        except Exception as e:
            elapsed_ms = _get_elapsed_ms(request_start)
            logger.error(
                f"[APPS_SCRIPT] REQUEST_EXCEPTION instance={self._instance_id} "
                f"elapsed_ms={elapsed_ms} type={type(e).__name__} "
                f"message={str(e)[:200]}"
            )
            return []

    def _validate_and_log_response_contract(
        self,
        data: Any,
        request_start: float,
        instance_id: str,
    ) -> None:
        """Validate and log the response contract from Apps Script."""
        elapsed_ms = _get_elapsed_ms(request_start)
        
        if not isinstance(data, dict):
            logger.warning(
                f"[APPS_SCRIPT] RESPONSE_CONTRACT instance={instance_id} "
                f"elapsed_ms={elapsed_ms} json_valid=false "
                f"results_type={type(data).__name__} results_length=0"
            )
            return
        
        ok_value = data.get("ok", False)
        quality_ok_value = data.get("qualityOk", False)
        count_value = data.get("count", 0)
        results_raw = data.get("results", [])
        results_length = len(results_raw) if isinstance(results_raw, list) else 0
        results_type = type(results_raw).__name__
        
        logger.info(
            f"[APPS_SCRIPT] RESPONSE_CONTRACT instance={instance_id} "
            f"elapsed_ms={elapsed_ms} json_valid=true "
            f"ok={ok_value} quality_ok={quality_ok_value} "
            f"count={count_value} results_type={results_type} "
            f"results_length={results_length}"
        )

    async def diagnostic_search(
        self,
        query: str = "Theotechnic College",
        max_results: int = 3,
    ) -> Dict[str, Any]:
        """Diagnostic method to test the Apps Script provider with a known query.
        
        This is NOT a replacement for the production provider.
        It exists solely to reproduce the Render-side failure.
        
        Returns a diagnostic report with timing and status information.
        """
        from datetime import datetime, timezone
        
        report: Dict[str, Any] = {
            "method": "diagnostic_search",
            "query": query,
            "max_results": max_results,
            "instance_id": self._instance_id,
            "base_url": _sanitize_url_for_logging(self.base_url) if self.base_url else None,
            "request_started": None,
            "request_returned": None,
            "status": None,
            "body_size": 0,
            "json_valid": False,
            "result_count": 0,
            "total_elapsed_ms": 0,
            "error": None,
        }
        
        if not self.base_url:
            report["error"] = "No base_url configured"
            report["total_elapsed_ms"] = 0
            return report
        
        try:
            request_start = time.monotonic()
            report["request_started"] = datetime.now(timezone.utc).isoformat()
            
            logger.info(
                f"[APPS_SCRIPT_DIAG] Diagnostic search started instance={self._instance_id} "
                f"query=\"{query}\" max_results={max_results}"
            )
            
            # Perform the actual search
            results = await self.search(query, max_results=max_results)
            
            report["request_returned"] = datetime.now(timezone.utc).isoformat()
            report["total_elapsed_ms"] = _get_elapsed_ms(request_start)
            report["result_count"] = len(results)
            report["status"] = "success"
            
            logger.info(
                f"[APPS_SCRIPT_DIAG] Diagnostic search completed instance={self._instance_id} "
                f"elapsed_ms={report['total_elapsed_ms']} results={len(results)}"
            )
            
        except Exception as e:
            report["request_returned"] = datetime.now(timezone.utc).isoformat()
            report["total_elapsed_ms"] = _get_elapsed_ms(request_start)
            report["status"] = "failed"
            report["error"] = f"{type(e).__name__}: {str(e)[:200]}"
            
            logger.error(
                f"[APPS_SCRIPT_DIAG] Diagnostic search failed instance={self._instance_id} "
                f"elapsed_ms={report['total_elapsed_ms']} error={report['error']}"
            )
        
        return report

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
