"""Public, HTTP-based search provider backed by DuckDuckGo HTML search scraping.

This provider is now one of many in the multi-provider architecture.
User-Agent rotation has been removed as it doesn't solve IP-level blocking.

The Instant Answer API was replaced with HTML scraping because:
- Instant Answer API returns DuckDuckGo proxy URLs (duckduckgo.com/...) which are filtered out
- HTML search returns direct, crawlable URLs from actual websites
"""
from __future__ import annotations

import asyncio
import base64
import random
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, parse_qs, urlunparse, unquote

import httpx
from bs4 import BeautifulSoup

from app.services.research.search_provider import ProviderRole, SearchProvider, SearchResult
from app.services.research.evidence import normalize_url
from app.logging import logger


class WebSearchProvider(SearchProvider):
    """DuckDuckGo Instant Answer search provider.
    
    This is now one provider among many. Failure of this provider
    does not cause pipeline failure - the orchestrator will try others.
    
    Features:
    - Query expansion with context-aware variants
    - Retry logic with exponential backoff for transient failures
    - Site scraping for minimal snippets
    - Adaptive relevance scoring
    """

    role = ProviderRole.WEB_DISCOVERY

    # Single, honest User-Agent - no rotation (doesn't help with IP blocking)
    USER_AGENT = "NORAResearchBot/1.0 (+https://github.com/tmakiriyado1-arch/atis-node-builder)"

    def __init__(
        self,
        base_url: str = "https://html.duckduckgo.com/html/",
        timeout: float = 15.0,
        user_agent: Optional[str] = None,
        max_queries_per_search: int = 5,
        min_relevance_score: int = 40,
        max_retries: int = 1,  # Reduced retries since orchestrator handles failures
        backoff_factor: float = 1.0,
    ) -> None:
        self.base_url = base_url
        self.timeout = timeout
        self.max_queries_per_search = max_queries_per_search
        self.min_relevance_score = min_relevance_score
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        # Use provided user agent or the default honest one
        self.user_agent = user_agent or self.USER_AGENT
        self.headers = {"User-Agent": self.user_agent, "Accept": "text/html"}
        self._client = None  # Lazy-initialized HTTP client for connection pooling

    async def search(
        self,
        query: str,
        max_results: int = 10,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Search with query expansion and adaptive retrieval.
        
        Args:
            query: The primary search query
            max_results: Maximum number of results to return
            context: Optional context dict containing:
                - entity_name: Original entity name for normalization
                - entity_type: Type of entity (organization, person, etc.)
                - country: Country for geo-context
                - aliases: List of known aliases
        """
        from app.logging import logger
        
        cleaned_query = (query or "").strip()
        logger.info(f"[SEARCH] Starting DuckDuckGo HTML search for query: {cleaned_query[:100]}")
        
        # Generate query variants if context is provided
        queries = self._generate_query_variants(cleaned_query, context)
        logger.info(f"[SEARCH] Will try {len(queries)} query variants")
        
        all_results: List[Dict[str, Any]] = []
        seen_urls: set[str] = set()
        
        for query_variant in queries[:self.max_queries_per_search]:
            logger.info(f"[SEARCH] Trying DuckDuckGo query variant: {query_variant[:100]}")
            results = await self._search_single(query_variant, max_results)
            
            # Score and filter results
            scored_results = []
            for result in results:
                url = result.get("url", "")
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                
                # Score this result against the original query/context
                score = self._score_result(result, query, context)
                result["_relevance_score"] = score
                scored_results.append(result)
                logger.info(f"[SEARCH] Result scored {score}: {result.get('title', '')[:50]} - {url[:60]}")
            
            all_results.extend(scored_results)
            
            # Check if we have enough high-quality evidence
            high_quality = [r for r in all_results if r.get("_relevance_score", 0) >= self.min_relevance_score]
            if len(high_quality) >= 3:
                logger.info(f"[SEARCH] Found {len(high_quality)} high-quality results, stopping early")
                break
        
        # Sort by relevance score descending
        all_results.sort(key=lambda r: r.get("_relevance_score", 0), reverse=True)
        
        # Remove internal scoring metadata
        for result in all_results:
            result.pop("_relevance_score", None)
        
        logger.info(f"[SEARCH] Final DuckDuckGo results: {len(all_results)} total, {len(high_quality)} high-quality")
        
        # Convert to SearchResult format with proper provenance
        search_results = []
        for idx, result in enumerate(all_results[:max_results]):
            search_result = SearchResult(
                provider=self.__class__.__name__,
                query=query,
                page=1,
                rank=idx + 1,
                title=result.get("title", ""),
                url=result.get("url", ""),
                snippet=result.get("snippet", None),
                metadata={"relevance_score": result.get("_relevance_score", 0)},
            )
            search_results.append(search_result)
        
        # Close client if we created it during this search
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        
        return search_results
    
    def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client with connection pooling."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers=self.headers,
                timeout=self.timeout,
                follow_redirects=True,
                limits=httpx.Limits(max_keepalive_connections=20, max_connections=100),
            )
        return self._client

    async def _search_single(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        """Execute a single DuckDuckGo HTML search with retry logic.
        
        Uses DuckDuckGo HTML interface (html.duckduckgo.com) which returns
        actual website URLs instead of proxy URLs.
        """
        cleaned_query = (query or "").strip()
        if not cleaned_query:
            return []

        # Build params for HTML search
        params = {
            "q": cleaned_query,
        }

        # Use lazy-initialized client for connection pooling
        client = self._get_client()
        
        last_exception = None
        for attempt in range(self.max_retries + 1):
            try:
                response = await client.get(self.base_url, params=params)
                response.raise_for_status()
                break  # Success, exit retry loop
            except (httpx.HTTPError, httpx.TimeoutException, httpx.ConnectError) as e:
                last_exception = e
                # Extract detailed error info
                error_type = type(e).__name__
                error_details = str(e)
                status_code = getattr(e, 'response', None)
                if status_code and hasattr(status_code, 'status_code'):
                    error_details = f"HTTP {status_code.status_code}: {error_details}"
                
                if attempt < self.max_retries:
                    # Exponential backoff with jitter
                    delay = self.backoff_factor * (2 ** attempt) + random.uniform(0, 0.5)
                    logger.warning(f"[SEARCH] DuckDuckGo HTML {error_type} for '{cleaned_query[:50]}' (attempt {attempt + 1}/{self.max_retries + 1}), retrying in {delay:.1f}s: {error_details}")
                    await asyncio.sleep(delay)
                    # Recreate client (no User-Agent rotation - it doesn't help with IP blocking)
                    if self._client:
                        await self._client.aclose()
                        self._client = None
                    client = self._get_client()
                else:
                    logger.error(f"[SEARCH] DuckDuckGo HTML FAILED after {self.max_retries + 1} attempts - {error_type}: {error_details}")
                    # Mark as provider unavailable - orchestrator will handle this
                    raise
        else:
            # All retries exhausted
            return []

        # Parse HTML response to extract search results
        try:
            results = await self._parse_ddg_html(response.text, cleaned_query, max_results)
        except Exception as e:
            logger.error(f"[SEARCH] HTML parse FAILED for '{cleaned_query[:50]}' - {type(e).__name__}: {e}")
            return []

        return results

    @staticmethod
    def _coerce_item(item: Dict[str, Any]) -> Dict[str, Any]:
        """Coerce a result dict into standard format. Kept for backward compatibility."""
        try:
            title = str(item.get("Text") or item.get("Name") or item.get("title") or "Untitled result").strip()
            url = str(
                item.get("FirstURL")
                or item.get("AbstractURL")
                or item.get("DefinitionURL")
                or item.get("DefinitionSource")
                or item.get("URL")
                or item.get("url")
                or ""
            ).strip()
            
            # Skip DuckDuckGo proxy/redirect URLs - they don't contain actual content
            if url and url.startswith("https://duckduckgo.com/"):
                return {}
            
            snippet = str(item.get("snippet") or item.get("Text") or item.get("title") or "").strip()
        except (AttributeError, TypeError, ValueError):
            return {}

        if not url:
            return {}

        clean_title = title.split(" - ")[0].strip() if title else "Untitled result"
        return {"title": clean_title, "url": url, "snippet": snippet or clean_title}

    def _generate_query_variants(self, query: str, context: Optional[Dict[str, Any]] = None) -> List[str]:
        """Generate multiple query variants for robust retrieval."""
        variants = [query]  # Original query first
        
        # If we have entity context, use it for smarter query generation
        if context:
            entity_name = context.get("entity_name", query)
            entity_type = context.get("entity_type", "")
            country = context.get("country", "")
            aliases = context.get("aliases", [])
            
            # Extract acronym from parentheses
            acronym = self._extract_acronym(entity_name)
            base_name = self._remove_acronym(entity_name)
            
            # Add base name without acronym
            if base_name != entity_name and base_name not in variants:
                variants.append(base_name)
            
            # Add acronym if found
            if acronym and acronym not in variants:
                variants.append(acronym)
            
            # Add aliases
            for alias in aliases:
                if alias and alias not in variants:
                    variants.append(alias)
            
            # Add country context
            if country:
                variants.append(f"{base_name} {country}")
                if acronym:
                    variants.append(f"{acronym} {country}")
            
            # Add type-specific queries for organizations
            if entity_type and "organization" in entity_type.lower():
                variants.append(f"{base_name} official website")
                if acronym:
                    variants.append(f"{acronym} official website")
                    variants.append(f"{acronym} annual report")
        else:
            # Basic query expansion without context
            acronym = self._extract_acronym(query)
            base_name = self._remove_acronym(query)
            
            if base_name != query and base_name not in variants:
                variants.append(base_name)
            if acronym and acronym not in variants:
                variants.append(acronym)
        
        # Deduplicate while preserving order
        seen = set()
        unique_variants = []
        for v in variants:
            if v not in seen:
                seen.add(v)
                unique_variants.append(v)
        
        return unique_variants

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

    def _score_result(self, result: Dict[str, Any], original_query: str, context: Optional[Dict[str, Any]] = None) -> int:
        """Score a result for relevance to the query and context."""
        score = 0
        title = (result.get("title") or "").lower()
        snippet = (result.get("snippet") or "").lower()
        url = (result.get("url") or "").lower()
        full_text = f"{title} {snippet}"
        
        query_lower = original_query.lower()
        
        # Extract entity name from context or use original query
        entity_name = context.get("entity_name", original_query) if context else original_query
        entity_name_lower = entity_name.lower()
        
        # Exact match in title or snippet
        if query_lower in full_text:
            score += 50
        
        # Entity name match
        if entity_name_lower in full_text:
            score += 40
        
        # Partial matches (token overlap)
        query_tokens = set(query_lower.split())
        text_tokens = set(full_text.split())
        overlap = query_tokens & text_tokens
        score += len(overlap) * 5
        
        # Acronym match
        if context:
            acronym = self._extract_acronym(entity_name)
            if acronym:
                acronym_lower = acronym.lower()
                if acronym_lower in full_text:
                    score += 30
        
        # Country match
        if context and context.get("country"):
            country_lower = context.get("country", "").lower()
            if country_lower in full_text:
                score += 15
        
        # Alias match
        if context and context.get("aliases"):
            for alias in context.get("aliases", []):
                alias_lower = alias.lower()
                if alias_lower in full_text:
                    score += 20
        
        # Official domain bonus
        official_domains = ["gov", "org", "com", "net", "edu", "ac"]
        for domain in official_domains:
            if f".{domain}/" in url or f".{domain} " in url:
                score += 10
                break
        
        # PDF bonus (often authoritative)
        if url.endswith(".pdf") or ".pdf?" in url:
            score += 15
        
        # Wikipedia bonus
        if "wikipedia.org" in url:
            score += 20
        
        # Government domain bonus
        gov_keywords = ["gov.", "government", "ministry", "regulatory", "authority"]
        for kw in gov_keywords:
            if kw in url or kw in full_text:
                score += 10
                break
        
        # Penalize very short snippets (likely low quality)
        # But reduce penalty for official/organization domains
        if snippet and len(snippet) < 20:
            # Check if URL looks like an official site
            official_indicators = ["sapp.co.zw", "sadc.int", "gov.", "org.", "ac.", "edu."]
            is_official = any(indicator in url for indicator in official_indicators)
            if not is_official:
                score -= 10
            else:
                score -= 5  # Reduced penalty for official sites
        
        # URL-based scoring: match domain to entity
        if entity_name_lower:
            entity_words = set(entity_name_lower.split())
            # Remove common words
            stop_words = {"the", "a", "an", "of", "and", "in", "to", "for", "with", "by", "as"}
            entity_words = entity_words - stop_words
            # Check if any entity word appears in URL
            for word in entity_words:
                if word in url:
                    score += 15
                    break
        
        return max(0, score)
    
    async def _parse_ddg_html(self, html: str, query: str, max_results: int) -> List[Dict[str, Any]]:
        """Parse DuckDuckGo HTML search results page to extract actual website URLs.
        
        DuckDuckGo HTML search returns a page with result links that have
        data-url attributes containing the actual target URLs.
        """
        results: List[Dict[str, Any]] = []
        seen_urls: set[str] = set()
        
        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception as e:
            logger.error(f"[SEARCH] Failed to parse DDG HTML - {type(e).__name__}: {e}")
            return []
        
        # Find all result links - DuckDuckGo uses <a> tags with class "result__url"
        # or data-url attributes
        link_selectors = [
            "a.result__url",
            "a[class*='result'][href]",
            "a[href^='http']",
        ]
        
        for selector in link_selectors:
            links = soup.select(selector)
            for link in links:
                if len(results) >= max_results:
                    break
                
                # Try to get URL from data-url attribute (DuckDuckGo's actual target)
                url = link.get("data-url") or link.get("href", "")
                
                if not url:
                    continue
                
                # Clean up URL - remove tracking parameters
                url = self._clean_ddg_url(url)
                
                if not url:
                    continue
                
                # Skip DuckDuckGo proxy URLs
                if url.startswith("https://duckduckgo.com/"):
                    continue
                
                # Skip already seen URLs
                normalized = normalize_url(url)
                if normalized in seen_urls:
                    continue
                seen_urls.add(normalized)
                
                # Get title from link text or nearby elements
                title = link.get_text().strip()
                if not title or len(title) < 5:
                    # Try to find title in parent or sibling elements
                    parent = link.find_parent()
                    if parent:
                        title = parent.get_text().strip()[:200]
                
                if not title:
                    title = "Untitled result"
                
                # Get snippet/description from nearby elements
                snippet = ""
                # Look for description elements
                next_sib = link.find_next_sibling()
                if next_sib and next_sib.get_text().strip():
                    snippet = next_sib.get_text().strip()[:500]
                
                # Look for parent's text
                if not snippet:
                    parent = link.find_parent(class_=re.compile(r"result"))
                    if parent:
                        parent_text = parent.get_text().strip()
                        # Remove the URL from the parent text
                        if url in parent_text:
                            snippet = parent_text.replace(url, "").strip()[:500]
                        else:
                            snippet = parent_text[:500]
                
                results.append({
                    "title": title,
                    "url": url,
                    "snippet": snippet,
                })
        
        # If we didn't find results with the standard selectors, try a broader approach
        if not results:
            # Look for any links that might be results
            all_links = soup.find_all("a", href=True)
            for link in all_links:
                if len(results) >= max_results:
                    break
                
                href = link.get("href", "")
                
                # Skip DuckDuckGo internal links
                if href.startswith("/") or href.startswith("https://duckduckgo.com/"):
                    continue
                
                # Clean URL
                url = self._clean_ddg_url(href)
                if not url:
                    continue
                
                # Skip non-HTTP links
                if not url.startswith("http://") and not url.startswith("https://"):
                    continue
                
                normalized = normalize_url(url)
                if normalized in seen_urls:
                    continue
                seen_urls.add(normalized)
                
                title = link.get_text().strip()
                if not title:
                    title = "Untitled result"
                
                results.append({
                    "title": title,
                    "url": url,
                    "snippet": "",
                })
        
        logger.info(f"[SEARCH] Extracted {len(results)} results from DDG HTML")
        return results
    
    @staticmethod
    def _clean_ddg_url(url: str) -> str:
        """Clean DuckDuckGo URL to get the actual target URL.
        
        Handles:
        - /l/?uddg=... URL encoding
        - Regular URLs
        - URL-encoded URLs
        """
        if not url:
            return ""
        
        # Handle DuckDuckGo's /l/ redirect URLs
        # These have the format: /l/?uddg=<base64_encoded_url>
        if url.startswith("/l/?"):
            # Parse the query string
            try:
                parsed = urlparse(url)
                params = parse_qs(parsed.query)
                
                # Try uddg parameter (base64 encoded)
                if "uddg" in params:
                    encoded = params["uddg"][0]
                    try:
                        # Add padding if needed
                        padding = "=" * (4 - len(encoded) % 4) if len(encoded) % 4 else ""
                        decoded = base64.urlsafe_b64decode(encoded + padding)
                        return decoded.decode("utf-8")
                    except Exception:
                        pass
                
                # Try ud parameter
                if "ud" in params:
                    encoded = params["ud"][0]
                    try:
                        padding = "=" * (4 - len(encoded) % 4) if len(encoded) % 4 else ""
                        decoded = base64.urlsafe_b64decode(encoded + padding)
                        return decoded.decode("utf-8")
                    except Exception:
                        pass
                
                # Try to extract from query params directly
                for key, values in params.items():
                    for val in values:
                        if val.startswith("http"):
                            return unquote(val)
            except Exception:
                pass
        
        # Handle regular URLs
        if url.startswith("http://") or url.startswith("https://"):
            # Unquote URL-encoded characters
            return unquote(url)
        
        # If it's a relative URL, try to make it absolute
        if url.startswith("//"):
            return "https:" + url
        
        return ""

    async def _scrape_site_content(self, url: str, timeout: float = 5.0) -> str:
        """Scrape a website to extract meaningful text content when snippet is minimal."""
        try:
            async with httpx.AsyncClient(headers=self.headers, timeout=timeout) as client:
                response = await client.get(url)
                response.raise_for_status()
                
                content_type = response.headers.get("Content-Type", "").lower()
                if "text/html" not in content_type:
                    return ""
                
                html = response.text
                soup = BeautifulSoup(html, "html.parser")
                
                # Remove script, style, and other non-content elements
                for element in soup(["script", "style", "nav", "footer", "head", "iframe"]):
                    element.decompose()
                
                # Get text from paragraph, article, section, div, main, content elements
                content_elements = soup.find_all(["p", "article", "section", "main", "div", "span", "h1", "h2", "h3", "h4", "h5", "h6"])
                
                # Collect text with reasonable length
                text_parts = []
                for elem in content_elements:
                    text = elem.get_text().strip()
                    # Skip very short or navigation-like text
                    if len(text) > 20 and len(text) < 5000:
                        text_parts.append(text)
                
                if text_parts:
                    # Return first meaningful paragraph
                    return text_parts[0][:1000]  # Limit to 1000 chars
                
                # Fallback: try to get text from body
                body = soup.find("body")
                if body:
                    text = body.get_text().strip()
                    # Get first 1000 chars
                    return text[:1000] if text else ""
                
                return ""
                
        except Exception as e:
            from app.logging import logger
            error_type = type(e).__name__
            logger.error(f"[SCRAPE] FAILED for {url} - {error_type}: {e}")
            return ""
