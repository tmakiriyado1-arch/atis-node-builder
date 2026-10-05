"""Research services for NORA.

This module provides the Apps Script search provider for evidence collection,
semantic extraction services for structured evidence processing,
and Mistral web research for primary evidence investigation.
"""
from __future__ import annotations

from app.services.research.apps_script_provider import AppsScriptSearchProvider
from app.services.research.mistral_web_research import (
    EntityMatchType,
    EvidenceItem,
    EvidenceLevel,
    MistralResearchResult,
    MistralWebResearchProvider,
    RejectionReason,
    ResearchContext,
    ResearchStatus as MistralResearchStatus,
    SourceAssessment,
    SourceResult,
)
from app.services.research.search_provider import ProviderRole, SearchProvider, SearchResult
from app.services.research.semantic_extractor import (
    AtomicEvidence,
    EvidenceType,
    ExtractionResult,
    ResearchDocument,
    MistralSemanticExtractor,
)

__all__ = [
    "AppsScriptSearchProvider",
    "AtomicEvidence",
    "EntityMatchType",
    "EvidenceItem",
    "EvidenceLevel",
    "EvidenceType",
    "ExtractionResult",
    "MistralResearchResult",
    "MistralResearchStatus",
    "MistralSemanticExtractor",
    "MistralWebResearchProvider",
    "ProviderRole",
    "RejectionReason",
    "ResearchContext",
    "ResearchDocument",
    "ResearchStatus",
    "SearchProvider",
    "SearchResult",
    "SourceAssessment",
    "SourceResult",
]
