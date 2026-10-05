"""Research services for NORA.

This module provides the Apps Script search provider for evidence collection,
and semantic extraction services for structured evidence processing.
"""
from __future__ import annotations

from app.services.research.apps_script_provider import AppsScriptSearchProvider
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
    "EvidenceType",
    "ExtractionResult",
    "MistralSemanticExtractor",
    "ProviderRole",
    "ResearchDocument",
    "SearchProvider",
    "SearchResult",
]
