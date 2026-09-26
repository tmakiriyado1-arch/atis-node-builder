# STEP 8: Reproduce the Historical SAPP Semantic Decision

## 1. API Availability

| Aspect | Value |
|--------|-------|
| Mistral available | **NO** |
| Model configured | mistral-large-latest |
| API errors | MISTRAL_API_KEY is empty or not configured |

**Conclusion**: External semantic model unavailable. Model-behavior experiment not executed.

---

## 2. Baseline Production Evidence

Since the Mistral API is unavailable, we cannot capture the actual production evidence
from live research. However, we can report the controlled evidence fixtures that
would be used in the experiment.

### Controlled Evidence Fixtures (for reference)

#### Authoritative SAPP Evidence (3 records)

1. **Official SAPP Website**
   - URL: `https://www.sapp.co.zw/about`
   - Source: `official`
   - Content: Describes SAPP as "a regional cooperation organization established in 1995" that "coordinates the planning, generation, transmission, and marketing of electricity"
   - Length: ~450 characters

2. **SADC Institutional Page**
   - URL: `https://www.sadc.int/sapp`
   - Source: `institutional`
   - Content: Describes SAPP as "the regional electricity cooperation platform for the Southern African Development Community"
   - Length: ~500 characters

3. **Wikipedia**
   - URL: `https://en.wikipedia.org/wiki/Southern_African_Power_Pool`
   - Source: `wikipedia`
   - Content: Describes SAPP as "an organization that coordinates the development and operation of electricity infrastructure"
   - Length: ~400 characters

#### THIN Misleading Evidence (3 records)

1. **News 1**: "SAPP operates within a regional electricity framework."
   - URL: `https://example.com/news1`
   - Source: `news`
   - Status: THIN
   - Content: 48 characters

2. **News 2**: "The regional power framework includes SAPP."
   - URL: `https://example.com/news2`
   - Source: `news`
   - Status: THIN
   - Content: 45 characters

3. **News 3**: "SAPP is part of the electricity cooperation framework."
   - URL: `https://example.com/news3`
   - Source: `news`
   - Status: THIN
   - Content: 50 characters

#### Duplicate Evidence (3 records)

- Same content as Authoritative SAPP Evidence #1
- Different URLs: `https://mirror1.example.com/sapp/about`, `https://mirror2.example.com/sapp/about`, `https://mirror3.example.com/sapp/about`
- Used for pre-Step-7 comparison

---

## 3. Baseline SemanticDecision

**Status**: Cannot be determined (Mistral API unavailable)

Without Mistral API access, we cannot capture the actual semantic output.

---

## 4. SAPP Classification

**Status**: **inconclusive**

**Reason**: Mistral API is not configured/available in this environment.

**Important**: The historical SAPP misclassification (`entity_type = Framework`) 
**cannot be reproduced or refuted** without access to the external semantic model.

---

## 5. Controlled Variants

The following variants were prepared and tested for evidence capture (without Mistral calls):

| Variant | Evidence Configuration | Records (after dedup) | Chunks | Characters | Status |
|---------|----------------------|---------------------:|-------:|----------:|--------|
| A_current_production | Authoritative (3) + THIN (3) | 6 | 6 | 1,593 | Ready |
| B_substantive_only | Authoritative (3) only | 3 | 3 | 1,442 | Ready |
| C_substantive_plus_thin | Authoritative (3) + THIN (3) | 6 | 6 | 1,593 | Ready |
| D_deduplicated | Authoritative (3) + THIN (3) + Duplicates (3) | 6 | 6 | N/A | Ready |
| D_pre_step7_with_duplicates | Same as above, NO deduplication | 9 | 9 | N/A | Ready |
| E_authoritative_only | Authoritative (1) only | 1 | 1 | ~500 | Ready |

**Note**: Character counts for D variants depend on whether deduplication is applied.
With deduplication: 6 records. Without: 9 records (3 duplicates + 6 unique).

---

## 6. Repeatability

**Status**: Not applicable (Mistral API unavailable)

Without API access, repeatability testing cannot be performed.

---

## 7. "Framework" Analysis

**Status**: Cannot be performed (Mistral API unavailable)

The controlled evidence fixtures include:

- **Authoritative evidence**: Clearly identifies SAPP as a "regional cooperation organization" and "organization that coordinates electricity infrastructure"
- **THIN evidence**: Contains the word "framework" 3 times in short snippets
- **Duplicate evidence**: Same authoritative content repeated across 3 URLs

**Hypothesis**: If the model were to classify SAPP as `Framework`, it would likely be due to:
1. The THIN evidence containing "framework" language
2. The amplification of "framework" mentions (if duplicates were not filtered)

**However**: This cannot be tested without Mistral API access.

---

## 8. Root-Cause Assessment

### Demonstrated

From Steps 5-7, we have **demonstrated** that:

1. ✅ URL-level deduplication exists and works
2. ✅ Content-level deduplication now exists (Step 7) and removes exact duplicates
3. ✅ THIN evidence reaches the semantic boundary
4. ✅ UNUSABLE evidence is filtered before semantic enrichment
5. ✅ No context budget exists
6. ✅ Evidence ordering is not deterministic
7. ✅ The semantic boundary is `_create_evidence_chunks()` → `enrich_evidence_with_mistral()`

### Plausible

The following remain **plausible hypotheses** for the historical SAPP misclassification:

1. 🔍 **THIN evidence influence**: THIN records containing "framework" may have influenced the model's classification
2. 🔍 **Duplicate amplification**: Before Step 7, identical content from different URLs may have amplified misleading signals
3. 🔍 **Prompt/ontology issue**: The semantic prompt or ontology may have allowed/encouraged `Framework` classification
4. 🔍 **Model behavior**: The model itself may have a tendency to classify regional cooperation as `Framework`

### Ruled Out

We can **rule out** the following:

1. ❌ **URL deduplication failure**: URL-level deduplication was working correctly
2. ❌ **Raw HTML fallback**: Step 4B eliminated this
3. ❌ **Content deduplication**: Step 7 now prevents exact duplicate amplification

---

## 9. Production Impact

**Confirmation**: No production semantic behavior was changed.

This step:
- Created only test fixtures and diagnostic harnesses
- Did NOT modify `enrich_evidence_with_mistral()`
- Did NOT modify `_create_evidence_chunks()`
- Did NOT modify ontology, SemanticDecision schema, or prompts
- Did NOT modify SearchOrchestrator, PageCrawler, or any production service
- Is completely isolated from production code paths

The only production change from Step 7 (content-level deduplication) remains in place
and is working correctly.

---

## 10. Proposed Step 9

**Recommendation**: No production change justified yet.

**Rationale**: 

Without access to the Mistral API, we cannot:
1. Reproduce the historical SAPP misclassification
2. Determine if THIN evidence causes the issue
3. Determine if duplicate amplification was the cause
4. Test the impact of Step 7's content deduplication on actual model behavior

**What we know**:
- Step 7 addresses a demonstrated issue (exact duplicate amplification)
- THIN evidence still reaches Mistral (by design)
- The semantic pipeline is otherwise unchanged

**Next steps (if API becomes available)**:
1. Run this Step 8 experiment with actual Mistral calls
2. Compare Variant A (current production) vs Variant B (substantive only)
3. If A produces `Framework` but B produces correct classification → evidence mixture is the problem
4. If both produce correct classification → historical corruption may have been fixed by Step 7 or other changes
5. If both produce `Framework` → need to investigate prompt/ontology/model

**Current status**: 
> No additional production change justified yet. The demonstrated issue (content amplification) has been addressed by Step 7. Other potential issues require actual model testing to justify changes.

---

## Appendix: Evidence Fixture Details

### Complete Evidence Text

#### Authoritative Evidence 1 (Official SAPP)
```
The Southern African Power Pool (SAPP) is a regional cooperation organization 
established in 1995. It coordinates the planning, generation, transmission, and 
marketing of electricity among the national electricity utilities in the Southern 
African Development Community (SADC) region. SAPP facilitates cross-border electricity 
trade and ensures reliable power supply across member countries. The organization 
operates under the auspices of the SADC Energy Sector and works to integrate the 
power systems of its member utilities.
```

#### Authoritative Evidence 2 (SADC)
```
The Southern African Power Pool (SAPP) is the regional electricity cooperation 
platform for the Southern African Development Community. It was established to 
facilitate the development of a competitive electricity market and to ensure the 
efficient utilization of energy resources across the region. SAPP member utilities 
include national power companies from Angola, Botswana, Democratic Republic of 
Congo, Lesotho, Malawi, Mozambique, Namibia, South Africa, Swaziland, Tanzania, 
Zambia, and Zimbabwe.
```

#### Authoritative Evidence 3 (Wikipedia)
```
The Southern African Power Pool (SAPP) is an organization that coordinates the 
development and operation of electricity infrastructure in Southern Africa. It is 
a cooperation of national electricity companies working together to ensure reliable 
and affordable electricity supply across the region. SAPP operates as a regional power 
pool, facilitating electricity trade and grid interconnection among its members.
```

#### THIN Evidence (all)
```
1. "SAPP operates within a regional electricity framework."
2. "The regional power framework includes SAPP."
3. "SAPP is part of the electricity cooperation framework."
```

---

## Test Results

All evidence capture tests passed:
- ✅ Variant A capture: 6 records, 6 chunks, 1,593 characters
- ✅ Variant B capture: 3 records, 3 chunks, 1,442 characters
- ✅ Variant D comparison: Deduplicated (6 records) vs Pre-Step-7 (9 records)
- ✅ Report structure validation

**Experiment harness is ready** for when Mistral API becomes available.
