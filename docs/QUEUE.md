# ATIS Node Builder — New Entity Queue

## Overview

The New Entity Queue collects entities discovered during processing for recursive, graph-expanding research.

## Principles

1. **Entity Resolution, Not String Equality** — Dedup via normalizer, not raw text
2. **Full Provenance** — Track where each entity came from
3. **Recursive Processing** — Process queue → discover more entities → expand queue
4. **Status Tracking** — Monitor processing progress

## QueuedEntity

```python
@dataclass
class QueuedEntity:
    canonical_name: str          # Canonical entity name
    entity_type: Optional[str]   # Hint: "organization", "person", etc.
    aliases: List[str]           # Known alternate names
    source_node: Optional[str]   # Entity that discovered this
    source_field: Optional[str]  # Field where discovered
    source_context: str          # Evidence snippet
    confidence: float            # 0-1 confidence
    status: QueueStatus          # PENDING, PROCESSING, COMPLETED, ERROR, SKIPPED
```

## Recursive Processing

```
RITA Input: "Zambian Civil Society Debt Alliance"
  ↓ Build Node → Discover
  ├→ Queue: "Ministry of Energy and Power Development"
  └→ Queue: "International Monetary Fund"

  Process Queue Item: "Ministry of Energy..."
    ↓ Build Node → Discover
    ├→ Queue: "Parliament of Zambia"
    ├→ Queue: "Energy Policy Committee"
    └→ Queue: "Neoliberal Policies"
```
