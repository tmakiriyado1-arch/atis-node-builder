# ATIS Node Builder — Architecture

## Core Principle

**Entity Identity ≠ Node Existence**

An entity can exist in the ATIS ontology even if there is no Obsidian node for it. The system must resolve textual variants (e.g., `ZERA`, `Zimbabwe Energy Regulatory Authority`) to a single canonical entity identity, generate backlinks even for missing nodes, and queue undiscovered entities for future processing.

## System Overview

```
RITA Input
  ↓
Normalization & Resolution
  ↓
Research Engine (Internet + LLM)
  ↓
Entity Extraction & Resolution (Prose + Structured)
  ↓
Backlink Generation
  ↓
Canonical ATIS Row Population
  ↓
New Entity Discovery & Queue
  ↓
CSV Export + Validation Report
```

## Core Components

### 1. Entity Resolution Subsystem
- **Deterministic Normalization**: regex, case, whitespace, punctuation, Unicode
- **Alias System**: canonical name + normalized forms + acronyms + raw variants
- **Canonical Entity ID**: stable identifier independent of filename/folder
- **Decision States**: RESOLVED, POSSIBLE_MATCH, NEW_ENTITY, AMBIGUOUS, CONFLICT
- **Entity Registry**: persistent store of all known entities and aliases

### 2. Schema Registry
- Machine-readable representation of the canonical ATIS Google Sheets schema
- Field metadata: name, data type, required/optional, entity-bearing, backlinkable, etc.
- Does NOT replace or modify the existing schema
- Drives research field-by-field rather than generating generic prose

### 3. Research Engine
- Search provider interface (Internet sources, prioritizing authoritative sources)
- LLM provider interface (Mistral primary, replaceable)
- Evidence extraction: claim, source URL, publication date, confidence
- Claims are synthesized from evidence, never fabricated
- Field-driven research based on schema requirements

### 4. Backlink Engine
- Entity mention extraction from prose (summaries, descriptions, claims)
- Canonicalization of extracted mentions
- Structured field backlinking (lists, individual values)
- Summary backlinking (embedded entity references)
- Missing node detection and queue registration

### 5. Node Builder
- RITA input ingestion
- Schema-driven field research and population
- Summary generation with backlinked entities
- Structured field population with canonical backlinks
- Validation before marking complete

### 6. New Entity Queue
- First-class queue structure with full entity metadata
- Deduplication via entity resolution (not string equality)
- Recursive processing capability
- Resolution status tracking

### 7. Job Processor
- Asynchronous job-oriented architecture
- Status tracking: QUEUED, RUNNING, COMPLETED, FAILED, REVIEW_REQUIRED
- Resumable from intermediate states
- Preserves full processing ledger

## Development Phases

### Phase 1: Repository Foundation ✓
- Project structure
- Configuration management
- Logging
- Database setup
- API skeleton
- Testing framework
- CI/CD
- Documentation

### Phase 2: Schema Registry
- Import canonical ATIS CSV schema
- Build schema registry data model
- Define field metadata structure
- Create validators

### Phase 3: Entity Resolution (Priority)
- Normalization layer with regex
- Alias system
- Canonical entity ID generation
- Deterministic matching
- Fuzzy matching (secondary)
- Entity registry
- Comprehensive test suite

### Phase 4: Backlink Engine
- Entity mention extraction
- Canonicalization
- Structured field backlinking
- Summary backlinking
- Duplicate prevention

### Phase 5: Research Engine
- Search provider integration
- Evidence collection
- Claim extraction
- LLM integration
- Field mapping

### Phase 6: Node Builder
- RITA input processing
- Schema-driven research
- Field population
- Validation

### Phase 7: New Entity Queue
- Deduplication
- Queue management
- Recursive processing

### Phase 8: CSV Export
- Exact schema compliance
- Validation

### Phase 9: Web Interface
- Only after backend contracts stabilize

## Key Rules

1. **Never hallucinate ATIS data** — Only populate fields with evidence or explicit unknowns
2. **Never delete/rename ATIS fields** — Only enrich or supplement existing fields
3. **Never treat node existence as proof** — Generate backlinks for missing nodes
4. **Never create duplicate entities via fuzzy matching** — Preserve ambiguous candidates with reasoning
5. **Backlinks are graph data** — Every entity-bearing field must support them
6. **Normalization first** — Use deterministic logic before LLM assistance
7. **Evidence-backed claims** — Every synthesized value should retain its provenance

## Data Model Overview

### Canonical Entity
```
- entity_id (stable UUID)
- canonical_name
- entity_type
- aliases []
- acronyms []
- raw_observed_variants []
- resolution_confidence
- created_at
- updated_at
```

### Entity Mention (from prose/fields)
```
- text (raw)
- normalized
- context
- source_field
- source_document
- resolution_status
- resolved_entity_id
- candidates []
- confidence
```

### Research Claim
```
- claim
- source_url
- source_title
- publication_date
- collection_date
- evidence_passage
- source_type
- confidence
- field_name
- entity_id
```

### ATIS Row
```
- entity_id
- [canonical schema fields]
- [backlinked summaries]
- [backlinked entity references]
- validation_status
- research_ledger
- discovered_entities []
- processing_log
```

### Processing Job
```
- job_id
- status (QUEUED, RUNNING, COMPLETED, FAILED, REVIEW_REQUIRED)
- input_entity
- canonical_entity_id
- intermediate_state
- result
- error
- created_at
- updated_at
```

## Technology Stack

- **Language**: Python 3.11+
- **Framework**: FastAPI
- **Database**: PostgreSQL with SQLAlchemy
- **Validation**: Pydantic v2
- **Testing**: pytest
- **HTTP**: httpx (async)
- **LLM**: Mistral (pluggable provider)
- **Environment**: python-dotenv
- **Async**: asyncio

## API Overview

Endpoints will be designed around these core concepts:

```
POST   /entities                    Create/register entity
POST   /build                       Build a node (async job)
POST   /resolve                     Resolve entity identity
POST   /research                    Research an entity
GET    /jobs/{job_id}              Get job status/results
GET    /entities/{entity_id}       Get canonical entity
GET    /queue                       List new entity queue
GET    /schema                      List schema registry
GET    /health                      Health check
```

## Testing Strategy

Priority test coverage:

1. **Entity Resolution** — Normalization variants, alias resolution, fuzzy matching safety
2. **Backlink Generation** — Field backlinking, summary backlinking, duplicate prevention
3. **Schema Compliance** — Field types, required fields, CSV format
4. **Evidence Integrity** — Claim extraction, source tracking, no fabrication
5. **Entity Discovery** — Queue deduplication, recursive processing

## Important Constraints

- Entity resolution operates throughout the pipeline, not just at the end
- Schema registry is NOT a replacement ATIS schema
- Research internal model is richer than final CSV but does not replace ATIS schema
- Obsidian is downstream; folder organization is not a backend dependency
- LLM assists but does not replace deterministic logic
- Conflicts must be recorded with sources and dates, not silently resolved

---

See `ENTITY_RESOLUTION.md`, `SCHEMA.md`, `RESEARCH.md`, `BACKLINKING.md`, `QUEUE.md`, `API.md` for detailed subsystem documentation.
