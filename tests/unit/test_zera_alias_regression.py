from __future__ import annotations

from app.services.research.evidence import EvidenceRecord
from app.services.research.semantic_extractor import (
    EvidenceType,
    MistralSemanticExtractor,
    ResearchDocument,
)


TARGET_ENTITY = "Zimbabwe Energy Regulatory Authority (ZERA)"


def _make_document(passage: str, title: str = "ZERA Mandate") -> ResearchDocument:
    record = EvidenceRecord(
        url="https://www.zera.co.zw/our-mandate/",
        title=title,
        snippet=passage,
        content=passage,
        normalized_text=passage,
        source="official",
        query="ZERA",
        entity_name=TARGET_ENTITY,
    )
    return ResearchDocument.from_evidence_record(record)


def test_parse_extraction_result_accepts_known_alias_subject() -> None:
    extractor = MistralSemanticExtractor(api_key="test-key")
    document = _make_document("ZERA regulates the energy sector in Zimbabwe.")
    parsed = {
        "atomic_evidence": [
            {
                "subject": "ZERA",
                "predicate": "regulates",
                "object": "energy sector",
                "passage": "ZERA regulates the energy sector in Zimbabwe.",
                "evidence_type": "RELATIONSHIP",
                "chunk_index": 0,
            }
        ],
        "entity_assessment": {"entity_match": True},
        "errors": [],
    }

    result = extractor._parse_extraction_result(TARGET_ENTITY, document, parsed, aliases=["ZERA"])

    assert result.evidence_count == 1
    assert result.atomic_evidence[0].subject == "ZERA"
    assert result.atomic_evidence[0].passage == "ZERA regulates the energy sector in Zimbabwe."
    assert result.atomic_evidence[0].evidence_type == EvidenceType.RELATIONSHIP


def test_verify_entity_match_accepts_canonical_and_alias_forms() -> None:
    extractor = MistralSemanticExtractor(api_key="test-key")
    document = _make_document("The Zimbabwe Energy Regulatory Authority (ZERA) regulates the energy sector in Zimbabwe.")

    assert extractor._verify_entity_match(TARGET_ENTITY, document) is True
    assert extractor._verify_entity_match(TARGET_ENTITY, document, aliases=["ZERA"]) is True
    assert extractor._verify_entity_match(TARGET_ENTITY, document, aliases=["Zimbabwe Energy Regulatory Authority"]) is True


def test_verify_entity_match_rejects_unrelated_entity() -> None:
    extractor = MistralSemanticExtractor(api_key="test-key")
    document = _make_document("The Ministry of Energy manages utilities and infrastructure in Zimbabwe.")

    assert extractor._verify_entity_match(TARGET_ENTITY, document) is False
    assert extractor._verify_entity_match(TARGET_ENTITY, document, aliases=["ZERA"]) is False


def test_parse_extraction_result_rejects_missing_or_unsupported_passage() -> None:
    extractor = MistralSemanticExtractor(api_key="test-key")
    document = _make_document("ZERA regulates the energy sector in Zimbabwe.")

    missing = extractor._parse_extraction_result(
        TARGET_ENTITY,
        document,
        {
            "atomic_evidence": [{
                "subject": "ZERA",
                "predicate": "regulates",
                "object": "energy sector",
                "passage": "",
                "evidence_type": "RELATIONSHIP",
                "chunk_index": 0,
            }],
            "entity_assessment": {"entity_match": True},
            "errors": [],
        },
        aliases=["ZERA"],
    )
    assert missing.evidence_count == 0
    assert any(reason.get("reason") == "missing_passage" for reason in missing.rejection_reasons)

    unsupported = extractor._parse_extraction_result(
        TARGET_ENTITY,
        document,
        {
            "atomic_evidence": [{
                "subject": "ZERA",
                "predicate": "regulates",
                "object": "energy sector",
                "passage": "A completely unrelated utility board regulates the energy sector.",
                "evidence_type": "RELATIONSHIP",
                "chunk_index": 0,
            }],
            "entity_assessment": {"entity_match": True},
            "errors": [],
        },
        aliases=["ZERA"],
    )
    assert unsupported.evidence_count == 0
    assert any(reason.get("reason") == "unsupported_passage" for reason in unsupported.rejection_reasons)


def test_parse_extraction_result_rejects_malformed_record() -> None:
    extractor = MistralSemanticExtractor(api_key="test-key")
    document = _make_document("ZERA regulates the energy sector in Zimbabwe.")

    result = extractor._parse_extraction_result(
        TARGET_ENTITY,
        document,
        {
            "atomic_evidence": [{
                "subject": "ZERA",
                "predicate": "regulates",
                "object": "energy sector",
                "evidence_type": "RELATIONSHIP",
                "chunk_index": 0,
            }],
            "entity_assessment": {"entity_match": True},
            "errors": [],
        },
        aliases=["ZERA"],
    )

    assert result.evidence_count == 0
    assert any(reason.get("reason") == "missing_passage" for reason in result.rejection_reasons)
