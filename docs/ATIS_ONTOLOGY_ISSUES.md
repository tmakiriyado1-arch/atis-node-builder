# ATIS Ontology Data-Quality and Architecture Issues

This report identifies the problems visible in the current ATIS/NORA codebase and documentation. It ranks issues by severity and ties each finding to direct evidence in the repository.

## Summary

| Severity | Finding |
| --- | --- |
| CRITICAL | The repository does not contain the actual ATIS canonical schema or database contract. |
| CRITICAL | The implemented ontology is generic and does not define actual ATIS domain objects such as country, commodity, or sector. |
| HIGH | `ResearchEngine` is a placeholder; its research and claim model is not implemented. |
| HIGH | `confidence` is used as a numeric signal without a defined ATIS semantics or authoritative taxonomy. |
| MEDIUM | Backlinks are rendered as Obsidian text and are not formally persisted as graph edges. |
| MEDIUM | Queue entries may represent unresolved names without a canonical entity record. |
| LOW | Relationship vocabulary is a free string and has no controlled catalog. |
| LOW | Provenance is minimal and not yet fully aligned with a source-document identity model. |

## CRITICAL

### 1. No canonical ATIS schema is implemented

Evidence:

- [docs/SCHEMA.md](../docs/SCHEMA.md) states that the schema registry is a TODO and does not yet import the actual ATIS schema.
- [docs/NORA_ARCHITECTURE.md](../docs/NORA_ARCHITECTURE.md) explicitly says the repository does not yet contain the canonical ATIS Google Sheets schema.
- [app/models.py](../app/models.py) defines `ATISNode.fields: Dict[str, Any]`, which is intentionally generic and not schema-bound.

Impact:

- The project cannot presently distinguish actual ATIS objects from arbitrary fields.
- Any ontology derived from the repository is necessarily provisional and generic.

### 2. The repository does not define real ATIS domain objects

Evidence:

- Search of the implemented source shows no canonical `Country`, `Commodity`, `Sector`, `Investigation`, or `VaultDocument` model.
- `entity_type` is defined as an optional free-form string in [app/services/entity_resolution/registry.py](../app/services/entity_resolution/registry.py), not as a constrained ATIS taxonomy.
- The architecture documents emphasize entity identity and generic node construction, not a full ATIS domain model.

Impact:

- NORA currently models “entity” generically, not ATIS-specific domain classes.
- The ontology is capable of tracking resolved identity, but not a domain-specific hierarchy.

## HIGH

### 3. Research pipeline is not implemented

Evidence:

- [app/services/research_engine.py](../app/services/research_engine.py) contains `NotImplementedError` in `SearchProvider.search` and a deliberately failed status in `ResearchEngine.research`.
- The file states the provider contract and evidence extraction are not present.

Impact:

- `ResearchClaim` and `ResearchResult` are not active ATIS source-of-truth objects.
- Any provenance beyond the generic node contract is not yet trustworthy as a real ATIS model.

### 4. Numeric confidence lacks a real ATIS semantics

Evidence:

- The project uses numerics in `EntityResolveResponse.confidence`, `CanonicalEntity.resolution_confidence`, alias confidence, fuzzy-match candidates, and `ResearchClaim.confidence`.
- There is no ATIS-specific taxonomy or operational meaning defined in the repository.
- The architecture docs call out numeric scores as operational heuristics rather than authoritative ATIS truth.

Impact:

- Confidence is currently a matching convenience, not a domain ontology.
- It should not be mistaken for a meaningful semantic property of entities or claims.

## MEDIUM

### 5. Backlinks are text-level presentation, not durable graph assertions

Evidence:

- [app/services/backlink/__init__.py](../app/services/backlink/__init__.py) generates Obsidian-style text such as `[[Canonical Name]]`.
- `NodeRelationship` is the only explicit graph edge object, and the backlink logic does not persist a relationship record.

Impact:

- The backlink layer is derived presentation/index functionality, not a canonical ontology.
- It cannot be treated as authoritative structural knowledge.

### 6. Queue entries are discovery records, not canonical entities

Evidence:

- `QueuedEntity` in [app/services/queue_manager.py](../app/services/queue_manager.py) stores unresolved names and discovery context.
- Queue entries are deduplicated by normalized name, not by registry identity.
- A queue item can exist before a canonical entity is created or resolved.

Impact:

- The queue captures unresolved knowledge, but it is not the same as the canonical entity registry.
- It can create ambiguity when interpreting source material.

## LOW

### 7. Relationship vocabulary is unconstrained

Evidence:

- `NodeRelationship.relationship_type` is a free string in [app/models.py](../app/models.py).
- No relationship catalog or controlled vocabulary is defined in the current code.

Impact:

- Relationships can be asserted but not semantically validated against a canonical vocabulary.
- This is acceptable for an early contract, but it is not a full ontology.

### 8. Provenance is minimal and incomplete

Evidence:

- `SourceProvenance` requires only `source_id` and accepts optional `source_uri`, `excerpt`, and collection time.
- The repository does not yet define an authoritative document-ID model, source organization, or publication-date provenance structure.

Impact:

- Provenance is sufficient for explicit node and relationship evidence, but insufficient for a complete source-trace system.
- It is a minimal contract, not a comprehensive evidence model.

## Additional observations

- The repository distinguishes entity identity from node existence, which is correct and valuable, but it also means the system has not yet mapped all ATIS domain objects onto concrete model classes.
- The current code is intentionally a foundation layer, not a full ATIS ontology implementation.
- The project should not expand the ontology until the actual ATIS schema or authoritative data sources are present.
