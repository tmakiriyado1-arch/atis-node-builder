"""Research services for NORA.

This module provides the Apps Script search provider for evidence collection,
semantic extraction services for structured evidence processing,
Mistral web research for primary evidence investigation,
and Leanstral research agent with tool-driven research loop.
"""
from __future__ import annotations

from app.services.research.apps_script_provider import AppsScriptSearchProvider
from app.services.research.leanstral_research_agent import (
    LeanstralResearchAgent,
    LeanstralResearchResult,
    Message,
    ResearchStatus as LeanstralResearchStatus,
    RetrievalResult,
    ToolCall,
    ToolDefinition,
    ToolResult,
)
from app.services.research.mistral_web_research import (
    EntityMatchType,
    EvidenceItem,
    EvidenceLevel,
    MistralResearchResult,
    MistralWebResearchProvider,
    RejectionReason,
    ResearchContext,
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
    "LeanstralResearchAgent",
    "LeanstralResearchResult",
    "LeanstralResearchStatus",
    "Message",
    "MistralResearchResult",
    "MistralResearchStatus",
    "MistralSemanticExtractor",
    "MistralWebResearchProvider",
    "ProviderRole",
    "RejectionReason",
    "ResearchContext",
    "ResearchDocument",
    "ResearchStatus",
    "RetrievalResult",
    "SearchProvider",
    "SearchResult",
    "SourceAssessment",
    "SourceResult",
    "ToolCall",
    "ToolDefinition",
    "ToolResult",
]
