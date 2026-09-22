"""Multi-provider search orchestrator for production-grade evidence retrieval.

This orchestrator manages multiple search providers and ensures that failure
of any single provider does not cause pipeline failure.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence

from app.services.research.evidence import EvidenceRecord, deduplicate_evidence, normalize_search_result
from app.services.research.search_provider import SearchProvider
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
    status: ProviderStatus
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None
    query: Optional[str] = None


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


class SearchOrchestrator:
    """Orchestrates multiple search providers for resilient evidence retrieval.
    
    This ensures that failure of any single provider (including DuckDuckGo)
    does not cause the entire research pipeline to fail.
    """

    # Minimum number of evidence records to consider "enough"
    MIN_EVIDENCE_COUNT = 3
    
    # Minimum number of high-quality evidence records
    MIN_HIGH_QUALITY_COUNT = 2

    def __init__(
        self,
        providers: Optional[Sequence[SearchProvider]] = None,
        min_evidence: int = 3,
        min_high_quality: int = 2,
        timeout_per_provider: float = 30.0,
        max_concurrent_providers: int = 3,
    ):
        """Initialize orchestrator with a list of providers.
        
        Args:
            providers: List of search providers to use
            min_evidence: Minimum evidence count to stop early
            min_high_quality: Minimum high-quality evidence count to stop early
            timeout_per_provider: Timeout for each provider
            max_concurrent_providers: Max providers to run concurrently
        """
        self.providers = list(providers) if providers else []
        self.min_evidence = min_evidence
        self.min_high_quality = min_high_quality
        self.timeout_per_provider = timeout_per_provider
        self.max_concurrent_providers = max_concurrent_providers
        self._provider_timeout = timeout_per_provider

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
        """Search across all providers until enough evidence is collected.
        
        Args:
            query: The search query
            context: Optional context for query expansion
            max_results: Maximum results to return
            
        Returns:
            OrchestratorResult with combined evidence and status
        """
        if not self.providers:
            return OrchestratorResult(
                status=ResearchStatus.UNAVAILABLE,
                error_message="No search providers configured",
            )

        logger.info(f"[ORCHESTRATOR] Starting search for '{query[:100]}' with {len(self.providers)} providers")
        
        all_evidence: List[EvidenceRecord] = []
        provider_results: List[ProviderResult] = []
        providers_attempted: List[str] = []
        providers_succeeded: List[str] = []
        providers_failed: List[str] = []
        total_queries = 0

        # Process providers in batches to limit concurrency
        for i in range(0, len(self.providers), self.max_concurrent_providers):
            batch = self.providers[i:i + self.max_concurrent_providers]
            
            # Run batch concurrently
            batch_results = await asyncio.gather(
                *[self._run_provider(p, query, context, max_results) for p in batch],
                return_exceptions=True
            )
            
            for provider, result in zip(batch, batch_results):
                provider_name = self._get_provider_name(provider)
                providers_attempted.append(provider_name)
                total_queries += 1
                
                if isinstance(result, ProviderResult):
                    provider_results.append(result)
                    if result.status == ProviderStatus.SUCCESS:
                        providers_succeeded.append(provider_name)
                        # Convert to EvidenceRecords
                        evidence_records = []
                        for item in result.evidence:
                            record = normalize_search_result(
                                item,
                                entity_id=context.get("entity_id") if context else None,
                                entity_name=query,
                                query=result.query or query,
                                source=f"{provider_name}",
                            )
                            if record:
                                evidence_records.append(record)
                        all_evidence.extend(evidence_records)
                    else:
                        providers_failed.append(provider_name)
                        logger.warning(f"[ORCHESTRATOR] Provider {provider_name} failed: {result.error}")
                else:
                    # Exception occurred
                    providers_failed.append(provider_name)
                    provider_results.append(ProviderResult(
                        provider_name=provider_name,
                        status=ProviderStatus.FAILED,
                        error=str(result),
                        query=query,
                    ))
                    logger.warning(f"[ORCHESTRATOR] Provider {provider_name} raised exception: {result}")

            # Check if we have enough evidence
            deduped = deduplicate_evidence(all_evidence)
            if self._enough_evidence(deduped):
                logger.info(f"[ORCHESTRATOR] Enough evidence collected ({len(deduped)} records), stopping early")
                break

        # Final deduplication
        final_evidence = deduplicate_evidence(all_evidence)
        
        # Determine status
        status = self._determine_status(final_evidence, providers_attempted, providers_succeeded)
        
        logger.info(f"[ORCHESTRATOR] Search complete: status={status}, evidence={len(final_evidence)}, succeeded={len(providers_succeeded)}, failed={len(providers_failed)}")
        
        return OrchestratorResult(
            status=status,
            evidence=final_evidence,
            provider_results=provider_results,
            providers_attempted=providers_attempted,
            providers_succeeded=providers_succeeded,
            providers_failed=providers_failed,
            total_queries=total_queries,
        )

    async def _run_provider(
        self,
        provider: SearchProvider,
        query: str,
        context: Optional[Dict[str, Any]],
        max_results: int,
    ) -> ProviderResult:
        """Run a single provider with timeout."""
        provider_name = self._get_provider_name(provider)
        
        try:
            # Apply timeout
            evidence = await asyncio.wait_for(
                provider.search(query, max_results=max_results, context=context),
                timeout=self._provider_timeout,
            )
            
            # Validate evidence
            if not isinstance(evidence, list):
                evidence = []
            
            return ProviderResult(
                provider_name=provider_name,
                status=ProviderStatus.SUCCESS,
                evidence=evidence,
                query=query,
            )
            
        except asyncio.TimeoutError:
            logger.warning(f"[ORCHESTRATOR] Provider {provider_name} timed out after {self._provider_timeout}s")
            return ProviderResult(
                provider_name=provider_name,
                status=ProviderStatus.TIMEOUT,
                error=f"Timeout after {self._provider_timeout}s",
                query=query,
            )
            
        except Exception as e:
            logger.warning(f"[ORCHESTRATOR] Provider {provider_name} failed: {e}")
            return ProviderResult(
                provider_name=provider_name,
                status=ProviderStatus.FAILED,
                error=str(e),
                query=query,
            )

    def _get_provider_name(self, provider: SearchProvider) -> str:
        """Get a readable name for a provider."""
        return getattr(provider.__class__, '__name__', str(type(provider).__name__))

    def _enough_evidence(self, evidence: List[EvidenceRecord]) -> bool:
        """Check if we have enough evidence to stop."""
        if len(evidence) >= self.min_evidence:
            return True
        return False

    def _determine_status(
        self,
        evidence: List[EvidenceRecord],
        attempted: List[str],
        succeeded: List[str],
    ) -> ResearchStatus:
        """Determine the overall research status."""
        if not attempted:
            return ResearchStatus.UNAVAILABLE
        
        if not succeeded:
            return ResearchStatus.UNAVAILABLE
        
        if len(evidence) >= self.min_evidence:
            if len(succeeded) == len(attempted):
                return ResearchStatus.COMPLETE
            else:
                return ResearchStatus.PARTIAL
        
        if len(evidence) >= self.min_high_quality:
            return ResearchStatus.PARTIAL
        
        if len(evidence) > 0:
            return ResearchStatus.DEGRADED
        
        return ResearchStatus.INSUFFICIENT


class SearchProviderUnavailable(Exception):
    """Raised when a search provider is unavailable."""
    pass


class ProviderUnavailable(Exception):
    """Raised when a search provider fails."""
    pass
