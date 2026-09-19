"""Search provider abstraction for NORA research."""
from __future__ import annotations

from typing import Any, Dict, List


class SearchProvider:
    """Abstract interface for web search providers."""

    async def search(
        self,
        query: str,
        max_results: int = 10,
    ) -> List[Dict[str, Any]]:
        """Return structured search results with at least title, url, and snippet."""
        raise NotImplementedError("No search provider is configured")
