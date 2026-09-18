# NORA Architecture

## 1. Purpose

NORA (Node & Ontology Retrieval Assistant) turns trusted, caller-supplied source
material into validated ATIS node records and explicitly supplied relationships.
It resolves entity identity through the existing `EntityRegistry` and
`EntityResolver`, preserves source references, and leaves unsupported or
unresolved facts unresolved.

NORA does not search the internet, call an LLM, invent ATIS fields, infer a
relationship from entity co-occurrence, or claim that an in-memory record is
durably persisted. The repository does not yet contain the canonical ATIS
Google Sheets schema or a database implementation.

## 2. Pipeline

The implemented pipeline is:

```text
SOURCE -> PARSE (caller supplies structured fields)
       -> NORMALIZE/RESOLVE (existing entity resolution)
       -> BUILD (validated generic node)
       -> VALIDATE (Pydantic contract and explicit provenance)
       -> PERSIST (process-local store only)
       -> RELATE/INDEX (explicit relationships and lookup)
```

Schema-driven parsing, external research, durable persistence, CSV export, and
asynchronous jobs remain deferred because their source contracts are not in the
repository.

## 3. Canonical data contracts

### Entity

`CanonicalEntity` in `app/services/entity_resolution/registry.py` is the single
entity identity contract. It contains an `ENTITY-000001`-style stable ID,
canonical name, optional type, aliases with source/confidence, acronyms, raw
variants, confidence, notes, and timestamps.

### Node

`ATISNode` in `app/models.py` represents a validated ATIS row candidate. It
requires a caller-supplied stable `node_id`, a resolved `entity_id`, the
canonical name copied from the registry, a free-form `fields` mapping (the
canonical ATIS field list is not present yet), and at least one
`SourceProvenance` record. No field is fabricated when it is absent from the
source.

### Relationship

`NodeRelationship` represents an explicitly supplied relation from a source
node to a target entity. It requires a non-empty relationship type and source
provenance. Relationship IDs are deterministic hashes of the endpoint, type,
and provenance references. Co-occurrence does not create a relationship.

### Backlink

Backlinks are currently rendered as Obsidian `[[Canonical Name]]` text by
`BacklinkGenerator`. The extractor returns mention, canonical name, and
confidence. It does not establish a relationship or assert node existence.

### Source/provenance

`SourceProvenance` requires a caller-supplied `source_id` and records optional
source type, URI, excerpt, and collection time. Existing `ResearchClaim` and
queue records retain their own provenance fields; they are not replaced.

### Job

No job contract is implemented. `BuildJobRequest` and `BuildJobResponse` are
legacy API models only and are not exposed as fake job endpoints. The existing
`EntityQueue` is a discovery queue, not an asynchronous job processor.

### Validation result

`ValidationResult` reports a boolean and deterministic error list. Node model
validation raises on malformed records; the API validation endpoint reports the
stored node contract without claiming schema compliance that cannot currently
be checked.

## 4. Module responsibilities

- `app/services/entity_resolution/normalizer.py`: deterministic text normalization.
- `app/services/entity_resolution/registry.py`: canonical entity storage and indexes.
- `app/services/entity_resolution/resolver.py`: deterministic entity resolution.
- `app/services/backlink/__init__.py`: mention extraction and backlink rendering.
- `app/services/queue_manager.py`: in-memory discovered-entity queue and status.
- `app/services/research_engine.py`: research result contracts; provider pipeline is deferred.
- `app/models.py`: API and validated node/relationship contracts.
- `app/services/node_builder.py`: source-to-node construction through entity resolution.
- `app/services/node_store.py`: process-local node and relationship storage.
- `app/api/entities.py`: entity resolution and registry endpoints.
- `app/api/nodes.py`: node creation, retrieval, validation, and explicit relationships.
- `app/main.py`: FastAPI application and router registration.
- `tests/`: executable contracts for implemented behavior.
