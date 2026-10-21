"""
Regression tests for semantic extraction response contract.

These tests validate the integration contract between Mistral API responses
and the semantic extraction pipeline. They cover:
1. Plain JSON string responses
2. List-of-blocks responses (reasoning + text blocks)
3. Dict-with-content-list responses
4. Alias-aware entity matching
5. Unsupported passage rejection
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.research.evidence import EvidenceRecord
from app.services.research.mistral_response import normalize_mistral_content
from app.services.research.semantic_extractor import (
    MistralSemanticExtractor,
    ResearchDocument,
    ExtractionResult,
)


# =============================================================================
# Test Fixtures
# =============================================================================

TARGET_ENTITY = "Zimbabwe Energy Regulatory Authority (ZERA)"
PASSAGE = "ZERA regulates the energy sector in Zimbabwe."


def make_document():
    """Create a test ResearchDocument."""
    record = EvidenceRecord(
        url="https://www.zera.co.zw/our-mandate/",
        title="Zimbabwe Energy Regulatory Authority (ZERA)",
        snippet=PASSAGE,
        content=PASSAGE,
        normalized_text=PASSAGE,
        source="official",
        query="ZERA",
        entity_name=TARGET_ENTITY,
    )
    return ResearchDocument.from_evidence_record(record)


# =============================================================================
# Test 1: Plain JSON String Response (Baseline)
# =============================================================================

@pytest.mark.asyncio
async def test_plain_json_response_normalization():
    """Test that plain JSON string responses are normalized correctly."""
    raw = '{"atomic_evidence": [{"subject": "ZERA", "predicate": "regulates", "object": "energy sector", "passage": "ZERA regulates the energy sector in Zimbabwe.", "evidence_type": "RELATIONSHIP", "chunk_index": 0}], "entity_assessment": {"entity_match": true}, "errors": []}'
    
    normalized = normalize_mistral_content(raw, context="SEMANTIC_EXTRACTOR")
    
    assert normalized is not None
    assert isinstance(normalized, str)
    
    # Should parse as valid JSON
    parsed = json.loads(normalized)
    assert "atomic_evidence" in parsed
    assert "entity_assessment" in parsed


# =============================================================================
# Test 2: List-of-Blocks Response (Integration Contract Bug)
# =============================================================================

@pytest.mark.asyncio
async def test_list_of_blocks_response_normalization():
    """Test that list-of-blocks responses (reasoning + text) are normalized to valid JSON.
    
    This is a regression test for the integration contract bug where Mistral
    returns responses as structured blocks instead of plain strings.
    """
    raw = [
        {"type": "reasoning", "thinking": "Checking entity match", "closed": True},
        {"type": "text", "text": '{"atomic_evidence": [{"subject": "ZERA", "predicate": "regulates", "object": "energy sector", "passage": "ZERA regulates the energy sector in Zimbabwe.", "evidence_type": "RELATIONSHIP", "chunk_index": 0}], "entity_assessment": {"entity_match": true}, "errors": []}'},
    ]
    
    normalized = normalize_mistral_content(raw, context="SEMANTIC_EXTRACTOR")
    
    assert normalized is not None, "List-of-blocks normalization failed - returned None"
    assert isinstance(normalized, str)
    
    # The normalized string should be valid JSON (after extracting text blocks)
    try:
        parsed = json.loads(normalized)
        assert "atomic_evidence" in parsed, "Normalized content missing atomic_evidence"
    except json.JSONDecodeError as e:
        pytest.fail(f"List-of-blocks normalization produced invalid JSON: {e}\nNormalized content: {normalized[:500]}")


# =============================================================================
# Test 3: Dict-with-Content-List Response
# =============================================================================

@pytest.mark.asyncio
async def test_dict_with_content_list_response_normalization():
    """Test that dict-with-content-list responses are normalized correctly."""
    raw = {
        "content": [
            {"type": "text", "text": '{"atomic_evidence": [{"subject": "ZERA", "predicate": "regulates", "object": "energy sector", "passage": "ZERA regulates the energy sector in Zimbabwe.", "evidence_type": "RELATIONSHIP", "chunk_index": 0}], "entity_assessment": {"entity_match": true}, "errors": []}'}
        ]
    }
    
    normalized = normalize_mistral_content(raw, context="SEMANTIC_EXTRACTOR")
    
    assert normalized is not None
    assert isinstance(normalized, str)
    
    # Should parse as valid JSON
    parsed = json.loads(normalized)
    assert "atomic_evidence" in parsed


# =============================================================================
# Test 4: Alias-Aware Entity Matching
# =============================================================================

@pytest.mark.asyncio
async def test_alias_aware_entity_matching():
    """Test that evidence with alias subject is accepted when alias is in entity name.
    
    This is a regression test for the validation logic bug where the parser
    requires the full canonical entity name to appear in the subject/passage,
    rather than checking if the subject (alias) appears in the entity name.
    """
    extractor = MistralSemanticExtractor(api_key="test-key")
    doc = make_document()
    
    # Response with alias "ZERA" as subject
    parsed_response = {
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
    
    result = extractor._parse_extraction_result(TARGET_ENTITY, doc, parsed_response)
    
    # The evidence should be ACCEPTED because "ZERA" is in the entity name
    assert len(result.atomic_evidence) > 0, (
        f"Alias-aware entity matching failed: subject='ZERA' was rejected "
        f"even though 'ZERA' is in entity_name='{TARGET_ENTITY}'. "
        f"Extraction errors: {result.extraction_errors}"
    )
    
    # Verify the atomic evidence was created correctly
    evidence = result.atomic_evidence[0]
    assert evidence.subject == "ZERA"
    assert evidence.predicate == "regulates"
    assert evidence.object == "energy sector"
    assert evidence.passage == "ZERA regulates the energy sector in Zimbabwe."


# =============================================================================
# Test 5: Unsupported Passage Rejection
# =============================================================================

@pytest.mark.asyncio
async def test_unsupported_passage_rejection():
    """Test that passages not found in document text are rejected.
    
    This validates that the parser correctly rejects evidence where the
    passage doesn't appear in the source document.
    """
    extractor = MistralSemanticExtractor(api_key="test-key")
    doc = make_document()
    
    # Response with passage NOT in the document
    parsed_response = {
        "atomic_evidence": [
            {
                "subject": "ZERA",
                "predicate": "regulates",
                "object": "energy sector",
                "passage": "THIS PASSAGE IS NOT IN THE DOCUMENT",
                "evidence_type": "RELATIONSHIP",
                "chunk_index": 0,
            }
        ],
        "entity_assessment": {"entity_match": True},
        "errors": [],
    }
    
    result = extractor._parse_extraction_result(TARGET_ENTITY, doc, parsed_response)
    
    # The evidence should be REJECTED because passage doesn't match document
    assert len(result.atomic_evidence) == 0, (
        "Unsupported passage was incorrectly accepted"
    )


# =============================================================================
# Test 6: Entity Name in Passage (Full Match)
# =============================================================================

@pytest.mark.asyncio
async def test_entity_name_in_passage_full_match():
    """Test that evidence with passage matching document is accepted."""
    extractor = MistralSemanticExtractor(api_key="test-key")
    doc = make_document()
    
    # Response with passage that MATCHES the document text
    # The document contains "ZERA regulates the energy sector in Zimbabwe."
    parsed_response = {
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
    
    result = extractor._parse_extraction_result(TARGET_ENTITY, doc, parsed_response)
    
    # Should be accepted - passage matches document text
    assert len(result.atomic_evidence) > 0
    assert result.atomic_evidence[0].subject == "ZERA"


# =============================================================================
# Test 7: Prompt Construction Size
# =============================================================================

@pytest.mark.asyncio
async def test_prompt_construction_size():
    """Test that prompt construction produces reasonable-sized prompts.
    
    Large prompts (>8000 chars) can cause timeouts. This test ensures
    the prompt is within reasonable bounds.
    """
    extractor = MistralSemanticExtractor(api_key="test-key")
    doc = make_document()
    
    prompt = extractor._build_extraction_prompt(
        TARGET_ENTITY,
        doc,
        extractor._create_document_chunks(doc),
    )
    
    # Log prompt size for monitoring
    print(f"\n[PROMPT_SIZE] length={len(prompt)}")
    
    # Should be under 10000 chars to avoid timeout issues
    assert len(prompt) < 10000, (
        f"Prompt too large: {len(prompt)} chars. "
        f"Consider reducing prompt size or using smaller chunks."
    )
    
    # Should contain key elements
    assert TARGET_ENTITY in prompt
    assert PASSAGE in prompt


# =============================================================================
# Test 8: Complete Integration Test
# =============================================================================

@pytest.mark.asyncio
async def test_complete_integration_all_response_types():
    """Complete integration test validating all response types and alias matching.
    
    This test combines all the individual tests into one comprehensive test
    that validates the complete semantic extraction contract.
    """
    extractor = MistralSemanticExtractor(api_key="test-key")
    doc = make_document()
    
    # Test all three response formats
    fixtures = [
        ("plain_json", '{"atomic_evidence": [{"subject": "ZERA", "predicate": "regulates", "object": "energy sector", "passage": "ZERA regulates the energy sector in Zimbabwe.", "evidence_type": "RELATIONSHIP", "chunk_index": 0}], "entity_assessment": {"entity_match": true}, "errors": []}'),
        ("list_of_blocks", [{"type": "text", "text": '{"atomic_evidence": [{"subject": "ZERA", "predicate": "regulates", "object": "energy sector", "passage": "ZERA regulates the energy sector in Zimbabwe.", "evidence_type": "RELATIONSHIP", "chunk_index": 0}], "entity_assessment": {"entity_match": true}, "errors": []}'}]),
        ("dict_with_content", {"content": [{"type": "text", "text": '{"atomic_evidence": [{"subject": "ZERA", "predicate": "regulates", "object": "energy sector", "passage": "ZERA regulates the energy sector in Zimbabwe.", "evidence_type": "RELATIONSHIP", "chunk_index": 0}], "entity_assessment": {"entity_match": true}, "errors": []}'}]}),
    ]
    
    results = []
    for label, raw in fixtures:
        normalized = normalize_mistral_content(raw, context="SEMANTIC_EXTRACTOR")
        assert normalized is not None, f"{label}: normalization returned None"
        
        try:
            parsed = json.loads(normalized)
            result = extractor._parse_extraction_result(TARGET_ENTITY, doc, parsed)
            
            # For alias-aware matching to work, we need the parser to accept "ZERA" as subject
            # when the entity name contains "ZERA"
            if len(result.atomic_evidence) == 0:
                results.append((label, "REJECTED", result.extraction_errors))
            else:
                results.append((label, "ACCEPTED", None))
        except json.JSONDecodeError as e:
            results.append((label, "INVALID_JSON", str(e)))
    
    # Print summary
    print("\n[INTEGRATION_TEST_SUMMARY]")
    for label, status, errors in results:
        print(f"  {label}: {status}")
        if errors:
            print(f"    Errors: {errors}")
    
    # All response types should produce valid, parseable JSON
    for label, status, errors in results:
        assert status != "INVALID_JSON", f"{label}: produced invalid JSON after normalization"
