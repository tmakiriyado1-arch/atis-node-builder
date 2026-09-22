"""Wikidata provider for entity identity resolution and structured data.

This provider queries Wikidata to retrieve canonical entity information,
including labels, aliases, descriptions, official websites, and structured metadata.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx

from app.services.research.search_provider import SearchProvider
from app.logging import logger


class WikidataProvider(SearchProvider):
    """Search provider for Wikidata entity information.
    
    Uses the Wikidata Query Service (WDQS) SPARQL endpoint and the Wikidata API
    to retrieve structured entity data for identity resolution.
    """

    def __init__(
        self,
        sparql_endpoint: str = "https://query.wikidata.org/sparql",
        api_endpoint: str = "https://www.wikidata.org/w/api.php",
        timeout: float = 30.0,
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
        
        # First, try to find the entity by label search
        entity_id = await self._find_entity_by_label(cleaned_query)
        
        if entity_id:
            # Get full entity information
            entity_data = await self._get_entity_info(entity_id)
            if entity_data:
                results = [self._format_entity_result(entity_data, cleaned_query)]
                logger.info(f"[WIKIDATA] Found entity: {entity_id}")
                return results[:max_results]
        
        # If direct lookup fails, try SPARQL search
        results = await self._sparql_search(cleaned_query, max_results)
        if results:
            logger.info(f"[WIKIDATA] SPARQL search returned {len(results)} results")
            return results[:max_results]
        
        return []

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
        
        # Return the first result's ID
        first_result = search_results[0]
        entity_id = first_result.get("id")
        
        # Check if the label matches well
        if entity_id and self._label_matches(first_result, label):
            return entity_id
        
        return None

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
        return entities.get(entity_id)

    async def _sparql_search(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        """Search Wikidata using SPARQL."""
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
                
                # Add official website if available
                website_value = website.get("value", "")
                if website_value:
                    result["official_website"] = website_value
                
                results.append(result)
        
        return results

    def _label_matches(self, search_result: Dict[str, Any], query: str) -> bool:
        """Check if a search result label matches the query."""
        label = search_result.get("label", "").lower()
        query_lower = query.lower()
        
        # Exact match
        if query_lower in label:
            return True
        
        # Check aliases
        aliases = search_result.get("aliases", [])
        for alias in aliases:
            if query_lower in alias.lower():
                return True
        
        return False

    def _format_entity_result(
        self,
        entity_data: Dict[str, Any],
        query: str,
    ) -> Dict[str, Any]:
        """Format Wikidata entity information as a search result."""
        entity_id = entity_data.get("id", "")
        
        # Get labels
        labels = entity_data.get("labels", {}).get("en", {})
        title = labels.get("value", entity_id)
        
        # Get descriptions
        descriptions = entity_data.get("descriptions", {}).get("en", {})
        description = descriptions.get("value", "")
        
        # Get official website
        official_website = None
        claims = entity_data.get("claims", {})
        if "P856" in claims:  # Official website property
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
        
        # Build result
        result = {
            "title": title,
            "url": f"https://www.wikidata.org/wiki/{entity_id}",
            "snippet": description,
            "source": "wikidata",
            "entity_id": entity_id,
        }
        
        # Add metadata
        if official_website:
            result["official_website"] = official_website
        if alias_list:
            result["aliases"] = alias_list
        if wikipedia_url:
            result["wikipedia_url"] = wikipedia_url
        
        # Extract country if available
        if "P17" in claims:  # Country property
            country_claims = claims["P17"]
            if country_claims:
                country_id = country_claims[0].get("mainsnak", {}).get("datavalue", {}).get("value", "")
                if country_id:
                    result["country_id"] = country_id
        
        # Extract entity type if available
        if "P31" in claims:  # Instance of property
            instance_claims = claims["P31"]
            if instance_claims:
                instance_id = instance_claims[0].get("mainsnak", {}).get("datavalue", {}).get("value", "")
                if instance_id:
                    result["entity_type_id"] = instance_id
        
        return result
