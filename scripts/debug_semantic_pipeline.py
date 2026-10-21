#!/usr/bin/env python3
"""Focused debug harness for the semantic extraction contract.

Purpose:
- isolate whether the production failure is caused by:
  1) prompt construction / payload size
  2) Mistral response-shape mismatch
  3) parser validation of entity aliases / passages
  4) downstream misclassification of failed checks as evidence rejection

This script intentionally exercises the exact failure pattern we saw with ZERA:
- valid alias subject like 'ZERA'
- full canonical name present in title or document
- a valid relationship predicate
- a document with exact supporting passage
- a response variant that may be a list-of-blocks rather than a plain JSON string
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

from app.services.research.evidence import EvidenceRecord
from app.services.research.mistral_response import normalize_mistral_content
from app.services.research.semantic_extractor import MistralSemanticExtractor, ResearchDocument

TARGET_ENTITY = "Zimbabwe Energy Regulatory Authority (ZERA)"
ZERA_PASSAGE = "ZERA regulates the energy sector in Zimbabwe."


def make_document(passage: str = ZERA_PASSAGE) -> ResearchDocument:
    record = EvidenceRecord(
        url="https://www.zera.co.zw/our-mandate/",
        title="Zimbabwe Energy Regulatory Authority (ZERA)",
        snippet=passage,
        content=passage,
        normalized_text=passage,
        source="official",
        query="ZERA",
        entity_name=TARGET_ENTITY,
    )
    return ResearchDocument.from_evidence_record(record)


def build_debug_prompt() -> str:
    extractor = MistralSemanticExtractor(api_key="debug-key")
    document = make_document()
    chunks = extractor._create_document_chunks(document)
    prompt = extractor._build_extraction_prompt(TARGET_ENTITY, document, chunks)
    return prompt


def inspect_response_shape(raw_response: Any, label: str) -> Dict[str, Any]:
    normalized = normalize_mistral_content(raw_response, context=label)
    result: Dict[str, Any] = {
        "label": label,
        "raw_type": type(raw_response).__name__,
        "normalized_is_none": normalized is None,
        "normalized_preview": (normalized[:240] if isinstance(normalized, str) else None),
        "normalized_length": len(normalized) if isinstance(normalized, str) else 0,
    }

    if isinstance(normalized, str):
        try:
            parsed = json.loads(normalized)
            result["json_parse_success"] = True
            result["json_top_keys"] = list(parsed.keys()) if isinstance(parsed, dict) else type(parsed).__name__
        except Exception as exc:  # pragma: no cover - diagnostic output only
            result["json_parse_success"] = False
            result["json_parse_error"] = str(exc)
    else:
        result["json_parse_success"] = False
        result["json_parse_error"] = "normalized_output_missing"
    return result


def run_debug_suite() -> List[Dict[str, Any]]:
    extractor = MistralSemanticExtractor(api_key="debug-key")
    document = make_document()

    fixtures = [
        (
            "plain_json_string",
            '{"atomic_evidence": [{"subject": "ZERA", "predicate": "regulates", "object": "energy sector", "passage": "ZERA regulates the energy sector in Zimbabwe.", "evidence_type": "RELATIONSHIP", "chunk_index": 0}], "entity_assessment": {"entity_match": true}, "errors": []}',
        ),
        (
            "list_of_blocks",
            [
                {"type": "reasoning", "thinking": "I am checking the entity match.", "closed": True},
                {"type": "text", "text": '{"atomic_evidence": [{"subject": "ZERA", "predicate": "regulates", "object": "energy sector", "passage": "ZERA regulates the energy sector in Zimbabwe.", "evidence_type": "RELATIONSHIP", "chunk_index": 0}], "entity_assessment": {"entity_match": true}, "errors": []}'},
            ],
        ),
        (
            "dict_with_content_list",
            {"content": [
                {"type": "text", "text": '{"atomic_evidence": [{"subject": "ZERA", "predicate": "regulates", "object": "energy sector", "passage": "ZERA regulates the energy sector in Zimbabwe.", "evidence_type": "RELATIONSHIP", "chunk_index": 0}], "entity_assessment": {"entity_match": true}, "errors": []}'}
            ]},
        ),
    ]

    responses: List[Dict[str, Any]] = []
    for label, raw in fixtures:
        responses.append(inspect_response_shape(raw, label))

    for item in responses:
        if item.get("json_parse_success"):
            try:
                parsed = json.loads(item["normalized_preview"] or "")
                result = extractor._parse_extraction_result(TARGET_ENTITY, document, parsed, aliases=["ZERA"])
                item["accepted_evidence_count"] = len(result.atomic_evidence)
                item["rejection_reasons"] = result.rejection_reasons
            except Exception as exc:  # pragma: no cover - diagnostic output only
                item["accepted_evidence_count"] = 0
                item["parse_exception"] = str(exc)
        else:
            item["accepted_evidence_count"] = 0
            item["rejection_reasons"] = []

    return responses


def main() -> None:
    print("== Prompt debug ==")
    prompt = build_debug_prompt()
    print(f"prompt_length={len(prompt)}")
    print(prompt[:800])

    print("\n== Response-shape debug ==")
    for item in run_debug_suite():
        print(json.dumps(item, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
