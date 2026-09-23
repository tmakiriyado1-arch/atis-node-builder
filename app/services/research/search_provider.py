"""Search provider abstraction for NORA research."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Dict, List, Optional


class ProviderRole(str, Enum):
    """Role classification for search providers based on their purpose."""
    IDENTITY = "identity"           # Structured identity resolution (Wikidata)
    REFERENCE = "reference"         # Authoritative reference (Wikipedia)
    OFFICIAL_SOURCE = "official_source"  # Direct official site crawling
    WEB_DISCOVERY = "web_discovery"  # General web search (DuckDuckGo)
    NEWS = "news"                  # News coverage (GDELT)
    DEEP_ARCHIVE = "deep_archive"  # Historical archive (CommonCrawl)
    SECONDARY_WEB_SEARCH = "secondary_web_search"  # Backup web search (Mozilla)


@dataclass
class SearchResult:
    """Normalized search result contract for all search providers.
    
    This ensures provider-specific result formats don't leak into the orchestrator.
    Every search provider should return results that can be converted to this format.
    """
    provider: str
    query: str
    page: int = 1
    rank: int = 0
    title: str = ""
    url: str = ""
    snippet: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class SearchProvider:
    """Abstract interface for web search providers."""

    # Role classification for this provider
    role: ClassVar[ProviderRole] = ProviderRole.WEB_DISCOVERY

    async def search(
        self,
        query: str,
        max_results: int = 10,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Return structured search results with at least title, url, and snippet.
        
        Results should be convertible to SearchResult format with:
        - provider: provider name
        - query: the search query
        - page: page number (typically 1 for first page)
        - rank: result rank/position
        - title: result title
        - url: result URL
        - snippet: result snippet/description (optional)
        - metadata: provider-specific metadata
        """
        raise NotImplementedError("No search provider is configured")
