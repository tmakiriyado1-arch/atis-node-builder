# ATIS Node Builder — Research Engine

## Overview

The Research Engine gathers internet evidence about entities and synthesizes structured claims.

## Principles

1. **Evidence-backed, not fabricated** — Every claim has a source
2. **Structured output** — Claims map to ATIS fields
3. **Full provenance** — URL, title, date, passage, confidence
4. **Field-driven** — Research specific fields, not generic prose
5. **LLM as assistant** — Not a replacement for deterministic logic

## Architecture (TODO)

### SearchProvider

Interface for internet search (replaceable backend).

### LLMProvider

Interface for LLM-based claim extraction (Mistral primary).

### ResearchEngine

Orchestrates research pipeline.

## ResearchClaim

```python
@dataclass
class ResearchClaim:
    claim: str                      # The claim text
    field_name: str                 # ATIS field (e.g., "established")
    source_url: str                 # Where it came from
    evidence_passage: str           # Quote from source
    confidence: float               # 0-1 confidence
```

## Important Rules

1. **NEVER fabricate sources** — Only cite real evidence
2. **ALWAYS include evidence passage** — Full quote, not summary
3. **TRACK confidence** — Distinguish high/medium/low quality sources
4. **PREFER authoritative sources** — Government sites, official docs
5. **SKIP promotional content** — Company marketing != reliable evidence

## TODO

- [ ] Implement SearchProvider with Bing API
- [ ] Integrate Mistral for claim extraction
- [ ] Build caching layer for sources
- [ ] Create source quality scoring
