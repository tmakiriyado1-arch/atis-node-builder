"""Wikidata provider for entity identity resolution and structured data.

This provider queries Wikidata to retrieve canonical entity information,
including labels, aliases, descriptions, official websites, and structured metadata.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx

from app.services.research.search_provider import ProviderRole, SearchProvider, SearchResult
from app.logging import logger


class WikidataProvider(SearchProvider):
    """Search provider for Wikidata entity information.
    
    Uses the Wikidata Query Service (WDQS) SPARQL endpoint and the Wikidata API
    to retrieve structured entity data for identity resolution.
    """

    role = ProviderRole.IDENTITY

    def __init__(
        self,
        sparql_endpoint: str = "https://query.wikidata.org/sparql",
        api_endpoint: str = "https://www.wikidata.org/w/api.php",
        timeout: float = 15.0,
        user_agent: str = "NORAResearchBot/1.0 (+https://github.com/tmakiriyado1-arch/atis-node-builder)",
    ) -> None:
        self.sparql_endpoint = sparql_endpoint
        self.api_endpoint = api_endpoint
        self.timeout = timeout
        self.headers = {"User-Agent": user_agent, "Accept": "application/json"}

    async def search(
        self,
        query: str,
        max_results: int = 10,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Search Wikidata for entity information.
        
        Args:
            query: The entity name to search for
            max_results: Maximum number of results to return
            context: Optional context for query expansion
            
        Returns:
            List of result dictionaries with entity information
        """
        cleaned_query = (query or "").strip()
        if not cleaned_query:
            return []

        logger.info(f"[WIKIDATA] Searching for '{cleaned_query[:100]}'")
        
        # Generate query variants for better matching
        query_variants = self._generate_query_variants(cleaned_query, context)
        
        # Try each variant
        results = []
        for variant in query_variants:
            if len(results) >= max_results:
                break
            
            # Try to find the entity by label search
            entity_id = await self._find_entity_by_label(variant)
            
            if entity_id:
                # Get full entity information
                entity_data = await self._get_entity_info(entity_id)
                if entity_data:
                    result = self._format_entity_result(entity_data, cleaned_query)
                    results.append(result)
                    logger.info(f"[WIKIDATA] Found entity: {entity_id}")
        
        # If we have results, convert and return them
        if results:
            return self._to_search_results(results, cleaned_query)[:max_results]
        
        # If direct lookup fails, try SPARQL search with original query
        results = await self._sparql_search(cleaned_query, max_results)
        if results:
            logger.info(f"[WIKIDATA] SPARQL search returned {len(results)} results")
            return self._to_search_results(results, cleaned_query)[:max_results]
        
        # Try SPARQL with variants
        for variant in query_variants:
            if len(results) >= max_results:
                break
            variant_results = await self._sparql_search(variant, max_results - len(results))
            results.extend(variant_results)
        
        return self._to_search_results(results, cleaned_query)[:max_results]

    async def _find_entity_by_label(self, label: str) -> Optional[str]:
        """Find a Wikidata entity ID by its label."""
        params = {
            "action": "wbsearchentities",
            "format": "json",
            "language": "en",
            "search": label,
            "limit": 5,
        }
        
        try:
            async with httpx.AsyncClient(headers=self.headers, timeout=self.timeout) as client:
                response = await client.get(self.api_endpoint, params=params)
                response.raise_for_status()
                data = response.json()
        except Exception as e:
            logger.warning(f"[WIKIDATA] Entity search failed for '{label[:50]}': {e}")
            return None
        
        if not isinstance(data, dict):
            return None
        
        search_results = data.get("search", [])
        if not search_results:
            return None
        
        # Return the first result's ID if label matches well
        for result in search_results:
            entity_id = result.get("id")
            if entity_id and self._label_matches(result, label):
                return entity_id
        
        # Fallback: return first result's ID even if label doesn't match perfectly
        first_result = search_results[0]
        return first_result.get("id")

    async def _get_entity_info(self, entity_id: str) -> Optional[Dict[str, Any]]:
        """Get full information for a Wikidata entity."""
        params = {
            "action": "wbgetentities",
            "format": "json",
            "ids": entity_id,
            "props": "labels|descriptions|aliases|claims|sitelinks",
            "languages": "en",
        }
        
        try:
            async with httpx.AsyncClient(headers=self.headers, timeout=self.timeout) as client:
                response = await client.get(self.api_endpoint, params=params)
                response.raise_for_status()
                data = response.json()
        except Exception as e:
            logger.warning(f"[WIKIDATA] Entity info failed for {entity_id}: {e}")
            return None
        
        if not isinstance(data, dict):
            return None
        
        entities = data.get("entities", {})
        entity_data = entities.get(entity_id)
        
        # If entity not found or doesn't exist, return None
        if not entity_data or entity_data.get("missing", False):
            return None
        
        return entity_data

    async def _sparql_search(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        """Search Wikidata using SPARQL.
        
        Returns structured metadata including official website when available.
        """
        # Build a SPARQL query to find entities matching the label
        sparql_query = f"""
        SELECT DISTINCT ?item ?itemLabel ?description ?officialWebsite WHERE {{
          ?item ?label "{query}"@en .
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" . }}
          OPTIONAL {{ ?item wdt:P856 ?officialWebsite }}
          FILTER(LANG(?description) = "en")
        }}
        LIMIT {min(max_results, 10)}
        """
        
        params = {
            "query": sparql_query,
            "format": "json",
        }
        
        try:
            async with httpx.AsyncClient(headers=self.headers, timeout=self.timeout) as client:
                response = await client.get(self.sparql_endpoint, params=params)
                response.raise_for_status()
                data = response.json()
        except Exception as e:
            logger.warning(f"[WIKIDATA] SPARQL search failed for '{query[:50]}': {e}")
            return []
        
        if not isinstance(data, dict):
            return []
        
        results = []
        bindings = data.get("results", {}).get("bindings", [])
        
        for binding in bindings:
            item = binding.get("item", {})
            label = binding.get("itemLabel", {})
            description = binding.get("description", {})
            website = binding.get("officialWebsite", {})
            
            if item.get("type") == "uri":
                entity_id = item.get("value", "").split("/")[-1]
                entity_url = f"https://www.wikidata.org/wiki/{entity_id}"
                
                result = {
                    "title": label.get("value", ""),
                    "url": entity_url,
                    "snippet": description.get("value", ""),
                    "source": "wikidata",
                    "entity_id": entity_id,
                }
                
                # Add structured metadata
                metadata = {}
                website_value = website.get("value", "")
                if website_value:
                    metadata["official_website"] = website_value
                
                # Only add metadata if we have any
                if metadata:
                    result["metadata"] = metadata
                
                results.append(result)
        
        return results

    def _label_matches(self, search_result: Dict[str, Any], query: str) -> bool:
        """Check if a search result label matches the query."""
        label = search_result.get("label", "").lower()
        query_lower = query.lower()
        
        # Exact match
        if query_lower == label:
            return True
        
        # Check if query is in label (for partial matches)
        if query_lower in label:
            return True
        
        # Check aliases
        aliases = search_result.get("aliases", [])
        for alias in aliases:
            if query_lower == alias.lower() or query_lower in alias.lower():
                return True
        
        return False

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

    def _to_search_results(
        self,
        results: List[Dict[str, Any]],
        query: str,
    ) -> List[SearchResult]:
        """Convert result dicts to SearchResult format."""
        search_results = []
        for idx, result in enumerate(results):
            search_result = SearchResult(
                provider=self.__class__.__name__,
                query=query,
                page=1,
                rank=idx + 1,
                title=result.get("title", ""),
                url=result.get("url", ""),
                snippet=result.get("snippet", None),
                metadata=result.get("metadata", {}),
            )
            search_results.append(search_result)
        return search_results

    def _format_entity_result(
        self,
        entity_data: Dict[str, Any],
        query: str,
    ) -> Dict[str, Any]:
        """Format Wikidata entity information as a search result.
        
        Includes structured metadata for identity resolution and official-source discovery.
        """
        entity_id = entity_data.get("id", "")
        
        # Get labels
        labels = entity_data.get("labels", {}).get("en", {})
        title = labels.get("value", entity_id)
        
        # Get descriptions
        descriptions = entity_data.get("descriptions", {}).get("en", {})
        description = descriptions.get("value", "")
        
        # Get official website (P856)
        official_website = None
        claims = entity_data.get("claims", {})
        if "P856" in claims:
            for claim in claims["P856"]:
                if claim.get("mainsnak", {}).get("datavalue", {}).get("value"):
                    official_website = claim["mainsnak"]["datavalue"]["value"]
                    break
        
        # Get aliases
        aliases = entity_data.get("aliases", {}).get("en", [])
        alias_list = [a.get("value", "") for a in aliases if a.get("value")]
        
        # Get sitelinks (Wikipedia pages)
        sitelinks = entity_data.get("sitelinks", {})
        wikipedia_url = None
        if "enwiki" in sitelinks:
            wikipedia_url = f"https://en.wikipedia.org/wiki/{sitelinks['enwiki'].get('title', '')}"
        
        # Build result with entity_id in metadata
        result = {
            "title": title,
            "url": f"https://www.wikidata.org/wiki/{entity_id}",
            "snippet": description,
            "source": "wikidata",
        }
        
        # Add structured metadata for identity and official-source discovery
        metadata = {"entity_id": entity_id}
        
        if official_website:
            metadata["official_website"] = official_website
        
        if alias_list:
            metadata["aliases"] = alias_list
        
        # Extract country (P17) with label resolution
        if "P17" in claims:
            country_claims = claims["P17"]
            if country_claims:
                country_id = country_claims[0].get("mainsnak", {}).get("datavalue", {}).get("value", "")
                if country_id:
                    metadata["country_id"] = country_id
                    # Try to resolve country label
                    country_labels = entity_data.get("labels", {}).get("en", {})
                    # Note: country label resolution would require additional API call
                    # For now, just store the ID
        
        # Extract instance of (P31) with label resolution
        if "P31" in claims:
            instance_claims = claims["P31"]
            instance_ids = []
            for claim in instance_claims:
                instance_id = claim.get("mainsnak", {}).get("datavalue", {}).get("value", "")
                if instance_id:
                    instance_ids.append(instance_id)
            if instance_ids:
                metadata["instance_of_ids"] = instance_ids
        
        # Add Wikipedia URL if available
        if wikipedia_url:
            metadata["wikipedia_url"] = wikipedia_url
        
        # Only add metadata if we have any
        if metadata:
            result["metadata"] = metadata
        
        return result
