"""Research provider abstractions and evidence normalization."""

from app.services.research.evidence import EvidenceRecord, deduplicate_evidence, normalize_search_result
from app.services.research.mistral_enrichment import enrich_evidence_with_mistral
from app.services.research.search_provider import SearchProvider

__all__ = [
    "EvidenceRecord",
    "SearchProvider",
    "deduplicate_evidence",
    "enrich_evidence_with_mistral",
    "normalize_search_result",
]
