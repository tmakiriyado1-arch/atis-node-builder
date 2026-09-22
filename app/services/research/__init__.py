"""Research provider abstractions and evidence normalization."""

from app.services.research.evidence import EvidenceRecord, deduplicate_evidence, normalize_search_result
from app.services.research.mistral_enrichment import enrich_evidence_with_mistral
from app.services.research.search_provider import SearchProvider
from app.services.research.search_orchestrator import (
    ResearchStatus,
    ProviderStatus,
    SearchOrchestrator,
    OrchestratorResult,
    ProviderResult,
    SearchProviderUnavailable,
    ProviderUnavailable,
)
from app.services.research.web_search import WebSearchProvider
from app.services.research.wikipedia_provider import WikipediaProvider
from app.services.research.wikidata_provider import WikidataProvider
from app.services.research.gdelt_provider import GDELTProvider
from app.services.research.direct_site_crawler import DirectSiteCrawler
from app.services.research.commoncrawl_provider import CommonCrawlProvider
from app.services.research.mozilla_provider import MozillaProvider

__all__ = [
    "EvidenceRecord",
    "SearchProvider",
    "SearchOrchestrator",
    "ResearchStatus",
    "ProviderStatus",
    "OrchestratorResult",
    "ProviderResult",
    "SearchProviderUnavailable",
    "ProviderUnavailable",
    "WebSearchProvider",
    "MozillaProvider",
    "WikipediaProvider",
    "WikidataProvider",
    "GDELTProvider",
    "DirectSiteCrawler",
    "CommonCrawlProvider",
    "deduplicate_evidence",
    "enrich_evidence_with_mistral",
    "normalize_search_result",
]
