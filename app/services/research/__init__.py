"""Research services for NORA.

This module provides the Apps Script search provider for evidence collection.
"""
from __future__ import annotations

from app.services.research.apps_script_provider import AppsScriptSearchProvider
from app.services.research.search_provider import ProviderRole, SearchProvider, SearchResult

__all__ = [
    "AppsScriptSearchProvider",
    "ProviderRole",
    "SearchProvider",
    "SearchResult",
]
