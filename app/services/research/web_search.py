"""Public, HTTP-based search provider backed by DuckDuckGo instant answer JSON with site scraping."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

import httpx
from bs4 import BeautifulSoup

from app.services.research.search_provider import SearchProvider


class WebSearchProvider(SearchProvider):
    """Small public search provider that does not require a paid API key."""

    def __init__(
        self,
        base_url: str = "https://api.duckduckgo.com/",
        timeout: float = 10.0,
        user_agent: str = "NORAResearchBot/1.0 (+https://example.com)",
        max_queries_per_search: int = 5,
        min_relevance_score: int = 40,
    ) -> None:
        self.base_url = base_url
        self.timeout = timeout
        self.headers = {"User-Agent": user_agent, "Accept": "application/json"}
        self.max_queries_per_search = max_queries_per_search
        self.min_relevance_score = min_relevance_score

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
        
        logger.info(f"[SEARCH] Starting search for query: {query[:100]}")
        
        # Generate query variants if context is provided
        queries = self._generate_query_variants(query, context)
        logger.info(f"[SEARCH] Will try {len(queries)} query variants")
        
        all_results: List[Dict[str, Any]] = []
        seen_urls: set[str] = set()
        
        for query_variant in queries[:self.max_queries_per_search]:
            logger.info(f"[SEARCH] Trying query variant: {query_variant[:100]}")
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
        
        logger.info(f"[SEARCH] Final results: {len(all_results)} total, {len(high_quality)} high-quality")
        
        return all_results[:max_results]

    async def _search_single(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        """Execute a single DuckDuckGo search."""
        cleaned_query = (query or "").strip()
        if not cleaned_query:
            return []

        params = {
            "q": cleaned_query,
            "format": "json",
            "no_redirect": "1",
            "no_html": "1",
            "skip_disambig": "1",
            "pretty": "0",
        }

        try:
            async with httpx.AsyncClient(headers=self.headers, timeout=self.timeout) as client:
                response = await client.get(self.base_url, params=params)
                response.raise_for_status()
        except (httpx.HTTPError, ValueError, TypeError) as e:
            from app.logging import logger
            logger.warning(f"[SEARCH] DuckDuckGo request failed for '{cleaned_query[:50]}': {e}")
            return []

        try:
            payload = response.json()
        except (ValueError, TypeError):
            return []

        if not isinstance(payload, dict):
            return []

        results: List[Dict[str, Any]] = []
        seen: set[str] = set()

        # First, check Abstract - this is the most direct result
        abstract_text = payload.get("AbstractText")
        abstract_url = payload.get("AbstractURL")
        abstract_source = payload.get("Heading") or "Result"
        
        # Only use Abstract if it has both text AND a URL (provenance matters)
        if abstract_url and abstract_text and abstract_url not in seen:
            seen.add(abstract_url)
            results.append(
                {
                    "title": str(abstract_source),
                    "url": str(abstract_url),
                    "snippet": str(abstract_text or ""),
                }
            )

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

        # Post-process: scrape sites with minimal snippets
        for result in results:
            snippet = result.get("snippet", "")
            url = result.get("url", "")
            # If snippet is too short (less than 30 chars), try to scrape the site
            if snippet and len(snippet.strip()) < 30 and url:
                scraped = await self._scrape_site_content(url)
                if scraped and len(scraped) > len(snippet):
                    result["snippet"] = scraped

        return results[:max_results]

    @staticmethod
    def _coerce_item(item: Dict[str, Any]) -> Dict[str, Any]:
        try:
            title = str(item.get("Text") or item.get("Name") or item.get("title") or "Untitled result").strip()
            # Prioritize FirstURL (actual source) over any proxy URLs
            # But skip DuckDuckGo proxy URLs (they start with https://duckduckgo.com/)
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
            
            # For snippet, prefer dedicated snippet field, then Text, then title
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
            logger.warning(f"[SCRAPE] Failed to scrape {url}: {e}")
            return ""
