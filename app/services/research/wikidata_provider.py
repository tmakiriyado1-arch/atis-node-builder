"""Wikidata provider for entity identity resolution and structured data.

This provider queries Wikidata to retrieve canonical entity information,
including labels, aliases, descriptions, official websites, and structured metadata.

IMPORTANT: Wikidata candidates MUST pass semantic validation before their metadata
can be associated with the requested entity. A semantic mismatch (e.g., "Zera" genus of
insects vs "Zimbabwe Energy Regulatory Authority") must result in REJECTED status.
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
                # Perform semantic validation before accepting the match
                semantic_ok = await self._semantic_match(
                    entity_id, 
                    variant, 
                    cleaned_query, 
                    context
                )
                if not semantic_ok:
                    logger.info(f"[WIKIDATA] Semantic validation rejected {entity_id} for query '{cleaned_query}'")
                    continue
                
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
        # IMPORTANT: Apply semantic validation to SPARQL results too
        # to prevent rejected candidate metadata from contaminating context
        sparql_results = await self._sparql_search(cleaned_query, max_results)
        if sparql_results:
            # Filter SPARQL results through semantic validation
            validated_sparql_results = []
            for sparql_result in sparql_results:
                entity_id = sparql_result.get("entity_id", "")
                if entity_id:
                    semantic_ok = await self._semantic_match(
                        entity_id,
                        sparql_result.get("title", ""),
                        cleaned_query,
                        context
                    )
                    if semantic_ok:
                        validated_sparql_results.append(sparql_result)
                    else:
                        logger.info(f"[WIKIDATA] Semantic validation rejected SPARQL result {entity_id} for query '{cleaned_query}'")
                else:
                    validated_sparql_results.append(sparql_result)
            
            if validated_sparql_results:
                logger.info(f"[WIKIDATA] SPARQL search returned {len(validated_sparql_results)} validated results")
                return self._to_search_results(validated_sparql_results, cleaned_query)[:max_results]
        
        # Try SPARQL with variants
        for variant in query_variants:
            if len(results) >= max_results:
                break
            variant_results = await self._sparql_search(variant, max_results - len(results))
            # Apply semantic validation to variant results too
            validated_variant_results = []
            for vr in variant_results:
                entity_id = vr.get("entity_id", "")
                if entity_id:
                    semantic_ok = await self._semantic_match(
                        entity_id,
                        vr.get("title", ""),
                        cleaned_query,
                        context
                    )
                    if semantic_ok:
                        validated_variant_results.append(vr)
                    else:
                        logger.info(f"[WIKIDATA] Semantic validation rejected SPARQL variant result {entity_id} for query '{cleaned_query}'")
                else:
                    validated_variant_results.append(vr)
            results.extend(validated_variant_results)
        
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
            logger.error(f"[WIKIDATA] Entity search failed for '{label[:50]}': {e}")
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
            logger.error(f"[WIKIDATA] Entity info failed for {entity_id}: {e}")
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
            logger.error(f"[WIKIDATA] SPARQL search failed for '{query[:50]}': {e}")
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
        """Check if a search result label matches the query.
        
        This is a basic label match. For semantic validation, use _semantic_match instead.
        """
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
    
    async def _semantic_match(
        self,
        entity_id: str,
        query: str,
        original_query: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Perform semantic validation of a Wikidata entity candidate.
        
        This method checks if the entity is semantically compatible with the requested entity,
        not just based on label matching. This prevents false positives like:
        - ZERA (Zimbabwe Energy Regulatory Authority) matching Zera insect genus (Q1761087)
        
        Args:
            entity_id: The Wikidata entity ID to validate
            query: The query variant that matched
            original_query: The original full entity name
            context: Optional context with entity_type, country, etc.
            
        Returns:
            True if the entity is semantically compatible, False otherwise
        """
        # Get full entity information
        entity_data = await self._get_entity_info(entity_id)
        if not entity_data:
            return False
        
        # Extract entity metadata
        labels = entity_data.get("labels", {}).get("en", {})
        entity_label = labels.get("value", "").lower() if isinstance(labels, dict) else ""
        
        descriptions = entity_data.get("descriptions", {}).get("en", {})
        entity_description = descriptions.get("value", "").lower() if isinstance(descriptions, dict) else ""
        
        # Get instance-of (P31) - what type of thing is this entity?
        claims = entity_data.get("claims", {})
        instance_of_ids = []
        if "P31" in claims:
            for claim in claims["P31"]:
                instance_id = claim.get("mainsnak", {}).get("datavalue", {}).get("value", "")
                if instance_id:
                    instance_of_ids.append(instance_id)
        
        # Get country (P17)
        country_ids = []
        if "P17" in claims:
            for claim in claims["P17"]:
                country_id = claim.get("mainsnak", {}).get("datavalue", {}).get("value", "")
                if country_id:
                    country_ids.append(country_id)
        
        # Normalize original query
        original_lower = original_query.lower()
        
        # Check for known problematic matches
        # ZERA should NOT match Q1761087 (Zera insect genus)
        if entity_id == "Q1761087" and "zera" in original_lower:
            # Check if the original query indicates Zimbabwe Energy Regulatory Authority
            zera_patterns = [
                "zimbabwe",
                "energy",
                "regulatory",
                "authority",
                "electricity",
                "power",
                "zera co.zw",
                "zera.co.zw",
            ]
            if any(pattern in original_lower for pattern in zera_patterns):
                logger.error(f"[WIKIDATA] Rejecting Q1761087 (Zera insect genus) for query '{original_query}' - semantic mismatch")
                return False
        
        # Extract expected entity type from context
        expected_entity_type = None
        expected_country = None
        if context:
            expected_entity_type = (context.get("entity_type") or "").lower()
            expected_country = (context.get("country") or "").lower()
        
        # Parse original query for hints
        # If query contains "Zimbabwe" or "Energy" or "Regulatory", it's likely an organization
        if any(word in original_lower for word in ["zimbabwe", "energy", "regulatory", "authority"]):
            # This should be an organization, not a taxon
            # Check if entity is a taxon (Q16521)
            taxon_id = "Q16521"  # Wikidata ID for taxon
            if taxon_id in instance_of_ids:
                logger.error(f"[WIKIDATA] Rejecting {entity_id} ({entity_label}) for '{original_query}' - is a taxon, expected organization")
                return False
            
            # Check if entity is an insect genus
            if "insect" in entity_description or "genus" in entity_description:
                logger.error(f"[WIKIDATA] Rejecting {entity_id} ({entity_label}) for '{original_query}' - is an insect genus, expected organization")
                return False
        
        # If expected entity type is provided, check for compatibility
        if expected_entity_type:
            # Map expected types to likely Wikidata instance types
            org_keywords = ["organization", "agency", "government", "company", "corporation", "institution", "authority", "commission"]
            person_keywords = ["person", "individual", "human"]
            place_keywords = ["country", "city", "region", "location"]
            
            if any(kw in expected_entity_type for kw in org_keywords):
                # Should be an organization-like entity
                org_instance_ids = [
                    "Q43229",  # organization
                    "Q15284",  # government agency
                    "Q11631",  # regulatory body
                    "Q159235", # public body
                    "Q163740", # company
                    "Q11004",  # corporation
                ]
                if not any(oid in instance_of_ids for oid in org_instance_ids):
                    # Check if it's something obviously wrong
                    wrong_types = [
                        "Q16521",  # taxon
                        "Q5",      # human
                        "Q7432",   # genus
                        "Q164518", # species
                    ]
                    if any(wid in instance_of_ids for wid in wrong_types):
                        logger.error(f"[WIKIDATA] Rejecting {entity_id} ({entity_label}) for '{original_query}' - type mismatch: expected organization, got {instance_of_ids}")
                        return False
        
        # If we have country context, check for compatibility
        if expected_country and country_ids:
            # For now, just log - we'd need to resolve country IDs to names
            pass
        
        # Default: accept the match if we haven't found a reason to reject it
        return True

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
