"""Multi-provider search orchestrator for production-grade evidence retrieval.

This orchestrator manages multiple search providers and ensures that failure
of any single provider does not cause pipeline failure.

Key architectural principle: Search breadth must happen BEFORE entity resolution is finalized.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, ClassVar, Dict, List, Optional, Sequence, Set, Tuple
from urllib.parse import urlparse

from app.services.research.evidence import EvidenceRecord, deduplicate_evidence, normalize_search_result, normalize_url
from app.services.research.page_crawler import CrawlResult, CrawlStats, PageCrawler
from app.services.research.query_variation import QueryVariationGenerator, QueryVariationConfig
from app.services.research.search_provider import ProviderRole, SearchProvider, SearchResult
from app.logging import logger


class ResearchStatus(str, Enum):
    """Status of research evidence collection."""
    COMPLETE = "complete"           # All providers succeeded, enough evidence
    PARTIAL = "partial"             # Some providers failed, but enough evidence collected
    DEGRADED = "degraded"           # Limited evidence, may be incomplete
    INSUFFICIENT = "insufficient"   # Not enough evidence found from any provider
    UNAVAILABLE = "unavailable"     # All providers failed


class ProviderStatus(str, Enum):
    """Status of an individual search provider."""
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    TIMEOUT = "timeout"


@dataclass
class ProviderResult:
    """Result from a single search provider."""
    provider_name: str
    role: str
    status: ProviderStatus
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None
    query: Optional[str] = None
    raw_results: List[SearchResult] = field(default_factory=list)
    results_returned: int = 0


@dataclass
class OrchestratorResult:
    """Result from the search orchestrator."""
    status: ResearchStatus
    evidence: List[EvidenceRecord] = field(default_factory=list)
    provider_results: List[ProviderResult] = field(default_factory=list)
    providers_attempted: List[str] = field(default_factory=list)
    providers_succeeded: List[str] = field(default_factory=list)
    providers_failed: List[str] = field(default_factory=list)
    total_queries: int = 0
    error_message: Optional[str] = None
    # First-page search metrics
    search_results_total: int = 0
    unique_urls_discovered: int = 0
    urls_crawl_attempted: int = 0
    urls_crawl_succeeded: int = 0
    urls_crawl_failed: int = 0
    # Evidence metrics
    evidence_records_created: int = 0
    claims_created: int = 0
    entities_discovered: int = 0
    relationships_discovered: int = 0
    # Crawl metrics
    crawl_stats: Optional[CrawlStats] = None


class SearchOrchestrator:
    """Orchestrates multiple search providers for resilient evidence retrieval.
    
    This orchestrator:
    1. Queries all configured search providers
    2. Collects first-page results from each
    3. Normalizes and deduplicates URLs while preserving provenance
    4. Crawls EVERY unique usable first-page URL
    5. Extracts page content as evidence
    6. Ensures failure of any single provider or URL does not stop the pipeline
    
    The key architectural change: search providers are for DISCOVERY, and the actual
    webpage content (from crawling discovered URLs) is the RESEARCH MATERIAL.
    """

    # Minimum number of evidence records to consider "enough"
    MIN_EVIDENCE_COUNT = 3
    
    # Minimum number of high-quality evidence records
    MIN_HIGH_QUALITY_COUNT = 2
    
    # Target number of unique URLs for sufficient evidence
    TARGET_UNIQUE_URLS = 15
    
    # Maximum number of results per provider (first page)
    FIRST_PAGE_LIMIT = 10
    
    # Maximum number of concurrent URL crawls
    MAX_CONCURRENT_CRAWLS = 5
    
    # Maximum query variations per entity
    MAX_QUERY_VARIATIONS = 8

    def __init__(
        self,
        providers: Optional[Sequence[SearchProvider]] = None,
        min_evidence: int = 3,
        min_high_quality: int = 2,
        timeout_per_provider: float = 30.0,
        max_concurrent_providers: int = 3,
        crawl_timeout: float = 15.0,
        max_concurrent_crawls: int = 5,
        page_crawler: Optional[PageCrawler] = None,
        query_variation_config: Optional[QueryVariationConfig] = None,
    ):
        """Initialize orchestrator with a list of providers.
        
        Args:
            providers: List of search providers to use
            min_evidence: Minimum evidence count to stop early
            min_high_quality: Minimum high-quality evidence count to stop early
            timeout_per_provider: Timeout for each provider
            max_concurrent_providers: Max providers to run concurrently
            crawl_timeout: Timeout for crawling individual URLs
            max_concurrent_crawls: Max URLs to crawl concurrently
            page_crawler: Optional custom PageCrawler instance
            query_variation_config: Optional configuration for query variation generation
        """
        self.providers = list(providers) if providers else []
        self.min_evidence = min_evidence
        self.min_high_quality = min_high_quality
        self.timeout_per_provider = timeout_per_provider
        self.max_concurrent_providers = max_concurrent_providers
        self._provider_timeout = timeout_per_provider
        self.crawl_timeout = crawl_timeout
        self.max_concurrent_crawls = max_concurrent_crawls
        self._page_crawler = page_crawler or PageCrawler(
            timeout=crawl_timeout,
            max_concurrent=max_concurrent_crawls,
        )
        self._crawl_failures: List[CrawlFailure] = []
        self.query_variation_generator = QueryVariationGenerator(
            query_variation_config or QueryVariationConfig(
                max_variations=MAX_QUERY_VARIATIONS,
            )
        )

    def add_provider(self, provider: SearchProvider) -> None:
        """Add a search provider to the orchestrator."""
        if provider not in self.providers:
            self.providers.append(provider)

    def remove_provider(self, provider_name: str) -> bool:
        """Remove a provider by name."""
        for i, provider in enumerate(self.providers):
            provider_name_attr = getattr(provider, '__class__', {}).__name__
            if provider_name_attr == provider_name:
                self.providers.pop(i)
                return True
        return False

    async def search(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
        max_results: int = 10,
    ) -> OrchestratorResult:
        """Search across all providers, collect first-page results, crawl all URLs, extract evidence.
        
        This is the main research method that implements the full pipeline:
        1. Query all configured search providers for first-page results
        2. Normalize and deduplicate discovered URLs
        3. Crawl EVERY unique usable first-page URL
        4. Extract page content as evidence records
        5. Preserve full provenance (search provider, rank, query, final URL)
        
        Args:
            query: The search query
            context: Optional context for query expansion and metadata propagation
            max_results: Maximum results per provider (first page limit)
            
        Returns:
            OrchestratorResult with combined evidence, crawl metrics, and status
        """
        if not self.providers:
            return OrchestratorResult(
                status=ResearchStatus.UNAVAILABLE,
                error_message="No search providers configured",
            )

        logger.info(f"[ORCHESTRATOR] Starting search for '{query[:100]}' with {len(self.providers)} providers")
        
        # Phase 1: Collect first-page results from all providers
        all_search_results: List[SearchResult] = []
        provider_results: List[ProviderResult] = []
        providers_attempted: List[str] = []
        providers_succeeded: List[str] = []
        providers_failed: List[str] = []
        total_queries = 0
        
        # Generate query variations for broader discovery
        query_variations = self.query_variation_generator.generate(
            query,
            entity_type=context.get("entity_type") if context else None,
            context=context,
            country=context.get("country") if context else None,
        )
        
        logger.info(f"[ORCHESTRATOR] Generated {len(query_variations)} query variations")
        
        # Process providers in batches to limit concurrency
        for i in range(0, len(self.providers), self.max_concurrent_providers):
            batch = self.providers[i:i + self.max_concurrent_providers]
            
            # Run batch concurrently
            # Each provider will receive all query variations
            batch_results = await asyncio.gather(
                *[self._run_provider(p, query_variations, query, context, max_results) for p in batch],
                return_exceptions=True
            )
            
            for provider, result in zip(batch, batch_results):
                provider_name = self._get_provider_name(provider)
                provider_role = self._get_provider_role(provider)
                providers_attempted.append(provider_name)
                total_queries += 1
                
                if isinstance(result, ProviderResult):
                    provider_results.append(result)
                    if result.status == ProviderStatus.SUCCESS:
                        providers_succeeded.append(provider_name)
                        
                        # Store raw results for URL discovery
                        all_search_results.extend(result.raw_results)
                        
                        # Propagate verified official_website to context for subsequent providers
                        if provider_name == "WikidataProvider":
                            for item in result.evidence:
                                # item might be a dict or a SearchResult
                                if isinstance(item, dict):
                                    metadata = item.get("metadata", {})
                                    if isinstance(metadata, dict) and "official_website" in metadata:
                                        official_website = metadata["official_website"]
                                        if context is None:
                                            context = {}
                                        if "official_website" not in context:
                                            context["official_website"] = official_website
                                            logger.info(f"[ORCHESTRATOR] Propagating official_website to context: {official_website}")
                        
                        logger.info(f"[ORCHESTRATOR] Provider {provider_name} returned {len(result.raw_results)} results")
                    else:
                        providers_failed.append(provider_name)
                        logger.warning(f"[ORCHESTRATOR] Provider {provider_name} failed: {result.error}")
                else:
                    # Exception occurred
                    providers_failed.append(provider_name)
                    provider_results.append(ProviderResult(
                        provider_name=provider_name,
                        role=provider_role,
                        status=ProviderStatus.FAILED,
                        error=str(result),
                        query=query,
                    ))
                    logger.warning(f"[ORCHESTRATOR] Provider {provider_name} raised exception: {result}")
        
        # Phase 2: Normalize, deduplicate, and merge search results with provenance
        merged_results = self._merge_and_deduplicate_results(all_search_results)
        
        search_results_total = len(all_search_results)
        unique_urls_discovered = len(merged_results)
        
        logger.info(f"[ORCHESTRATOR] Collected {search_results_total} total results, {unique_urls_discovered} unique URLs")
        
        # Phase 3: Crawl EVERY unique first-page URL
        crawl_results: List[CrawlResult] = []
        crawl_failures: List[CrawlFailure] = []
        
        if merged_results:
            # Prepare URLs and their discovery metadata
            urls_to_crawl = []
            url_to_metadata: Dict[str, DiscoveryMetadata] = {}
            
            for merged in merged_results:
                urls_to_crawl.append(merged.normalized_url)
                url_to_metadata[merged.normalized_url] = merged.discovery_metadata
            
            # Crawl all URLs with bounded concurrency
            crawl_results = await self._crawl_all_urls(urls_to_crawl, url_to_metadata, query)
            
            # Track failures
            crawl_failures = [
                CrawlFailure(url=r.url, error=r.error or "Unknown error", error_type="crawl_error")
                for r in crawl_results if not r.success
            ]
            self._crawl_failures = crawl_failures
        
        urls_crawl_attempted = len(crawl_results)
        urls_crawl_succeeded = len([r for r in crawl_results if r.success])
        urls_crawl_failed = len(crawl_failures)
        
        logger.info(f"[ORCHESTRATOR] Crawled {urls_crawl_succeeded}/{urls_crawl_attempted} URLs")
        
        # Phase 4: Convert crawl results to evidence records
        all_evidence: List[EvidenceRecord] = []
        evidence_records_created = 0
        
        for crawl_result in crawl_results:
            if not crawl_result.success or not crawl_result.content:
                continue
            
            # Get discovery metadata for this URL
            discovery_metadata = url_to_metadata.get(crawl_result.url, DiscoveryMetadata())
            
            # Create evidence record from crawled content
            evidence_record = self._create_evidence_from_crawl(
                crawl_result, query, discovery_metadata
            )
            if evidence_record:
                all_evidence.append(evidence_record)
                evidence_records_created += 1
        
        # Phase 5: Deduplicate evidence by URL
        final_evidence = deduplicate_evidence(all_evidence)
        
        # Phase 6: Determine status based on evidence quality
        status = self._determine_status(final_evidence, providers_attempted, providers_succeeded)
        
        # Build crawl stats
        crawl_stats = CrawlStats(
            urls_attempted=urls_crawl_attempted,
            urls_succeeded=urls_crawl_succeeded,
            urls_failed=urls_crawl_failed,
            failure_reasons={f.error_type: sum(1 for f in crawl_failures if f.error_type == f.error_type) 
                            for f in crawl_failures},
        )
        
        logger.info(f"[ORCHESTRATOR] Search complete: status={status}, "
                    f"evidence={len(final_evidence)}, "
                    f"succeeded={len(providers_succeeded)}, "
                    f"failed={len(providers_failed)}, "
                    f"urls_discovered={unique_urls_discovered}, "
                    f"urls_crawled={urls_crawl_succeeded}")
        
        return OrchestratorResult(
            status=status,
            evidence=final_evidence,
            provider_results=provider_results,
            providers_attempted=providers_attempted,
            providers_succeeded=providers_succeeded,
            providers_failed=providers_failed,
            total_queries=total_queries,
            search_results_total=search_results_total,
            unique_urls_discovered=unique_urls_discovered,
            urls_crawl_attempted=urls_crawl_attempted,
            urls_crawl_succeeded=urls_crawl_succeeded,
            urls_crawl_failed=urls_crawl_failed,
            evidence_records_created=evidence_records_created,
            claims_created=0,
            entities_discovered=0,
            relationships_discovered=0,
            crawl_stats=crawl_stats,
        )

    async def _run_provider(
        self,
        provider: SearchProvider,
        query_variations: List[Any],  # List of QueryVariation or strings
        original_query: str,
        context: Optional[Dict[str, Any]],
        max_results: int,
    ) -> ProviderResult:
        """Run a single provider with timeout and convert results to SearchResult format.
        
        Each provider receives all query variations to execute.
        """
        provider_name = self._get_provider_name(provider)
        provider_role = self._get_provider_role(provider)
        
        try:
            # Extract query strings from variations
            if query_variations and hasattr(query_variations[0], 'query'):
                queries = [v.query for v in query_variations]
            else:
                queries = list(query_variations)
            
            # Apply timeout
            evidence = await asyncio.wait_for(
                provider.search(queries, max_results=max_results, context=context),
                timeout=self._provider_timeout,
            )
            
            # Validate evidence
            if not isinstance(evidence, list):
                evidence = []
            
            # Convert provider-specific results to normalized SearchResult format
            raw_results: List[SearchResult] = []
            for idx, item in enumerate(evidence):
                if isinstance(item, dict):
                    search_result = SearchResult(
                        provider=provider_name,
                        query=query,
                        page=1,
                        rank=idx + 1,
                        title=item.get("title", "") or "",
                        url=item.get("url", "") or "",
                        snippet=item.get("snippet", None),
                        metadata=item.get("metadata", {}),
                    )
                    raw_results.append(search_result)
                elif isinstance(item, SearchResult):
                    raw_results.append(item)
            
            return ProviderResult(
                provider_name=provider_name,
                role=provider_role,
                status=ProviderStatus.SUCCESS,
                evidence=evidence,
                query=query,
                raw_results=raw_results,
                results_returned=len(raw_results),
            )
            
        except asyncio.TimeoutError:
            logger.warning(f"[ORCHESTRATOR] Provider {provider_name} timed out after {self._provider_timeout}s")
            return ProviderResult(
                provider_name=provider_name,
                role=provider_role,
                status=ProviderStatus.TIMEOUT,
                error=f"Timeout after {self._provider_timeout}s",
                query=query,
                raw_results=[],
                results_returned=0,
            )
            
        except Exception as e:
            logger.warning(f"[ORCHESTRATOR] Provider {provider_name} failed: {e}")
            return ProviderResult(
                provider_name=provider_name,
                role=provider_role,
                status=ProviderStatus.FAILED,
                error=str(e),
                query=query,
                raw_results=[],
                results_returned=0,
            )

    def _get_provider_name(self, provider: SearchProvider) -> str:
        """Get a readable name for a provider.
        
        Checks for a 'name' attribute on the provider instance first,
        then falls back to the class name.
        """
        return getattr(provider, 'name', getattr(provider.__class__, '__name__', str(type(provider).__name__)))
    
    def _merge_and_deduplicate_results(
        self,
        all_results: List[SearchResult],
    ) -> List[MergedSearchResult]:
        """Merge search results from multiple providers, deduplicate by normalized URL,
        and preserve multi-provider provenance.
        
        This ensures that:
        - Each unique URL is only crawled once
        - We know which providers discovered each URL
        - We preserve rank information from each provider
        """
        # Group results by normalized URL
        url_to_results: Dict[str, List[Tuple[str, SearchResult, int]]] = {}
        
        for result in all_results:
            if not result.url:
                continue
            
            normalized = normalize_url(result.url)
            if not normalized:
                continue
            
            if normalized not in url_to_results:
                url_to_results[normalized] = []
            
            url_to_results[normalized].append((result.provider, result, result.rank))
        
        # Build merged results
        merged: List[MergedSearchResult] = []
        for normalized_url, provider_data in url_to_results.items():
            # Use the first result's title and snippet as primary
            # (or the one from the highest-ranked provider)
            primary_provider, primary_result, primary_rank = provider_data[0]
            
            # Collect all provider data
            all_provider_data = provider_data
            
            # Build discovery metadata
            discovery_metadata = DiscoveryMetadata(
                providers=[
                    {
                        "name": p,
                        "rank": r,
                    }
                    for p, _, r in all_provider_data
                ],
                query=primary_result.query,
                ranks=[r for _, _, r in all_provider_data],
                first_discovered_by=primary_provider,
            )
            
            merged_result = MergedSearchResult(
                url=primary_result.url,
                normalized_url=normalized_url,
                title=primary_result.title,
                snippet=primary_result.snippet or "",
                provider_data=all_provider_data,
                discovery_metadata=discovery_metadata,
            )
            merged.append(merged_result)
        
        return merged
    
    async def _crawl_all_urls(
        self,
        urls: List[str],
        url_to_metadata: Dict[str, DiscoveryMetadata],
        query: str,
    ) -> List[CrawlResult]:
        """Crawl all URLs with bounded concurrency.
        
        This is the critical method that ensures EVERY first-page URL is attempted.
        Failures are isolated per-URL and do not stop other crawls.
        """
        if not urls:
            return []
        
        logger.info(f"[ORCHESTRATOR] Crawling {len(urls)} unique URLs with concurrency limit {self.max_concurrent_crawls}")
        
        # Prepare discovery metadata for each URL
        metadata_map = {}
        for url in urls:
            metadata_map[url] = url_to_metadata.get(url, DiscoveryMetadata(query=query))
        
        # Crawl in batches
        all_results: List[CrawlResult] = []
        for i in range(0, len(urls), self.max_concurrent_crawls):
            batch = urls[i:i + self.max_concurrent_crawls]
            
            # Get metadata for this batch
            batch_metadata = {url: metadata_map.get(url, DiscoveryMetadata(query=query)) 
                            for url in batch}
            
            # Crawl batch concurrently
            batch_tasks = [
                self._page_crawler.crawl_url(url, self._build_crawl_metadata(url, md))
                for url, md in batch_metadata.items()
            ]
            
            batch_results = await asyncio.gather(*batch_tasks, return_exceptions=False)
            all_results.extend(batch_results)
            
            logger.info(f"[ORCHESTRATOR] Crawled batch {i//self.max_concurrent_crawls + 1}: "
                        f"{len([r for r in batch_results if r.success])} succeeded, "
                        f"{len([r for r in batch_results if not r.success])} failed")
        
        return all_results
    
    def _build_crawl_metadata(
        self,
        url: str,
        discovery_metadata: DiscoveryMetadata,
    ) -> Dict[str, Any]:
        """Build metadata dict for crawl provenance."""
        return {
            "discovery": {
                "providers": [
                    {
                        "name": p["name"],
                        "rank": p["rank"],
                    }
                    for p in discovery_metadata.providers
                ],
                "query": discovery_metadata.query,
                "ranks": discovery_metadata.ranks,
                "first_discovered_by": discovery_metadata.first_discovered_by,
            },
            "orchestrator": {
                "phase": "first_page_crawl",
            },
        }
    
    def _create_evidence_from_crawl(
        self,
        crawl_result: CrawlResult,
        query: str,
        discovery_metadata: DiscoveryMetadata,
    ) -> Optional[EvidenceRecord]:
        """Create an EvidenceRecord from a successful crawl result.
        
        This converts the crawled page content into the canonical evidence format
        used by the rest of the research pipeline.
        """
        if not crawl_result.success or not crawl_result.content:
            return None
        
        # Use final URL (after redirects) as the canonical URL
        final_url = crawl_result.final_url or crawl_result.url
        if not final_url:
            final_url = crawl_result.url
        
        # Build discovery metadata into evidence metadata
        evidence_metadata: Dict[str, Any] = {
            "discovery": {
                "providers": [
                    {
                        "name": p["name"],
                        "rank": p["rank"],
                    }
                    for p in discovery_metadata.providers
                ],
                "query": discovery_metadata.query,
                "ranks": discovery_metadata.ranks,
                "first_discovered_by": discovery_metadata.first_discovered_by,
            },
            "crawl": {
                "status_code": crawl_result.status_code,
                "content_type": crawl_result.content_type,
                "retrieved_at": crawl_result.retrieved_at.isoformat(),
                "original_url": crawl_result.url,
                "final_url": final_url,
            },
        }
        
        # Add HTTP status to metadata
        if crawl_result.status_code:
            evidence_metadata["http_status"] = crawl_result.status_code
        
        # Use crawled content as the snippet (truncated if needed)
        content = crawl_result.content
        snippet = content[:2000] if len(content) > 2000 else content
        
        # Build evidence record
        record = EvidenceRecord(
            url=final_url,
            title=crawl_result.title or "Untitled",
            snippet=snippet,
            source="page_crawl",
            query=query,
            entity_name=query,
            retrieved_at=crawl_result.retrieved_at,
            original_url=crawl_result.url,
            queries=[query],
            metadata=evidence_metadata,
        )
        
        return record

    def _get_provider_role(self, provider: SearchProvider) -> str:
        """Get the role of a provider."""
        return getattr(provider.__class__, 'role', ProviderRole.WEB_DISCOVERY).value

    def _enough_evidence(self, evidence: List[EvidenceRecord]) -> bool:
        """Check if we have enough evidence to stop, considering source diversity.
        
        Identity providers (like Wikidata) do not count toward the general evidence threshold.
        We need at least min_evidence items from non-identity providers, with source diversity.
        
        Source diversity is determined from the discovery metadata (which providers discovered the URL),
        not from the evidence source field.
        """
        # Separate identity evidence from general evidence
        identity_sources = {'wikidata', 'wikidataprovider', 'fakeidentityprovider'}
        
        identity_evidence = []
        general_evidence = []
        
        for item in evidence:
            # Check if this came from an identity provider via discovery metadata
            is_identity = False
            metadata = getattr(item, 'metadata', {})
            if isinstance(metadata, dict):
                discovery = metadata.get('discovery', {})
                if isinstance(discovery, dict):
                    providers = discovery.get('providers', [])
                    for p in providers:
                        if isinstance(p, dict):
                            pname = p.get('name', '').lower()
                            if any(identity_keyword in pname for identity_keyword in identity_sources):
                                is_identity = True
                                break
            
            # Also check source field for backward compatibility
            source = getattr(item, 'source', '').lower()
            if not is_identity and any(identity_keyword in source for identity_keyword in identity_sources):
                is_identity = True
            
            if is_identity:
                identity_evidence.append(item)
            else:
                general_evidence.append(item)
        
        # Need enough general (non-identity) evidence
        if len(general_evidence) < self.min_evidence:
            return False
        
        # Check source diversity: unique discovery sources from general evidence
        # Extract discovery sources from metadata
        unique_sources: Set[str] = set()
        for e in general_evidence:
            metadata = getattr(e, 'metadata', {})
            if isinstance(metadata, dict):
                discovery = metadata.get('discovery', {})
                if isinstance(discovery, dict):
                    providers = discovery.get('providers', [])
                    for p in providers:
                        if isinstance(p, dict):
                            pname = p.get('name', '')
                            if pname and pname not in identity_sources:
                                unique_sources.add(pname)
            
            # Fallback: use source field if no discovery metadata
            if not unique_sources:
                source = getattr(e, 'source', '')
                if source and source not in identity_sources:
                    unique_sources.add(source)
        
        # Need at least 2 distinct sources
        if len(unique_sources) < 2:
            return False
        
        return True

    def _determine_status(
        self,
        evidence: List[EvidenceRecord],
        attempted: List[str],
        succeeded: List[str],
    ) -> ResearchStatus:
        """Determine the overall research status.
        
        Uses the same role-aware logic as _enough_evidence to ensure consistency.
        """
        if not attempted:
            return ResearchStatus.UNAVAILABLE
        
        if not succeeded:
            return ResearchStatus.UNAVAILABLE
        
        # Use the same logic as _enough_evidence to check if we have enough evidence
        if self._enough_evidence(evidence):
            if len(succeeded) == len(attempted):
                return ResearchStatus.COMPLETE
            else:
                return ResearchStatus.PARTIAL
        
        # Check if we have high-quality evidence (non-identity)
        identity_sources = {'wikidata', 'wikidataprovider', 'fakeidentityprovider'}
        general_evidence = []
        
        for e in evidence:
            is_identity = False
            metadata = getattr(e, 'metadata', {})
            if isinstance(metadata, dict):
                discovery = metadata.get('discovery', {})
                if isinstance(discovery, dict):
                    providers = discovery.get('providers', [])
                    for p in providers:
                        if isinstance(p, dict):
                            pname = p.get('name', '').lower()
                            if any(identity_keyword in pname for identity_keyword in identity_sources):
                                is_identity = True
                                break
            
            source = getattr(e, 'source', '').lower()
            if not is_identity and any(identity_keyword in source for identity_keyword in identity_sources):
                is_identity = True
            
            if not is_identity:
                general_evidence.append(e)
        
        if len(general_evidence) >= self.min_high_quality:
            return ResearchStatus.PARTIAL
        
        if len(general_evidence) > 0:
            return ResearchStatus.DEGRADED
        
        return ResearchStatus.INSUFFICIENT


# =============================================================================
# Data Classes for Result Tracking
# =============================================================================

@dataclass
class DiscoveryMetadata:
    """Metadata about how a URL was discovered."""
    providers: List[Dict[str, Any]] = field(default_factory=list)
    query: str = ""
    ranks: List[int] = field(default_factory=list)
    first_discovered_by: str = ""


@dataclass
class MergedSearchResult:
    """A search result with merged provenance from multiple providers."""
    url: str
    normalized_url: str
    title: str
    snippet: str
    provider_data: List[Tuple[str, SearchResult, int]] = field(default_factory=list)
    discovery_metadata: DiscoveryMetadata = field(default_factory=DiscoveryMetadata)


@dataclass
class CrawlFailure:
    """Record of a failed crawl attempt."""
    url: str
    error: str
    error_type: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class SearchProviderUnavailable(Exception):
    """Raised when a search provider is unavailable."""
    pass


class ProviderUnavailable(Exception):
    """Raised when a search provider fails."""
    pass
