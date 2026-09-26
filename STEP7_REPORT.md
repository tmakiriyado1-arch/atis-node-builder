# STEP 7: Conservative Content-Level Evidence Deduplication

## 1. Repository Verification

### Files Inspected

| File | Function | Purpose |
|------|----------|---------|
| `app/services/research/evidence.py` | `deduplicate_evidence()` | Existing URL-level deduplication |
| `app/services/research/evidence.py` | `normalize_url()` | URL normalization |
| `app/services/research/search_orchestrator.py` | Line 452 | Calls `deduplicate_evidence()` |
| `app/services/research_engine.py` | Line 359 | Calls `deduplicate_evidence()` |
| `app/services/pipeline.py` | Line 150 | Calls `deduplicate_evidence()` |

### Verification Findings

- `deduplicate_evidence()` was the existing URL-level deduplication function
- It was called in 3 locations: SearchOrchestrator, ResearchEngine, Pipeline
- URL normalization was already implemented but NOT used as the deduplication key
- Content-level deduplication did NOT exist

---

## 2. Implementation

### Files Changed

- **`app/services/research/evidence.py`** (only file modified)

### Functions Changed

1. **`_canonicalize_content(content: str) -> str`** (NEW)
2. **`_content_fingerprint(content: str) -> str`** (NEW)
3. **`deduplicate_evidence(records: Iterable[EvidenceRecord]) -> List[EvidenceRecord]`** (MODIFIED)

### Canonicalization Behavior

`_canonicalize_content()` performs CONSERVATIVE normalization:

**Does normalize:**
- Leading/trailing whitespace → trimmed
- Multiple consecutive whitespace → single space
- Line endings (`\r\n`, `\n`, `\r`) → space

**Does NOT normalize:**
- Case (preserves uppercase/lowercase)
- Punctuation (preserves `.`, `!`, `?`, etc.)
- Words (no stopword removal)
- Any semantic content

**Documentation:** Fully documented in docstring with explicit "Does NOT" list.

### Hash Algorithm

- **Algorithm:** SHA-256
- **Encoding:** UTF-8
- **Output:** Hex digest (64 characters)
- **Library:** Python standard library `hashlib`
- **No external dependencies added**

### Deduplication Location

- **Location:** `app/services/research/evidence.py` in `deduplicate_evidence()`
- **Strategy:** Two-pass deduplication
  1. First pass: URL-level deduplication (existing behavior, now using normalized URL as key)
  2. Second pass: Content-level deduplication (new, using content fingerprint)

### Retained-Record Behavior

**Which record wins:** First record encountered (deterministic by input order)

**Provenance preservation:**
- **Queries:** All unique queries from all duplicates are accumulated
- **Entity name:** First non-empty value is retained
- **Entity ID:** First non-empty value is retained
- **Original URL:** First non-empty value is retained (limitation: cannot merge multiple distinct URLs)
- **URL:** First record's URL is retained
- **Title:** First record's title is retained
- **Source:** First record's source is retained

**Documentation:** Behavior documented in function docstring and in this report.

---

## 3. Before / After

### BEFORE

```
URL A \u2192 content X
URL B \u2192 content X
URL C \u2192 content X
\u2193
3 evidence records
```

### AFTER

```
URL A \u2192 content X
URL B \u2192 content X
URL C \u2192 content X
\u2193
1 evidence record (URL A retained, provenance merged)
```

### Additional Examples

| Input | Before | After |
|-------|--------|-------|
| 5 URLs with identical content | 5 records | 1 record |
| 3 URLs with same content + 2 URLs with different content | 5 records | 3 records |
| 2 URLs with whitespace-only differences | 2 records | 1 record |
| 2 URLs with punctuation differences | 2 records | 2 records |
| 2 URLs with case differences | 2 records | 2 records |

---

## 4. Tests

### Test Results

| Test | Result |
|------|--------|
| Identical content, different URLs | \u2713 PASSED |
| Identical content, multiple URLs (5) | \u2713 PASSED |
| Different content, different URLs | \u2713 PASSED |
| Whitespace variation | \u2713 PASSED |
| Punctuation variation | \u2713 PASSED |
| Case variation | \u2713 PASSED |
| THIN evidence preserved | \u2713 PASSED |
| UNUSABLE evidence behavior | \u2713 PASSED |
| Provenance preservation | \u2713 PASSED |
| Downstream chunk reduction | \u2713 PASSED |
| SAPP fixture regression | \u2713 PASSED |
| Step 4B tests | \u2713 PASSED |
| Step 5 tests | \u2713 PASSED |
| Step 6 tests | \u2713 PASSED |
| URL normalization tests | \u2713 PASSED |
| URL deduplication tests | \u2713 PASSED |

### Test Coverage

All 10 required test cases from the specification are covered:

1. **Identical content, different URLs** - 3 URLs → 1 record
2. **Multiple duplicates (3-5)** - 5 URLs → 1 record
3. **Different content** - All retained
4. **Whitespace variation** - Deduplicated (normalized)
5. **Punctuation difference** - NOT deduplicated (preserved)
6. **Case variation** - NOT deduplicated (preserved)
7. **THIN evidence** - Still reaches `_create_evidence_chunks()`
8. **UNUSABLE evidence** - Still filtered by `_create_evidence_chunks()` (unchanged)
9. **Provenance** - Queries accumulated, entity metadata preserved
10. **Downstream chunks** - 5 records → 1 deduped → 1 chunk

### Additional Tests

- Canonicalization whitespace normalization
- Canonicalization punctuation preservation
- Canonicalization case preservation
- Fingerprint determinism
- Fingerprint different content
- Fingerprint empty content
- Empty content records
- Snippet fallback
- URL deduplication still works

---

## 5. Semantic Impact

| Aspect | Changed? |
|--------|----------|
| SemanticDecision schema | **NO** |
| Semantic prompt | **NO** |
| Ontology | **NO** |
| Model/provider | **NO** |
| THIN behavior | **NO** |
| LLM ranking | **NO** |

**Confirmation:** No semantic behavior was changed. Only evidence deduplication was modified.

---

## 6. SAPP

**SAPP behavior:** **UNCHANGED**

**Observation:** The SAPP regression test (from Step 6 fixtures) was run and passed:
- SAPP evidence still extracts correctly
- Evidence remains substantive/usable
- Deduplication does not remove all SAPP evidence
- Provenance remains intact
- Semantic pipeline still receives valid evidence

**Important:** This step does NOT claim to fix the historical SAPP `Framework` classification. That would require:
1. Reproducing the actual misclassification with Mistral API calls
2. Demonstrating that duplicate evidence was the cause

This step only addresses the demonstrated issue that identical content from different URLs was being amplified.

---

## 7. Remaining Evidence Risks

Issues still supported by audits (from Step 5 and Step 6):

- \u2605 **THIN evidence still reaches Mistral** - Not addressed in Step 7 (by design)
- \u2605 **No total context budget** - Not addressed in Step 7
- \u2605 **Evidence ordering is not guaranteed deterministic** - Not addressed in Step 7
- \u2605 **LLM ranking still does not control semantic evidence** - Not addressed in Step 7

---

## 8. Proposed Step 8

**Recommendation:** No additional production change justified yet.

**Rationale:** 

The current evidence does not justify another production change because:

1. **THIN evidence impact unknown** - Step 6 did not call Mistral, so we don't know if THIN evidence actually causes misclassification
2. **Context budget not demonstrated as problem** - Step 6 showed linear scaling but no actual failures
3. **Ordering impact unknown** - Step 6 did not call Mistral, so we don't know if ordering affects results
4. **Content deduplication addresses demonstrated issue** - Step 6 proved identical content was amplified; Step 7 fixes this

**Next steps if issues are observed:**

- If THIN evidence is suspected of causing misclassification: Test with actual Mistral API calls using Step 6 fixtures
- If context volume becomes a problem: Add a configurable context budget
- If ordering causes instability: Implement deterministic sorting before semantic enrichment

**Current status:** The smallest demonstrated issue (content amplification) has been addressed. Other potential issues require actual model testing to justify changes.

---

## Appendix: Implementation Details

### Code Changes Summary

**Lines added:** ~70
**Lines modified:** ~5
**Files changed:** 1 (`app/services/research/evidence.py`)
**Dependencies added:** 0
**Breaking changes:** 0

### Helper Functions

```python
def _canonicalize_content(content: str) -> str:
    """Conservatively canonicalize evidence content for duplicate detection."""
    if not content:
        return ""
    content = content.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    content = re.sub(r'\s+', ' ', content)
    return content.strip()


def _content_fingerprint(content: str) -> str:
    """Generate a deterministic fingerprint for evidence content."""
    canonical = _canonicalize_content(content)
    if not canonical:
        return ""
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

### Deduplication Logic

```python
def deduplicate_evidence(records: Iterable[EvidenceRecord]) -> List[EvidenceRecord]:
    # Pass 1: URL-level deduplication with normalized URL keys
    url_deduped: Dict[str, EvidenceRecord] = {}
    for record in records:
        normalized_url = normalize_url(record.url)
        # ... merge provenance for URL duplicates
    
    # Pass 2: Content-level deduplication
    content_deduped: Dict[str, EvidenceRecord] = {}
    for record in url_deduped.values():
        content = getattr(record, 'content', None) or record.snippet or ""
        fingerprint = _content_fingerprint(content)
        # ... merge provenance for content duplicates
    
    return list(content_deduped.values())
```

---

## Commit Information

- **Commit:** `5308329`
- **Files changed:** 2
  - `app/services/research/evidence.py` (implementation)
  - `tests/unit/test_step7_content_deduplication.py` (test suite)
- **Lines added:** 702
- **Lines deleted:** 5
- **Test coverage:** 19 tests, all passing
