"""Research services for NORA.

This module provides various search and research providers for evidence collection.
"""
from __future__ import annotations

# Import all providers for registration
from app.services.research.wikipedia_provider import WikipediaProvider
from app.services.research.wikidata_provider import WikidataProvider
from app.services.research.direct_site_crawler import DirectSiteCrawler
from app.services.research.gdelt_provider import GDELTProvider
from app.services.research.commoncrawl_provider import CommonCrawlProvider
from app.services.research.mozilla_provider import MozillaProvider
from app.services.research.web_search import WebSearchProvider
from app.services.research.searxng_provider import SearXNGProvider
from app.services.research.searxng_manager import get_searxng_manager, SearXNGManager

__all__ = [
    "WikipediaProvider",
    "WikidataProvider",
    "DirectSiteCrawler",
    "GDELTProvider",
    "CommonCrawlProvider",
    "MozillaProvider",
    "WebSearchProvider",
    "SearXNGProvider",
    "SearXNGManager",
    "get_searxng_manager",
]
