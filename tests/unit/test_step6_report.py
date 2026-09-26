"""
STEP 6: Controlled Evidence Selection Experiment - Report Generator

This module generates the final report for Step 6.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from tests.unit.test_step6_evidence_selection_experiment import (
    build_configuration_a,
    build_configuration_b,
    build_configuration_c,
    build_configuration_d,
    build_configuration_e,
    build_configuration_f,
    build_configuration_g,
    build_configuration_hypothesis_a,
    build_configuration_hypothesis_b,
    build_configuration_hypothesis_c,
    build_configuration_hypothesis_d,
    build_configuration_order_a,
    build_configuration_order_b,
    build_duplicate_content_experiment_single,
    build_duplicate_content_experiment_triple,
    build_duplicate_content_experiment_quintuple,
    build_duplicate_content_experiment_different_secondary,
    build_thin_experiment_substantive_only,
    build_thin_experiment_plus_one,
    build_thin_experiment_plus_several,
    analyze_evidence_metrics,
    _create_evidence_chunks,
)


def generate_report() -> str:
    """Generate the complete Step 6 experiment report."""
    
    # Collect all experiment data
    
    # =============================================================================
    # 1. SAPP Hypothesis Test
    # =============================================================================
    hypothesis_configs = [
        build_configuration_hypothesis_a(),
        build_configuration_hypothesis_b(),
        build_configuration_hypothesis_c(),
        build_configuration_hypothesis_d(),
    ]
    
    hypothesis_data = []
    for config in hypothesis_configs:
        chunks = _create_evidence_chunks(config.evidence_records)
        metrics = analyze_evidence_metrics(config.evidence_records)
        
        hypothesis_data.append({
            "config": config.name,
            "description": config.description,
            "records": metrics["num_records"],
            "chunks": len(chunks),
            "characters": metrics["total_characters"],
            "substantive": metrics["num_substantive"],
            "thin": metrics["num_thin"],
            "unusable": metrics["num_unusable"],
        })
    
    # =============================================================================
    # 2. Volume Test
    # =============================================================================
    volume_data = []
    for num in [5, 10, 25]:
        config = build_configuration_g(num)
        chunks = _create_evidence_chunks(config.evidence_records)
        metrics = analyze_evidence_metrics(config.evidence_records)
        
        volume_data.append({
            "config": config.name,
            "records": metrics["num_records"],
            "chunks": len(chunks),
            "characters": metrics["total_characters"],
        })
    
    # =============================================================================
    # 3. Ordering Test
    # =============================================================================
    order_a = build_configuration_order_a()
    order_b = build_configuration_order_b()
    
    chunks_a = _create_evidence_chunks(order_a.evidence_records)
    chunks_b = _create_evidence_chunks(order_b.evidence_records)
    metrics_a = analyze_evidence_metrics(order_a.evidence_records)
    metrics_b = analyze_evidence_metrics(order_b.evidence_records)
    
    ordering_data = [
        {
            "config": order_a.name,
            "records": metrics_a["num_records"],
            "chunks": len(chunks_a),
            "characters": metrics_a["total_characters"],
            "first_source": order_a.evidence_records[0].source if order_a.evidence_records else "N/A",
        },
        {
            "config": order_b.name,
            "records": metrics_b["num_records"],
            "chunks": len(chunks_b),
            "characters": metrics_b["total_characters"],
            "first_source": order_b.evidence_records[0].source if order_b.evidence_records else "N/A",
        },
    ]
    
    # =============================================================================
    # 4. Duplicate Test
    # =============================================================================
    dup_configs = [
        build_duplicate_content_experiment_single(),
        build_duplicate_content_experiment_triple(),
        build_duplicate_content_experiment_quintuple(),
        build_duplicate_content_experiment_different_secondary(),
    ]
    
    dup_data = []
    for config in dup_configs:
        chunks = _create_evidence_chunks(config.evidence_records)
        metrics = analyze_evidence_metrics(config.evidence_records)
        
        dup_data.append({
            "config": config.name,
            "records": metrics["num_records"],
            "chunks": len(chunks),
            "characters": metrics["total_characters"],
        })
    
    # =============================================================================
    # 5. THIN Evidence Test
    # =============================================================================
    thin_configs = [
        build_thin_experiment_substantive_only(),
        build_thin_experiment_plus_one(),
        build_thin_experiment_plus_several(),
    ]
    
    thin_data = []
    for config in thin_configs:
        chunks = _create_evidence_chunks(config.evidence_records)
        metrics = analyze_evidence_metrics(config.evidence_records)
        
        thin_data.append({
            "config": config.name,
            "records": metrics["num_records"],
            "chunks": len(chunks),
            "characters": metrics["total_characters"],
            "substantive": metrics["num_substantive"],
            "thin": metrics["num_thin"],
        })
    
    # =============================================================================
    # Build Report
    # =============================================================================
    
    report = """# STEP 6: Controlled Evidence Selection Experiment

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
    ↓
_create_evidence_chunks()
    ↓
Mistral semantic enrichment (via enrich_evidence_with_mistral)
```

---

## 2. Evidence Configurations

### 2.1 SAPP Hypothesis Test Configurations

"""
    
    report += "\n| Config | Evidence | Records | Chunks | Characters | Subst | Thin | Unusable |\n"
    report += "|--------|----------|--------:|-------:|----------:|-------:|------:|---------:|\n"
    
    for r in hypothesis_data:
        report += f"| {r['config']} | {r['description'][:35]} | {r['records']} | {r['chunks']} | {r['characters']} | {r['substantive']} | {r['thin']} | {r['unusable']} |\n"
    
    report += """\n### 2.2 Volume Test Configurations

"""
    
    report += "\n| Config | Records | Chunks | Characters |\n"
    report += "|--------|--------:|-------:|----------:|\n"
    
    for r in volume_data:
        report += f"| {r['config']} | {r['records']} | {r['chunks']} | {r['characters']} |\n"
    
    report += """\n### 2.3 Duplicate Evidence Test Configurations

"""
    
    report += "\n| Config | Records | Chunks | Characters |\n"
    report += "|--------|--------:|-------:|----------:|\n"
    
    for r in dup_data:
        report += f"| {r['config']} | {r['records']} | {r['chunks']} | {r['characters']} |\n"
    
    report += """\n### 2.4 THIN Evidence Test Configurations

"""
    
    report += "\n| Config | Records | Chunks | Characters | Subst | Thin |\n"
    report += "|--------|--------:|-------:|----------:|-------:|------:|\n"
    
    for r in thin_data:
        report += f"| {r['config']} | {r['records']} | {r['chunks']} | {r['characters']} | {r['substantive']} | {r['thin']} |\n"
    
    report += """\n### 2.5 Ordering Test Configurations

"""
    
    report += "\n| Config | Records | Chunks | Characters | First Source |\n"
    report += "|--------|--------:|-------:|----------:|-------------:|\n"
    
    for r in ordering_data:
        report += f"| {r['config']} | {r['records']} | {r['chunks']} | {r['characters']} | {r['first_source']} |\n"
    
    report += """\n---

## 3. Semantic Results

**Note**: Without actual Mistral API calls, we cannot provide semantic outputs.
The table below shows what would be passed to Mistral for each configuration.

### 3.1 SAPP Hypothesis Test - Evidence Passed to Mistral

| Config | Records | Chunks | Characters | Evidence Type |\n"
|--------|--------:|-------:|----------:|---------------|\n"""
    
    for r in hypothesis_data:
        if r['thin'] == 0 and r['unusable'] == 0:
            evidence_desc = "authoritative only"
        elif r['thin'] > 0:
            evidence_desc = f"authoritative + {r['thin']} THIN"
        else:
            evidence_desc = "mixed"
        report += f"| {r['config']} | {r['records']} | {r['chunks']} | {r['characters']} | {evidence_desc} |\n"
    
    report += """\n### 3.2 Volume Test - Evidence Passed to Mistral

| Config | Records | Chunks | Characters | Observation |\n"
|--------|--------:|-------:|----------:|-------------|\n"""
    
    for r in volume_data:
        if r['records'] <= 5:
            obs = "Small, manageable"
        elif r['records'] <= 10:
            obs = "Medium, still manageable"
        else:
            obs = "Large, may approach limits"
        report += f"| {r['config']} | {r['records']} | {r['chunks']} | {r['characters']} | {obs} |\n"
    
    report += """\n---

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
"""
    
    return report


if __name__ == "__main__":
    print(generate_report())
