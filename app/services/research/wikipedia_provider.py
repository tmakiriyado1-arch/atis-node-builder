"""Wikipedia/MediaWiki search provider for authoritative entity information.

This provider uses the MediaWiki API to retrieve authoritative information
about entities, including official names, descriptions, and links.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx

from app.services.research.search_provider import ProviderRole, SearchProvider, SearchResult
from app.logging import logger


class EntityMatchError(Exception):
    """Raised when a Wikipedia result fails entity matching validation."""
    pass


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

    role = ProviderRole.REFERENCE

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
        
        # Extract acronym and base name for validation
        acronym = self._extract_acronym(cleaned_query)
        base_name = self._remove_acronym(cleaned_query)
        
        results = []
        
        # Generate query variants for better matching
        query_variants = self._generate_query_variants(cleaned_query, context)
        
        # Try each variant for direct page lookup
        for variant in query_variants:
            if len(results) >= max_results:
                break
            direct_result = await self._try_direct_page(variant)
            if direct_result:
                # Validate entity match before accepting
                if self._is_entity_match(
                    direct_result.get('title', ''),
                    direct_result.get('snippet', ''),
                    base_name,
                    acronym,
                ):
                    results.append(direct_result)
                    logger.info(f"[WIKIPEDIA] Found direct page: {direct_result.get('title', '')}")
                else:
                    logger.info(f"[WIKIPEDIA] Rejected direct page (entity mismatch): {direct_result.get('title', '')}")
        
        # If we don't have enough results, try search with original query
        if len(results) < max_results:
            search_results = await self._search_api(cleaned_query, max_results - len(results), base_name, acronym)
            for result in search_results:
                if result not in results:
                    results.append(result)
        
        # If still not enough, try search with variants
        if len(results) < max_results:
            for variant in query_variants:
                if len(results) >= max_results:
                    break
                search_results = await self._search_api(variant, max_results - len(results), base_name, acronym)
                for result in search_results:
                    if result not in results:
                        results.append(result)
        
        # Convert to SearchResult format and limit
        search_results = []
        for idx, result in enumerate(results[:max_results]):
            search_result = SearchResult(
                provider=self.__class__.__name__,
                query=cleaned_query,
                page=1,
                rank=idx + 1,
                title=result.get("title", ""),
                url=result.get("url", ""),
                snippet=result.get("snippet", None),
                metadata={"validated": True},
            )
            search_results.append(search_result)
        
        return search_results

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

    async def _search_api(
        self,
        query: str,
        max_results: int,
        base_name: Optional[str] = None,
        acronym: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Search Wikipedia using the OpenSearch API with filtering to avoid substring matches."""
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
        query_lower = query.lower()
        
        # Use provided base_name and acronym, or extract from query
        if base_name is None:
            base_name = self._remove_acronym(query)
        if acronym is None:
            acronym = self._extract_acronym(query)
        
        base_words = set(base_name.lower().split()) if base_name else set()
        
        for i, title in enumerate(data[1]):
            if i >= max_results:
                break
            url = data[3][i] if i < len(data[3]) else None
            snippet = data[2][i] if i < len(data[2]) else ""
            
            if not title or not url:
                continue
            
            title_lower = str(title).lower()
            title_words = set(title_lower.split())
            
            # Filter out substring matches for acronyms
            # If query contains an acronym in parentheses like "ZERA",
            # filter out results where the acronym appears as a substring in unrelated titles
            if acronym:
                # Check if title contains the acronym as a WHOLE WORD (not substring)
                # Use word boundary regex to match whole words only
                acronym_pattern = rf"\b{re.escape(acronym.lower())}\b"
                acronym_in_title = bool(re.search(acronym_pattern, title_lower))
                
                # Also check if acronym appears as substring (but not whole word)
                acronym_as_substring = (acronym.lower() in title_lower and not acronym_in_title)
                
                # Filter out results where:
                # 1. The acronym appears only as a substring (not whole word) AND
                # 2. The title doesn't contain any words from the base query
                if acronym_as_substring and len(base_words & title_words) == 0:
                    logger.info(f"[WIKIPEDIA] Filtering out substring match: {title}")
                    continue
                
                # Also filter out results where acronym appears as whole word but title
                # doesn't contain base query words (likely unrelated page with same acronym)
                if acronym_in_title and len(base_words & title_words) == 0:
                    # Check if this is a personal name
                    if self._is_personal_name(title_lower):
                        logger.info(f"[WIKIPEDIA] Filtering out personal name with acronym: {title}")
                        continue
            
            # Also filter out personal names when searching for organizational acronyms
            # (even without acronym in query)
            if len(base_words) > 0 and len(base_words & title_words) == 0:
                if self._is_personal_name(title_lower):
                    logger.info(f"[WIKIPEDIA] Filtering out personal name (no query match): {title}")
                    continue
            
            # Validate entity match for all results
            if not self._is_entity_match(title, snippet, base_name, acronym):
                logger.info(f"[WIKIPEDIA] Rejected search result (entity mismatch): {title}")
                continue
            
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
    def _is_personal_name(title: str) -> bool:
        """Check if a title looks like a personal name rather than an organization."""
        # Personal names typically have:
        # - 2-3 words, capitalized
        # - No organizational indicators (org, agency, authority, etc.)
        # - Common first names
        
        words = title.split()
        if len(words) < 2 or len(words) > 4:
            return False
        
        # Check for organizational keywords
        org_keywords = ['organization', 'agency', 'authority', 'company', 'corporation', 
                       'institution', 'ministry', 'department', 'commission', 'council',
                       'board', 'committee', 'foundation', 'institute', 'center', 'bureau',
                       'office', 'service', 'program', 'initiative', 'project',
                       'consortium', 'alliance', 'pool', 'cooperation', 'cooperative',
                       'network', 'association', 'group', 'firm', 'enterprise',
                       'government', 'public', 'state', 'national', 'regional',
                       'international', 'african', 'southern', 'development',
                       'regulatory', 'energy', 'power', 'electricity']
        
        title_lower = title.lower()
        if any(keyword in title_lower for keyword in org_keywords):
            return False
        
        # Check for common name patterns (Firstname Lastname)
        # Capitalized words that are common first names
        common_first_names = ['john', 'michael', 'david', 'james', 'robert', 'william',
                              'mary', 'jennifer', 'lisa', 'susan', 'patricia', 'linda',
                              'elizabeth', 'barbara', 'zera', 'zerelda', 'zerai', 'zerachiah',
                              'zerah', 'zeran', 'zerator', 'yacob', 'yisrael',
                              'amha', 'selassie', 'deres', 'zafara', 'zerafa',
                              'jacob', 'james', 'john', 'joseph', 'joshua', 'jonathan',
                              'matthew', 'mark', 'luke', 'andrew', 'peter', 'paul',
                              'stephen', 'steven', 'scott', 'sean', 'seth']
        
        if len(words) >= 2:
            first_word = words[0].lower()
            if first_word in common_first_names:
                # Check if this looks like "Firstname Lastname" pattern
                # Second word should also be capitalized (proper noun)
                if words[1][0].isupper():
                    return True
        
        return False

    def _is_entity_match(
        self,
        title: str,
        snippet: str,
        entity_name: str,
        acronym: Optional[str] = None,
    ) -> bool:
        """Determine if a Wikipedia result represents the same entity as the query.
        
        Uses normalized forms and requires sufficient evidence that the page
        represents the same entity. Acronym-only matches are validated against
        contextual evidence.
        
        Args:
            title: The Wikipedia page title
            snippet: The page snippet/description
            entity_name: The canonical entity name (without acronym)
            acronym: The extracted acronym (if any)
            
        Returns:
            True if the result represents the same entity, False otherwise
        """
        # Normalize all text for comparison
        def normalize(text: str) -> str:
            """Normalize text for comparison."""
            return re.sub(r'\s+', ' ', text.strip().lower())
        
        title_norm = normalize(title)
        snippet_norm = normalize(snippet)
        entity_norm = normalize(entity_name)
        combined_text = f"{title_norm} {snippet_norm}"
        
        # If we have no entity name to match against, accept (shouldn't happen)
        if not entity_norm:
            return True
        
        # Check 1: Full canonical name in title or snippet
        if entity_norm in title_norm or entity_norm in snippet_norm:
            return True
        
        # Check 2: Strong token overlap
        # Split entity name into meaningful tokens (remove common stop words)
        entity_words = set(w for w in entity_norm.split() if len(w) > 2)
        text_words = set(w for w in combined_text.split() if len(w) > 2)
        
        # If we have good overlap (at least 2+ matching tokens for multi-word entities)
        overlap = entity_words & text_words
        if len(overlap) >= 2:
            return True
        
        # Check 3: Acronym validation
        # If acronym is present, require additional contextual evidence
        if acronym:
            acronym_lower = acronym.lower()
            
            # Check if acronym appears as whole word in title
            acronym_pattern = rf"\b{re.escape(acronym_lower)}\b"
            acronym_in_title = bool(re.search(acronym_pattern, title_norm))
            
            if acronym_in_title:
                # Acronym is in title - check for contextual evidence
                # The page should mention the full entity name or have strong token overlap
                if entity_norm in combined_text:
                    return True
                
                # Check if snippet mentions the entity name
                if entity_norm in snippet_norm:
                    return True
                
                # Check for partial entity name in snippet
                # At least some of the entity words should appear
                if len(overlap) >= 1:
                    # For acronym-only matches, require at least 1 matching token
                    # but also check that this isn't a personal name
                    if self._is_personal_name(title_norm):
                        return False
                    # If we have at least 1 matching token and it's not a personal name,
                    # it might be valid (e.g., "ZERA" page that mentions "Zimbabwe" in snippet)
                    # But be conservative - require at least 2 matching tokens or full name
                    if len(overlap) >= 2:
                        return True
                    # If only 1 matching token, be very conservative
                    # Only accept if the entity is clearly organizational
                    if any(keyword in combined_text for keyword in 
                           ['authority', 'regulatory', 'energy', 'zimbabwe', 'organization', 
                            'agency', 'company', 'government', 'public']):
                        return True
                
                # If acronym in title but no entity overlap and it's a personal name, reject
                if self._is_personal_name(title_norm):
                    return False
        
        # Check 4: If no acronym and no overlap, reject
        # This catches random results that don't match the entity at all
        if len(overlap) == 0 and entity_norm not in combined_text:
            return False
        
        # Default: If we have some evidence but not strong, be conservative
        # For organizational queries, prefer false negatives over false positives
        return False

    @staticmethod
    def _remove_acronym(name: str) -> str:
        """Remove acronym in parentheses from end of name."""
        return re.sub(r"\s*\([^)]+\)\s*$", "", name.strip())
