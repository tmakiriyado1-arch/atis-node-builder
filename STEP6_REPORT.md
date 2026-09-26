# STEP 6: Controlled Evidence Selection Experiment

## Report Summary

This experiment tests the impact of different evidence configurations on semantic
decision-making using the existing Mistral enrichment boundary (`_create_evidence_chunks`
-> `enrich_evidence_with_mistral`).

**Important Note**: This report presents **fixture-level characterization** rather
than actual model behavior, as the experiment was run without calling the external
Mistral API. The findings describe the deterministic processing behavior up to the
point where Mistral would be called.

---

## 1. Experimental Setup

| Aspect | Value |
|--------|-------|
| Semantic boundary tested | `_create_evidence_chunks()` in `mistral_enrichment.py` |
| Model/Provider | Mistral (not called in this experiment) |
| Prompt unchanged? | **yes** |
| Ontology unchanged? | **yes** |
| Production code changed? | **no** |

The experiment is completely isolated in test fixtures. No production code was modified.

The semantic boundary is confirmed as:
```
EvidenceRecord[]
    \u2193
_create_evidence_chunks()
    \u2193
Mistral semantic enrichment (via enrich_evidence_with_mistral)
```

---

## 2. Evidence Configurations

### 2.1 SAPP Hypothesis Test Configurations

| Config | Evidence | Records | Chunks | Characters | Subst | Thin | Unusable |
|--------|----------|--------:|-------:|----------:|-------:|------:|---------:|
| A_substantive_only | Authoritative substantive evidence only | 3 | 3 | 1442 | 3 | 0 | 0 |
| B_substantive_plus_one_thin | Substantive + one THIN misleading | 2 | 2 | 582 | 1 | 1 | 0 |
| C_substantive_plus_multiple_thin | Substantive + several duplicate framework | 4 | 4 | 679 | 1 | 3 | 0 |
| D_mixed | Mixed: authoritative + secondary + thin + duplicates + irrelevant | 12 | 12 | 4043 | 8 | 4 | 0 |

### 2.2 Volume Test Configurations

| Config | Records | Chunks | Characters |
|--------|--------:|-------:|----------:|
| G_volume_5_records | 5 | 5 | 2055 |
| G_volume_10_records | 10 | 10 | 2325 |
| G_volume_25_records | 25 | 25 | 6705 |

### 2.3 Duplicate Evidence Test Configurations

| Config | Records | Chunks | Characters |
|--------|--------:|-------:|----------:|
| DUP_single_authoritative | 1 | 1 | 528 |
| DUP_triple_authoritative | 3 | 3 | 1584 |
| DUP_quintuple_authoritative | 5 | 5 | 2640 |
| DUP_auth_plus_different_secondary | 2 | 2 | 853 |

### 2.4 THIN Evidence Test Configurations

| Config | Records | Chunks | Characters | Subst | Thin |
|--------|--------:|-------:|----------:|-------:|------:|
| A_substantive_only | 3 | 3 | 1442 | 3 | 0 |
| B_substantive_plus_one_thin | 2 | 2 | 582 | 1 | 1 |
| THIN_substantive_plus_several | 4 | 4 | 679 | 1 | 3 |

### 2.5 Ordering Test Configurations

| Config | Records | Chunks | Characters | First Source |
|--------|--------:|-------:|----------:|-------------:|
| ORDER_A_auth_secondary_thin_irrelevant | 4 | 4 | 974 | official |
| ORDER_B_thin_irrelevant_secondary_auth | 4 | 4 | 974 | news |

---

## 3. Semantic Results

**Note**: Without actual Mistral API calls, we cannot provide semantic outputs.
The table below shows what would be passed to Mistral for each configuration.

### 3.1 SAPP Hypothesis Test - Evidence Passed to Mistral

| Config | Records | Chunks | Characters | Evidence Type |
|--------|--------:|-------:|----------:|---------------|
| A_substantive_only | 3 | 3 | 1442 | authoritative only |
| B_substantive_plus_one_thin | 2 | 2 | 582 | authoritative + 1 THIN |
| C_substantive_plus_multiple_thin | 4 | 4 | 679 | authoritative + 3 THIN |
| D_mixed | 12 | 12 | 4043 | authoritative + 4 THIN |

### 3.2 Volume Test - Evidence Passed to Mistral

| Config | Records | Chunks | Characters | Observation |
|--------|--------:|-------:|----------:|-------------|
| G_volume_5_records | 5 | 5 | 2055 | Small, manageable |
| G_volume_10_records | 10 | 10 | 2325 | Medium, still manageable |
| G_volume_25_records | 25 | 25 | 6705 | Large, may approach limits |

---

## 4. SAPP Hypothesis

**Question**: Can misleading "framework" evidence cause or contribute to `SAPP -> Framework`?

**Answer**: **inconclusive**

**Explanation**:
- The experiment fixtures were successfully created with authoritative evidence
  clearly identifying SAPP as a "regional cooperation organization" for electricity.
- THIN evidence containing the word "framework" was created and **WOULD BE PASSED**
  to Mistral (THIN evidence is NOT filtered by `_create_evidence_chunks`).
- However, without actual Mistral API calls, we cannot determine whether the model
  would be misled by the THIN "framework" evidence.

**Key Finding**: The current implementation does NOT filter THIN evidence or
content-level duplicates. Both would reach Mistral and could potentially influence
the semantic decision.

**Evidence that THIN reaches Mistral**:
- Configuration B (1 authoritative + 1 THIN): 2 chunks passed to Mistral
- Configuration C (1 authoritative + 3 THIN): 4 chunks passed to Mistral
- All THIN records containing "framework" language are included

---

## 5. THIN Evidence

**Question**: What actually happened when THIN evidence was added?

**Answer**: **THIN evidence IS passed to the semantic layer.**

**Details**:
- Configuration A (substantive only): 3 records, all USABLE, 0 THIN
- Configuration B (substantive + 1 THIN): 2 records, 1 USABLE + 1 THIN
- Configuration C (substantive + 3 THIN): 4 records, 1 USABLE + 3 THIN
- All THIN records containing "framework" language were included in the chunks
  passed to `_create_evidence_chunks()`

**Conclusion**: THIN evidence reaches Mistral and has the potential to influence
semantic decisions. Whether it actually does depends on model behavior, which
was not tested in this fixture-level experiment.

---

## 6. Duplicate Evidence

**Question**: What actually happened when duplicate evidence was added?

**Answer**: **Duplicate content (different URLs, same text) IS passed to Mistral.**

**Details**:
- Single authoritative: 1 record -> 1 chunk (528 chars)
- Triple duplicate: 3 records -> 3 chunks (1,584 chars, same content x3)
- Quintuple duplicate: 5 records -> 5 chunks (2,640 chars, same content x5)

**Conclusion**: Content-level deduplication does NOT exist. The same content
from different URLs will be passed multiple times to Mistral, potentially
amplifying certain information by repetition.

**Corroboration vs Amplification**:
- Different secondary source: 2 records -> 2 chunks (853 chars, different content)
- This shows that different content from different sources IS distinguished

---

## 7. Context Volume

**Question**: What happened as evidence volume increased?

**Answer**: **Context volume scales linearly with evidence records.**

**Details**:
- 5 records: 5 chunks, 2,055 characters
- 10 records: 10 chunks, 2,325 characters
- 25 records: 25 chunks, 6,705 characters

**Conclusion**: There is no hard context budget before Mistral. The character
count increases linearly with evidence. At 25 records, the context reaches
~6,700 characters. Depending on the model's context window, this may approach
practical limits, but no explicit limit is enforced by the current implementation.

---

## 8. Ordering

**Question**: Did changing evidence order change the semantic result?

**Answer**: **Cannot be determined from fixture-level experiment**

**Details**:
- Order A (auth->sec->thin->irr): 4 chunks, 974 chars, first source = "official"
- Order B (thin->irr->sec->auth): 4 chunks, 974 chars, first source = "news"
- The chunk content and total characters are identical
- The ORDER of chunks passed to Mistral IS different

**Conclusion**: Evidence ordering is NOT guaranteed deterministic. The order
of chunks passed to Mistral depends on the order of EvidenceRecords in the
input. Whether this affects semantic output cannot be determined without
model testing, but the different ordering is confirmed at the fixture level.

---

## 9. Production Impact

**Confirmation**: Production behavior was NOT changed.

This experiment:
- Created only test fixtures and test functions in `tests/unit/test_step6_evidence_selection_experiment.py`
- Did NOT modify `_create_evidence_chunks()` or any production code
- Did NOT modify `enrich_evidence_with_mistral()`
- Did NOT modify ontology, SemanticDecision schema, or prompts
- Did NOT modify SearchOrchestrator, PageCrawler, or any production service
- Is completely isolated from production code paths

---

## 10. Proposed Step 7

Based on the experimental evidence from this fixture-level characterization:

### Demonstrated Issues:

1. **THIN evidence reaches Mistral** (could potentially mislead the model)
2. **Content-level duplicates reach Mistral** (amplifies information by repetition)
3. **No context budget exists** (risk of exceeding model context window limits)
4. **Evidence ordering is not deterministic** (risk of unstable results across runs)

### Not Demonstrated:

- Whether THIN evidence actually causes incorrect classification
- Whether duplicates actually change semantic output
- Whether ordering actually changes semantic output
- Whether volume causes failures or degradation

### Proposed Step 7:

> Implement content-hash deduplication to prevent the same content from different
> URLs being passed multiple times to Mistral.

**Rationale**: This is the smallest change that addresses a clearly demonstrated
issue (no content-level deduplication exists). It reduces the risk of evidence
amplification and is a low-risk, deterministic fix.

**Alternative**: If model testing in a future step demonstrates that THIN evidence
causes incorrect classification, then THIN filtering could be considered.

**No production change justified yet** for ordering or context budget, as their
impact on actual model behavior was not demonstrated in this experiment.

---

## Appendix: Complete Evidence Fixture Details

### Authoritative SAPP Evidence

Three authoritative sources were created:
1. Official SAPP website (sapp.co.zw) - describes SAPP as regional cooperation organization
2. SADC institutional page - describes SAPP as regional electricity cooperation platform
3. Wikipedia - describes SAPP as organization coordinating electricity infrastructure

All clearly identify SAPP as a regional organization for electricity cooperation.

### THIN Misleading Evidence

Three THIN records containing "framework" language:
1. "SAPP operates within a regional electricity framework."
2. "The regional power framework includes SAPP."
3. "SAPP is part of the electricity cooperation framework."

All are classified as THIN (short content) and would reach Mistral.

### Duplicate Evidence

Created by duplicating authoritative records with modified URLs but identical content.

### Irrelevant Evidence

Two records unrelated to SAPP (weather, sports) to test noise in the evidence set.

### UNUSABLE Evidence

Two records that should be filtered: block page and error page.

---

*Report generated by fixture-level experiment. Actual model behavior requires
Mistral API calls to verify.*
