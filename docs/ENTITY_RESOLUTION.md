# Entity Resolution

## Overview

Entity Resolution is a foundational subsystem that resolves textual variants to **canonical entities**.

The core principle: **Entity Identity ≠ Node Existence**

Examples that must resolve to a SINGLE canonical entity:
- `ZERA`
- `Zimbabwe Energy Regulatory Authority`
- `Zimbabwe Energy Regulatory Authority (ZERA)`
- `ZERA (Zimbabwe Energy Regulatory Authority)`
- `zimbabwe energy regulatory authority` (case variations)
- `Zimbabwe  Energy   Regulatory  Authority` (whitespace variations)
- `"Zimbabwe Energy Regulatory Authority"` (quoted)

## Architecture

### 1. Normalizer

Deterministic text normalization using regex and string processing.

**Handles:**
- Case normalization (→ lowercase)
- Whitespace normalization (multiple → single)
- Punctuation removal (trailing)
- Quote normalization (" ' → ")
- Dash normalization (-, –, — → -)
- Possessive removal ('s)
- HTML entity decoding
- Unicode normalization (NFD)
- Acronym extraction and generation

**Key Methods:**
```python
from app.services.entity_resolution.normalizer import Normalizer

normalizer = Normalizer()

# Normalize to canonical form
canonical = normalizer.normalize("Zimbabwe  Energy   Regulatory Authority")
# → "zimbabwe energy regulatory authority"

# Extract acronym
acronym = normalizer.extract_acronym("Zimbabwe Energy Regulatory Authority (ZERA)")
# → "ZERA"

# Split name and acronym
name, acro = normalizer.split_name_and_acronym("ZERA (Zimbabwe Energy Regulatory Authority)")
# → ("zimbabwe energy regulatory authority", "ZERA")

# Generate acronym from multi-word name
generated = normalizer.generate_acronym("Zimbabwe Energy Regulatory Authority")
# → "ZERA"
```

### 2. Entity Registry

Authoritative store of canonical entities and their aliases.

**Data Model:**
```python
@dataclass
class CanonicalEntity:
    entity_id: str                    # ENTITY-000001
    canonical_name: str               # Authoritative name
    entity_type: Optional[str]        # "organization", "government_entity", etc.
    aliases: List[EntityAlias]        # Alternative names with provenance
    acronyms: List[str]               # Associated acronyms
    raw_variants: Set[str]            # All observed spelling variants
    resolution_confidence: float      # 0-1 confidence level
    notes: str                        # Additional metadata
    created_at: datetime
    updated_at: datetime
```

**Key Methods:**
```python
from app.services.entity_resolution.registry import EntityRegistry

registry = EntityRegistry()

# Create entity
entity = registry.create_entity(
    canonical_name="Zimbabwe Energy Regulatory Authority",
    entity_type="government_entity",
    acronyms=["ZERA"],
)

# Find by normalized name
entity_id = registry.find_by_normalized("zimbabwe energy regulatory authority")

# Find by acronym
entity_ids = registry.find_by_acronym("ZERA")

# Add alias
registry.add_alias_to_entity(
    entity_id,
    text="Zimbabwe Energy Regulator",
    normalized="zimbabwe energy regulator",
    source="source_document",
    confidence=0.9,
)

# Add acronym
registry.add_acronym_to_entity(entity_id, "ZER")
```

### 3. Entity Resolver

Resolves textual variants to canonical entities using a multi-stage pipeline.

**Resolution Pipeline:**
1. Normalize input text
2. Exact match against canonical names
3. Acronym match (direct lookup)
4. Name/acronym splitting and retry
5. Fuzzy matching (SequenceMatcher)
6. Return NEW_ENTITY if no match

**Resolution States:**
```python
class ResolutionState(str, Enum):
    RESOLVED = "RESOLVED"              # Confident match found
    POSSIBLE_MATCH = "POSSIBLE_MATCH"  # Multiple candidates or low confidence
    NEW_ENTITY = "NEW_ENTITY"          # No match found
    AMBIGUOUS = "AMBIGUOUS"            # Multiple equally likely matches
    CONFLICT = "CONFLICT"              # Conflicting information
```

**Key Methods:**
```python
from app.services.entity_resolution.resolver import EntityResolver

resolver = EntityResolver(registry, fuzzy_threshold=0.85)

# Resolve text to canonical entity
result = resolver.resolve(
    text="ZERA (Zimbabwe Energy Regulatory Authority)",
    entity_type="government_entity",
    context=None,
)

# Result contains:
# - state: ResolutionState
# - entity_id: str (if resolved)
# - canonical_name: str (if resolved)
# - confidence: float (0-1)
# - candidates: List[Tuple[entity_id, confidence]]
# - reasoning: str (explanation)

if result.state == ResolutionState.RESOLVED:
    print(f"Resolved to {result.canonical_name}")
elif result.state == ResolutionState.POSSIBLE_MATCH:
    print(f"Possible matches: {result.candidates}")
else:
    print(f"New entity: {result.reasoning}")
```

## Resolution Decision Logic

### Exact Normalized Match (Confidence: 1.0)

Input text, when normalized, exactly matches canonical name or alias.

```python
Text: "Zimbabwe  Energy   Regulatory  Authority."
Normalized: "zimbabwe energy regulatory authority"
Canonical: "zimbabwe energy regulatory authority"
→ RESOLVED (confidence 1.0)
```

### Acronym Match (Confidence: 0.95)

Single acronym lookup with no ambiguity.

```python
Text: "ZERA"
Extracted Acronym: "ZERA"
Lookup: registry.find_by_acronym("ZERA") → {"ENTITY-000001"}
→ RESOLVED (confidence 0.95)
```

### Ambiguous Acronym (State: AMBIGUOUS)

Acronym matches multiple entities.

```python
Text: "IDA"
Extracted Acronym: "IDA"
Lookup: registry.find_by_acronym("IDA") → {"ENTITY-000001", "ENTITY-000002"}
→ AMBIGUOUS (candidates=[(...), (...)])
```

### Name Component Extraction (Confidence: 0.9)

Parenthetical acronym is stripped; name is matched.

```python
Text: "Zimbabwe Energy Regulatory Authority (ZERA)"
Extracted Name: "zimbabwe energy regulatory authority"
Extracted Acronym: "ZERA"
Match Name: "zimbabwe energy regulatory authority" → "ENTITY-000001"
→ RESOLVED (confidence 0.9)
```

### Fuzzy Matching (Confidence: 0.85+)

SequenceMatcher similarity for typos or minor variations.

```python
Text: "Zimbabwe Eneregy Regulatory Authority"  # typo: "Eneregy"
Normalized: "zimbabwe eneregy regulatory authority"
Fuzzy Match: similarity = 0.92 against canonical
→ RESOLVED (confidence 0.92) if above threshold
```

### New Entity (State: NEW_ENTITY)

No match found at any stage.

```python
Text: "Some Random Organization"
Normalized: "some random organization"
No exact match, no acronym, no fuzzy match
→ NEW_ENTITY (confidence 0.0)
```

## Testing Strategy

Comprehensive test coverage in `tests/unit/`:

### test_normalization.py
- Whitespace handling
- Punctuation removal
- Quote/dash normalization
- Possessive handling
- HTML entity decoding
- Acronym extraction and generation
- Name/acronym splitting

### test_entity_resolution.py
- Exact matching (various formats)
- Case insensitivity
- Acronym resolution
- Name component extraction
- Fuzzy matching
- New entity detection
- Alias matching
- ZERA variant deduplication

### test_registry.py
- Entity creation
- Sequential ID assignment
- Stable IDs
- Entity retrieval
- Normalized name lookups
- Acronym lookups
- Alias management
- Acronym management

## Running Tests

```bash
# All tests
pytest tests/

# With coverage
pytest --cov=app tests/

# Specific test file
pytest tests/unit/test_entity_resolution.py -v

# Specific test class
pytest tests/unit/test_entity_resolution.py::TestExactMatching -v
```

## ZERA Test Case

The canonical ZERA test validates the entire resolution pipeline:

```python
def test_zera_variants_resolve_same(resolver, registry):
    """Test that ZERA variants all resolve to same entity"""
    entity = registry.create_entity(
        canonical_name="Zimbabwe Energy Regulatory Authority",
        acronyms=["ZERA"],
    )
    
    variants = [
        "ZERA",
        "Zimbabwe Energy Regulatory Authority",
        "Zimbabwe Energy Regulatory Authority (ZERA)",
        "ZERA (Zimbabwe Energy Regulatory Authority)",
        "zimbabwe energy regulatory authority",
        "ZIMBABWE ENERGY REGULATORY AUTHORITY",
    ]
    
    for variant in variants:
        result = resolver.resolve(variant)
        assert result.state == ResolutionState.RESOLVED
        assert result.entity_id == entity.entity_id
```

## Integration Points

Entity Resolution is used throughout the pipeline:

1. **Backlink Engine** — Resolve entity mentions in prose
2. **New Entity Queue** — Deduplicate discovered entities
3. **Research Engine** — Normalize research entity names
4. **Node Builder** — Resolve RITA entity names

## Future Enhancements

- PostgreSQL persistence (currently in-memory)
- Semantic matching with embeddings
- Contextual disambiguation with LLM
- Conflict resolution strategies
- Custom matching rules per entity type
- Graph-based entity linking

## Important Rules

1. **Never silently merge ambiguous entities** — Always preserve candidates and reasoning
2. **Preserve raw variants** — Never discard original text, only create normalized forms
3. **Deterministic first** — Use regex/string processing before fuzzy matching
4. **Confidence scores matter** — Track and respect confidence levels
5. **No hard deletions** — Entities can be marked inactive, not deleted
