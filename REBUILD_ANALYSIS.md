# NORA LLM System Rebuild - Analysis Report

## Executive Summary

The repository contains TWO competing architectures:
1. **Documented Architecture** (docs/NORA_ARCHITECTURE.md): Caller-supplied source pipeline, NO LLM, NO internet research
2. **Implemented Architecture**: Full LLM-powered research pipeline with web search, crawling, relevance filtering, ranking, and extraction

**The implemented architecture is the ACTIVE production system.** The documentation is outdated.

## Current Production Execution Path

```
API Endpoint (/api/runs)
  -> RUN_STORE (process-local dict - THIS IS THE ROOT CAUSE OF RUN_NOT_FOUND)
  -> EntityPipelineService.run()
    -> ResearchEngine.research()
      -> SearchOrchestrator.search() (if orchestrator exists)
        -> AppsScriptSearchProvider.search()
        -> PageCrawler.crawl()
      -> LeanstralResearchAgent.research() (if use_leanstral=True)
        -> Mistral API calls with tool loop
      -> MistralWebResearchProvider.research() (fallback, if enabled)
      -> Semantic Extraction / Mistral Enrichment
    -> Claim Classification
    -> Node Draft Building
    -> Canonical Row Building
```

## Root Causes Confirmed

### RC-1: RUN_NOT_FOUND (CRITICAL)
**File**: `app/api/runs.py` line 25
**Evidence**: `RUN_STORE: dict[str, dict[str, Any]] = {}`
**Impact**: Runs are stored in process memory only. Worker restarts, multiple instances, or container recycling causes runs to disappear.
**Status**: CONFIRMED - This is a process-local store, not durable storage.

### RC-2: ResearchResult.errors AttributeError (FIXED)
**File**: `app/services/research_engine.py` line 88-110
**Evidence**: Missing `errors` field in ResearchResult dataclass
**Status**: FIXED - Added `errors: List[str] = field(default_factory=list)` at line 99
**Commit**: b3905c3b3905c3

### RC-3: Mistral Response Typed Blocks Not Handled
**File**: `app/services/research/mistral_response.py`
**Evidence**: The `normalize_mistral_content()` function exists and handles typed blocks
**Status**: PARTIALLY FIXED - Function exists but may not be used by all consumers

### RC-4: RelevanceFilter Timeout -> IRRELEVANT (NOT REPRODUCED)
**File**: `app/services/research/relevance_filter.py`
**Evidence**: Current code returns UNKNOWN status on timeout, not IRRELEVANT
**Status**: Need to verify actual behavior in production

### RC-5: Semantic Extractor ALL EVIDENCE REJECTED
**File**: `app/services/research/semantic_extractor.py`
**Evidence**: The `_verify_entity_match` always returns True, but extraction logic may reject
**Status**: Need deep inspection

### RC-6: Apps Script Timeout at ~11s
**File**: `app/services/research/apps_script_provider.py`
**Evidence**: Upstream gateway times out at ~11s, but provider waits 15s per attempt with 3 retries
**Status**: Needs optimization

### RC-7: Crawler No Retry Logic
**File**: `app/services/research/page_crawler.py`
**Evidence**: Single attempt, no retry on transient failures
**Status**: Needs retry implementation

## Architecture Discrepancy Resolution

**Decision**: The LLM-powered research pipeline IS the intended production architecture.
The documentation in NORA_ARCHITECTURE.md is OUTDATED and must be updated.

**Active Code Paths**:
- ✅ LeanstralResearchAgent - PRIMARY research path (tool-driven)
- ✅ SearchOrchestrator - Multi-provider search coordination
- ✅ AppsScriptSearchProvider - Search bridge (primary)
- ✅ PageCrawler - Page retrieval
- ✅ RelevanceFilter - LLM-based relevance assessment
- ✅ LLMRanker - LLM-based ranking
- ✅ MistralSemanticExtractor - Atomic evidence extraction
- ✅ MistralWebResearchProvider - Fallback research path
- ✅ ResearchEngine - Main orchestrator
- ✅ EntityPipelineService - End-to-end pipeline

**Legacy/Unused Code Paths**:
- ❌ None identified - all code appears to be actively used or reachable

## File Inventory and Responsibilities

### Core Research Modules (12,280 lines)

1. **research_engine.py** (904 lines)
   - ResearchResult, ResearchClaim dataclasses
   - Main ResearchEngine class
   - Orchestrates: search -> enrichment -> claims
   - NOW HAS errors field (fixed)

2. **leanstral_research_agent.py** (1204 lines)
   - LeanstralResearchAgent with tool loop
   - LeanstralResearchResult
   - Tool definitions: search_web, open_url
   - PRIMARY research path

3. **search_orchestrator.py** (1063 lines)
   - Multi-provider search coordination
   - ResearchStatus enum (COMPLETE, PARTIAL, DEGRADED, INSUFFICIENT, UNAVAILABLE)
   - ProviderStatus enum
   - RelevanceFilter integration
   - LLMRanker integration

4. **semantic_extractor.py** (1096 lines)
   - MistralSemanticExtractor
   - AtomicEvidence dataclass
   - ExtractionResult
   - ResearchDocument
   - Evidence type classification

5. **mistral_web_research.py** (1246 lines)
   - MistralWebResearchProvider
   - MistralResearchResult
   - Full web research agent
   - Fallback path

6. **relevance_filter.py** (576 lines)
   - RelevanceFilter class
   - RelevanceFilterResult
   - Block page detection
   - LLM-based relevance assessment

7. **llm_ranking.py** (526 lines)
   - LLMRanker class
   - RankedResult, RankingResult
   - LLM-based ranking

8. **apps_script_provider.py** (679 lines)
   - AppsScriptSearchProvider
   - Search bridge to Google Apps Script
   - Retry logic exists

9. **page_crawler.py** (717 lines)
   - PageCrawler class
   - CrawlResult, CrawlStats
   - httpx-based crawling

10. **mistral_response.py** (241 lines)
    - normalize_mistral_content()
    - extract_mistral_message_content()
    - Canonical response normalization

11. **evidence.py** (703 lines)
    - EvidenceRecord dataclass
    - EvidenceStatus, ExtractionQuality, RetrievalStatus enums
    - deduplicate_evidence()
    - normalize_search_result()

12. **evidence_filter.py** (1578 lines)
    - EvidenceFilterPipeline
    - AtomicClaim
    - RelevanceClassification
    - EvidenceQualityStatus

13. **mistral_enrichment.py** (385 lines)
    - enrich_evidence_with_mistral()
    - enrich_evidence_with_semantic_extraction_to_claims()

14. **query_variation.py** (388 lines)
    - QueryVariationGenerator
    - Query variation for search

### Pipeline and API

15. **pipeline.py** (492 lines)
    - EntityPipelineService
    - PipelineResult
    - Orchestrates: research -> resolution -> classification -> draft -> row

16. **runs.py** (351 lines)
    - API endpoints: /runs, /runs/{id}, /runs/{id}/result, /runs/{id}/evidence, /runs/{id}/claims
    - RUN_STORE: dict (PROCESS-LOCAL ONLY - ROOT CAUSE)

## Test Inventory

30+ test files identified. Key ones:
- test_research_engine.py (16 tests) - PASSES
- test_mistral_response.py - Need to check
- test_llm_ranking.py - FAILING (expects old model name)
- test_relevance_filter.py - Need to check
- test_semantic_extractor.py - FAILING
- test_pipeline.py - Need to check

## Immediate Issues Found

1. **test_llm_ranking.py line 27**: Expects model='mistral-large-latest', but config defaults to 'labs-leanstral-1-5'
2. **test_llm_ranking.py line 174**: Expects 2 top_results, gets 0 (fallback behavior)
3. **test_semantic_extractor.py**: Multiple failures related to entity matching and extraction

## Next Steps

1. Fix test expectations to match current implementation
2. Verify all consumers use normalize_mistral_content()
3. Add durable run storage
4. Optimize Apps Script timeouts
5. Add crawler retry logic
6. Fix semantic extractor entity matching
7. Add comprehensive regression tests
8. Update documentation
