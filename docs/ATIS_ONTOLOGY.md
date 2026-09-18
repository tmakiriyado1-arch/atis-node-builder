# ATIS Ontology (Evidence-Bound)

This document records the ontology that is actually present in the repository today. It intentionally excludes speculative structures that are described in the project roadmap but not implemented, such as PostgreSQL persistence, a canonical Google Sheets schema, research ingestion, or an LLM-backed claim pipeline.

## Evidence basis

The repository currently defines the real contract surface in:

- [app/models.py](../app/models.py)
- [app/services/entity_resolution/registry.py](../app/services/entity_resolution/registry.py)
- [app/services/entity_resolution/resolver.py](../app/services/entity_resolution/resolver.py)
- [app/services/node_builder.py](../app/services/node_builder.py)
- [app/services/node_store.py](../app/services/node_store.py)
- [app/services/queue_manager.py](../app/services/queue_manager.py)
- [app/services/backlink/__init__.py](../app/services/backlink/__init__.py)
- [app/services/research_engine.py](../app/services/research_engine.py)
- [docs/NORA_ARCHITECTURE.md](../docs/NORA_ARCHITECTURE.md)
- [ARCHITECTURE.md](../ARCHITECTURE.md)

The strongest evidence is that the project explicitly states the canonical ATIS schema is not present and that the current implementation is a process-local, generic node layer.

## 1. ATIS knowledge inventory

### Authoritative versus derived structures

| Category | Evidence | Status |
| --- | --- | --- |
| Canonical entity identity | `CanonicalEntity` in registry | Authoritative |
| Entity aliases and acronym variants | `EntityAlias`, `CanonicalEntity.aliases`, `acronyms`, `raw_variants` | Authoritative within the entity identity layer |
| Source provenance | `SourceProvenance` in `app/models.py` | Authoritative |
| Validated node record | `ATISNode` | Authoritative within the implemented NORA contract |
| Explicit relationship | `NodeRelationship` | Authoritative within the implemented NORA contract |
| Resolution outcome | `ResolutionResult` and `ResolutionState` | Authoritative for matching logic |
| Discovered entity queue | `QueuedEntity` and `EntityQueue` | Derived operational workflow, not ATIS source truth |
| Text backlink generation | `BacklinkGenerator` and `EntityMentionExtractor` | Derived presentation/index layer |
| Research claim extraction | `ResearchClaim`, `ResearchResult` | Deferred/placeholder, not authoritative |
| Schema registry metadata | `docs/SCHEMA.md` and `Schema Registry` description | Deferred, not implemented |
| Country/commodity/sector objects | No concrete definitions found | Not represented in current ATIS implementation |

### Distinct knowledge objects actually represented

| Object | Description | Where it exists | Required fields | Optional fields | Stable identifier | Canonical or derived | Current usage |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `CanonicalEntity` | Canonical identity for an entity discovered or resolved in ATIS | `app/services/entity_resolution/registry.py` | `entity_id`, `canonical_name` | `entity_type`, `aliases`, `acronyms`, `raw_variants`, `resolution_confidence`, `notes`, timestamps | `entity_id` (`ENTITY-000001` pattern) | Canonical | Core identity layer |
| `EntityAlias` | A normalized alias or observed variant for a canonical entity | `app/services/entity_resolution/registry.py` | `text`, `normalized`, `source` | `discovered_at`, `confidence` | No standalone stable ID; attached to canonical entity | Canonical within entity identity | Alias resolution and normalization |
| `ResolutionResult` | The result of resolving a candidate string against the registry | `app/services/entity_resolution/resolver.py` | `state`, `reasoning` | `entity_id`, `canonical_name`, `confidence`, `candidates` | No standalone stable ID | Canonical for matching logic | Resolution API and node building |
| `ResolutionState` | Enumeration of resolution decision states | `app/services/entity_resolution/registry.py` | enum value | none | Enum value | Canonical workflow contract | Explicit matching semantics |
| `SourceProvenance` | Source-backed evidence attached to a node, relationship, or value | `app/models.py` | `source_id` | `source_type`, `source_uri`, `excerpt`, `collected_at` | Source-specific ID; there is no repository-wide document ID | Canonical evidence contract | Required metadata for any asserted claim |
| `ATISNode` | A validated node candidate built from a resolved entity and caller-supplied field map | `app/models.py` | `node_id`, `entity_id`, `canonical_name`, `provenance`, `fields` | `entity_type`, `validation_status` | `node_id` | Canonical within current implementation | Validated node persistence |
| `NodeRelationship` | Explicitly asserted relationship from one node to a target entity | `app/models.py` | `source_node_id`, `target_entity_id`, `relationship_type`, `provenance` | `relationship_id` | `relationship_id` generated deterministically from endpoints + type + provenance | Canonical within current implementation | Persisted edges |
| `ValidationResult` | Deterministic validation object | `app/models.py` | `valid` | `errors` | None | Canonical validation status | Node validation endpoint |
| `QueuedEntity` | An unresolved or discovered entity stored for follow-up processing | `app/services/queue_manager.py` | `canonical_name` | `entity_type`, `aliases`, `source_node`, `source_field`, `source_context`, `confidence`, `status`, timestamps, notes | No stable queue ID; queue entry is list position + canonical name | Derived workflow state | Discovery queue |
| `EntityQueue` | In-memory queue of `QueuedEntity` items | `app/services/queue_manager.py` | `items`, `canonical_index` | none | Queue item identity is by list membership + normalized canonical name | Derived workflow state | Unresolved entity follow-up |
| `ResearchClaim` | A claim extracted from research evidence | `app/services/research_engine.py` | `claim`, `field_name`, `source_url` | `source_title`, `publication_date`, `evidence_passage`, `source_type`, `confidence`, `extraction_method`, timestamps | No stable ID | Deferred/derived, not active canonical data | Research pipeline placeholder |
| `ResearchResult` | Research result bundle for an entity | `app/services/research_engine.py` | `entity_name`, `claims`, `summary`, `sources_count`, timestamps, `status` | `error_message` | None | Deferred/derived, not active canonical data | Placeholder research contract |

### What is not represented

The repository does not currently define authoritative ATIS objects for:

- Country
- Commodity
- Sector
- Investigation
- Vault document
- Knowledge graph node type hierarchy
- Document frontmatter schema
- ATIS row schema columns
- Controlled vocabulary tables

The repository explicitly says this schema is deferred and not present. The implementation is intentionally generic and entity-centric rather than ATIS-domain-specific.

## 2. Actual relationships in current ATIS/NORA

### Explicit relationships

These are directly represented by source data or implemented code:

1. `CanonicalEntity` has aliases and acronyms.
   - Evidence: `CanonicalEntity.aliases`, `acronyms`, `raw_variants`.
   - Semantics: same identity, multiple observed names.

2. `NodeRelationship` links one node to a target entity.
   - Evidence: `NodeRelationship(source_node_id, target_entity_id, relationship_type, provenance)`.
   - Semantics: an asserted relationship from a validated node to a canonical target identity.

3. `QueuedEntity.source_node` indicates a discovery source node.
   - Evidence: `QueuedEntity.source_node` and `source_field` in `queue_manager.py`.
   - Semantics: the queue entry was discovered from a node or field context.

4. `BacklinkGenerator` renders mention-to-entity backlinks in prose.
   - Evidence: `[[Canonical Name]]` in `backlink/__init__.py`.
   - Semantics: mention resolution to canonical entity in text, not a persisted graph edge.

### Derived relationships

These are created by deterministic logic in the repository:

- Normalized text variants map to the same canonical entity.
- Acronym lookup maps acronym text to a canonical entity.
- Fuzzy matching yields similarity candidates between names and canonical entities.
- Queue deduplication groups normalized variants under one queue key.
- Backlinked summary text creates a textual reference from text to canonical entity.

### Potential or inferred relationships

These are not currently authoritative and should not become the ontology without source evidence:

- Country → commodity
- Sector → entity
- Entity → investigation membership
- Node → parent/child ontology node
- Knowledge graph transitive closure
- Entity co-occurrence implying semantic relationship

NORA must not promote these automatically.

## 3. Reconciliation with the current NORA model

### Compatible structures

- `CanonicalEntity` matches the concept of “entity identity” in the architecture.
- `ATISNode` matches the “validated node record” concept.
- `SourceProvenance` matches the requirement that every asserted fact trace back to evidence.
- `NodeRelationship` matches the explicit relationship requirement.
- `EntityQueue` matches the unresolved discovery workflow.

### Missing structures

- No actual ATIS field schema exists in code.
- No country/commodity/sector classes exist.
- No vault frontmatter contract exists.
- No durable database contract exists.
- No document-level or publication-level provenance model is implemented beyond generic `source_id` and optional URI.

### Conflicting or duplicated concepts

- `confidence` is treated as both operational resolution confidence and research claim confidence, but the repository never defines a legitimate ATIS confidence taxonomy.
- `entity_type` is an optional free-form string, not a constrained ontology.
- `ATISNode.fields` is a free-form dictionary, so the actual schema is not yet modeled.
- `BacklinkGenerator` creates textual pointers to canonical names, but those are not formal graph edges or persisted relationship records.

## 4. Canonical ontology proposal for NORA

This is the minimal ontology justified by the repository as it actually exists.

### Node type: Entity

- Identity: canonical entity identity
- Required attributes:
  - `entity_id`
  - `canonical_name`
- Optional attributes:
  - `entity_type`
  - `aliases`
  - `acronyms`
  - `raw_variants`
  - `notes`
- Provenance:
  - alias/source provenance is stored in `EntityAlias.source`
  - creation/update timestamps are present
- Validation requirements:
  - canonical name must be non-empty
  - entity IDs must be unique and stable (`ENTITY-000001` pattern)
- Allowed relationships:
  - alias_of (implied by the entity registry; not a separate stored edge type)
  - no other domain relationships are defined

### Node type: Node

- Identity: a source-backed validated node candidate
- Required attributes:
  - `node_id`
  - `entity_id`
  - `canonical_name`
  - `fields`
  - `provenance`
- Optional attributes:
  - `entity_type`
  - `validation_status`
- Provenance:
  - at least one `SourceProvenance` entry
- Validation requirements:
  - node must resolve to a registered entity
  - node_id must be non-empty
  - `fields` must be a dictionary
- Allowed relationships:
  - `source_node` to underlying entity identity
  - `explicitly_related` to target entity via `NodeRelationship`

### Node type: Relationship

- Identity: explicit edge with evidence
- Required attributes:
  - `source_node_id`
  - `target_entity_id`
  - `relationship_type`
  - `provenance`
- Optional attributes:
  - `relationship_id`
- Provenance:
  - required, each relationship must carry at least one `SourceProvenance`
- Validation requirements:
  - source node must exist
  - target entity must exist in registry
  - self-relationship is invalid
  - relationship type must be non-empty
- Allowed relationships:
  - one node to one target entity

### Node type: QueueEntry

- Identity: unresolved or discovered entity awaiting follow-up
- Required attributes:
  - `canonical_name`
- Optional attributes:
  - `entity_type`, `aliases`, `source_node`, `source_field`, `source_context`, `confidence`, `status`, timestamps, `notes`
- Provenance:
  - available through source context, not a formal source document ID contract
- Validation requirements:
  - deduplicated by normalized canonical name
- Allowed relationships:
  - discovered_from node/field context

## 5. Provenance model

The repository supports only a minimal, explicit provenance model that is definable from current code.

### Provenance fields that are actually supported

- `source_id` — required in `SourceProvenance`
- `source_type` — optional, but accepted as a source classification
- `source_uri` — optional URL or document URI
- `excerpt` — optional evidence snippet or literal passage
- `collected_at` — optional collection timestamp

### Provenance fields that are not consistently represented

The repository does not currently support a stable, authoritative representation for:

- document ID
- author or organization
- publication date
- retrieval timestamp
- source document version
- extraction location or field coordinate

The research engine defines `source_title`, `publication_date`, and `evidence_passage`, but it is a deferred placeholder and should not be adopted as a canonical model until implemented.

## 6. Confidence and status model

The repository contains numeric `confidence` values for resolution and claims, but no canonical ATIS confidence taxonomy.

### Evidence-supported practice

- `EntityResolver` uses numeric similarity and match confidence for decision-making.
- `ResearchClaim` uses numeric confidence for speculative research output.
- `EntityQueue` uses explicit states: `PENDING`, `PROCESSING`, `COMPLETED`, `SKIPPED`, `ERROR`.

### What NORA should use

NORA should not invent a numeric ATIS confidence score. It should use explicit operational states where the code already does:

- `RESOLVED`
- `POSSIBLE_MATCH`
- `NEW_ENTITY`
- `AMBIGUOUS`
- `CONFLICT`
- `PENDING`, `PROCESSING`, `COMPLETED`, `SKIPPED`, `ERROR`

These are evidence-backed workflow states. Numeric confidence remains implementation detail, not authoritative ontology.

## 7. NORA responsibility

NORA, as implemented here, owns the following:

- ingest caller-supplied source material
- normalize and resolve entity identity
- validate node construction against the current contract
- attach provenance to every asserted fact
- persist nodes and relationships in process-local memory
- record unresolved or newly discovered entities in a queue
- generate deterministic backlinks from mention text
- enforce explicit relationships only

NORA does not own:

- PostgreSQL persistence
- CSV export
- a canonical ATIS Google Sheets schema
- LLM-based research synthesis
- internet search or web retrieval
- entity catalog expansion beyond the registry model
- analyst reasoning or factual synthesis
- automatic ontology expansion from co-occurrence

## 8. Final determination

The actual ATIS knowledge model present in this repository is intentionally minimal and evidence-driven:

- a canonical entity identity layer
- a process-local node layer
- explicit source-backed relationships
- deterministic normalization and resolution states
- provenance-backed evidence
- an unresolved-entity queue

It is not yet a full ATIS domain ontology and should not be mistaken for one.
