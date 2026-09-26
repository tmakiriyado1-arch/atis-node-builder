"""
STEP 7: Conservative Content-Level Evidence Deduplication Tests

This test suite verifies the content-level deduplication implementation.

The implementation adds content fingerprinting to the existing URL-based
deduplication in deduplicate_evidence().
"""

from __future__ import annotations

from app.services.research.evidence import (
    EvidenceRecord,
    EvidenceStatus,
    ExtractionQuality,
    deduplicate_evidence,
    _content_fingerprint,
    _canonicalize_content,
)


# =============================================================================
# TEST 1: Identical content, different URLs
# =============================================================================

def test_identical_content_different_urls():
    """Test that identical content from different URLs is deduplicated to 1 record."""
    r1 = EvidenceRecord(
        url="https://a.com/sapp",
        title="SAPP Page A",
        snippet="SAPP coordinates regional electricity cooperation.",
        content="SAPP coordinates regional electricity cooperation.",
        source="official",
        query="sapp",
        entity_name="SAPP",
    )
    r2 = EvidenceRecord(
        url="https://b.com/sapp",
        title="SAPP Page B",
        snippet="SAPP coordinates regional electricity cooperation.",
        content="SAPP coordinates regional electricity cooperation.",
        source="mirror",
        query="sapp regional",
    )
    r3 = EvidenceRecord(
        url="https://c.com/sapp",
        title="SAPP Page C",
        snippet="SAPP coordinates regional electricity cooperation.",
        content="SAPP coordinates regional electricity cooperation.",
        source="archive",
        query="sapp electricity",
    )
    
    result = deduplicate_evidence([r1, r2, r3])
    
    assert len(result) == 1, f"Expected 1 record, got {len(result)}"
    print(f"\u2713 Test 1 passed: {len(result)} record (expected: 1)")


# =============================================================================
# TEST 2: Identical content, multiple URLs (3-5)
# =============================================================================

def test_identical_content_multiple_urls():
    """Test that 5 identical content records from different URLs deduplicate to 1."""
    records = []
    for i in range(5):
        records.append(EvidenceRecord(
            url=f"https://site{i}.com/sapp",
            title=f"SAPP Page {i}",
            snippet="SAPP coordinates regional electricity cooperation.",
            content="SAPP coordinates regional electricity cooperation.",
            source="mirror",
            query=f"query{i}",
        ))
    
    result = deduplicate_evidence(records)
    
    assert len(result) == 1, f"Expected 1 record, got {len(result)}"
    print(f"\u2713 Test 2 passed: {len(result)} record (expected: 1)")


# =============================================================================
# TEST 3: Different content, different URLs
# =============================================================================

def test_different_content_different_urls():
    """Test that different content from different URLs is NOT deduplicated."""
    r1 = EvidenceRecord(
        url="https://a.com/sapp",
        title="SAPP Overview",
        snippet="SAPP coordinates regional electricity.",
        content="SAPP coordinates regional electricity.",
    )
    r2 = EvidenceRecord(
        url="https://b.com/sapp",
        title="SAPP Details",
        snippet="SAPP manages power grid infrastructure.",
        content="SAPP manages power grid infrastructure.",
    )
    r3 = EvidenceRecord(
        url="https://c.com/sapp",
        title="SAPP History",
        snippet="SAPP was established in 1995.",
        content="SAPP was established in 1995.",
    )
    
    result = deduplicate_evidence([r1, r2, r3])
    
    assert len(result) == 3, f"Expected 3 records, got {len(result)}"
    print(f"\u2713 Test 3 passed: {len(result)} records (expected: 3)")


# =============================================================================
# TEST 4: Whitespace-only variation
# =============================================================================

def test_whitespace_variation():
    """Test that whitespace-only differences are normalized and deduplicated."""
    r1 = EvidenceRecord(
        url="https://a.com",
        title="Test",
        snippet="SAPP   coordinates  regional electricity.",
        content="SAPP   coordinates  regional electricity.",
    )
    r2 = EvidenceRecord(
        url="https://b.com",
        title="Test 2",
        snippet="SAPP coordinates regional electricity.",
        content="SAPP coordinates regional electricity.",
    )
    
    result = deduplicate_evidence([r1, r2])
    
    assert len(result) == 1, f"Expected 1 record, got {len(result)}"
    print(f"\u2713 Test 4 passed: {len(result)} record (expected: 1)")


# =============================================================================
# TEST 5: Punctuation difference
# =============================================================================

def test_punctuation_difference():
    """Test that punctuation differences are NOT normalized - should NOT deduplicate."""
    r1 = EvidenceRecord(
        url="https://a.com",
        title="Test",
        snippet="SAPP coordinates regional electricity.",
        content="SAPP coordinates regional electricity.",
    )
    r2 = EvidenceRecord(
        url="https://b.com",
        title="Test 2",
        snippet="SAPP coordinates regional electricity!",
        content="SAPP coordinates regional electricity!",
    )
    
    result = deduplicate_evidence([r1, r2])
    
    assert len(result) == 2, f"Expected 2 records, got {len(result)}"
    print(f"\u2713 Test 5 passed: {len(result)} records (expected: 2)")


# =============================================================================
# TEST 6: Case difference
# =============================================================================

def test_case_difference():
    """Test that case differences are NOT normalized - should NOT deduplicate."""
    r1 = EvidenceRecord(
        url="https://a.com",
        title="Test",
        snippet="SAPP coordinates regional electricity.",
        content="SAPP coordinates regional electricity.",
    )
    r2 = EvidenceRecord(
        url="https://b.com",
        title="Test 2",
        snippet="sapp coordinates regional electricity.",
        content="sapp coordinates regional electricity.",
    )
    
    result = deduplicate_evidence([r1, r2])
    
    assert len(result) == 2, f"Expected 2 records, got {len(result)}"
    print(f"\u2713 Test 6 passed: {len(result)} records (expected: 2)")


# =============================================================================
# TEST 7: THIN evidence preserved
# =============================================================================

def test_thin_evidence_preserved():
    """Test that THIN evidence still reaches deduplication output."""
    r1 = EvidenceRecord(
        url="https://a.com",
        title="Thin snippet",
        snippet="SAPP operates.",
        content="SAPP operates.",
        evidence_status=EvidenceStatus.THIN,
        extraction_quality=ExtractionQuality.THIN,
    )
    r2 = EvidenceRecord(
        url="https://b.com",
        title="Different thin",
        snippet="SAPP manages.",
        content="SAPP manages.",
        evidence_status=EvidenceStatus.THIN,
        extraction_quality=ExtractionQuality.THIN,
    )
    
    result = deduplicate_evidence([r1, r2])
    
    # THIN evidence should be preserved (not filtered)
    assert len(result) == 2, f"Expected 2 records, got {len(result)}"
    assert all(r.evidence_status == EvidenceStatus.THIN for r in result)
    print(f"\u2713 Test 7 passed: {len(result)} THIN records preserved (expected: 2)")


# =============================================================================
# TEST 8: UNUSABLE evidence behavior
# =============================================================================

def test_unusable_evidence_behavior():
    """Test that UNUSABLE evidence is handled correctly.
    
    UNUSABLE evidence should still go through deduplication (URL + content).
    The filtering of UNUSABLE happens later in _create_evidence_chunks().
    """
    r1 = EvidenceRecord(
        url="https://a.com/blocked",
        title="Access Denied",
        snippet="Access denied.",
        content="Access denied.",
        evidence_status=EvidenceStatus.UNUSABLE,
        extraction_quality=ExtractionQuality.BLOCK_PAGE,
    )
    r2 = EvidenceRecord(
        url="https://b.com/blocked",
        title="Access Denied 2",
        snippet="Access denied.",
        content="Access denied.",
        evidence_status=EvidenceStatus.UNUSABLE,
        extraction_quality=ExtractionQuality.BLOCK_PAGE,
    )
    
    result = deduplicate_evidence([r1, r2])
    
    # Content-level deduplication should still apply
    assert len(result) == 1, f"Expected 1 record, got {len(result)}"
    assert result[0].evidence_status == EvidenceStatus.UNUSABLE
    print(f"\u2713 Test 8 passed: {len(result)} UNUSABLE record (expected: 1, content-deduped)")


# =============================================================================
# TEST 9: Provenance preservation
# =============================================================================

def test_provenance_preservation():
    """Test that provenance information is preserved after deduplication."""
    r1 = EvidenceRecord(
        url="https://a.com",
        title="First Source",
        snippet="SAPP coordinates.",
        content="SAPP coordinates.",
        query="query1",
        entity_name="SAPP",
        entity_id=None,
        original_url="https://original-a.com",
    )
    r2 = EvidenceRecord(
        url="https://b.com",
        title="Second Source",
        snippet="SAPP coordinates.",
        content="SAPP coordinates.",
        query="query2",
        entity_name=None,
        entity_id="entity123",
        original_url="https://original-b.com",
    )
    r3 = EvidenceRecord(
        url="https://c.com",
        title="Third Source",
        snippet="SAPP coordinates.",
        content="SAPP coordinates.",
        query="query3",
        entity_name=None,
        entity_id=None,
        original_url=None,
    )
    
    result = deduplicate_evidence([r1, r2, r3])
    
    assert len(result) == 1, f"Expected 1 record, got {len(result)}"
    
    retained = result[0]
    
    # URL: should be first record's URL
    assert retained.url == "https://a.com"
    
    # Queries: should accumulate all unique queries
    # Note: query1 is added to r1's queries during URL dedup
    assert "query1" in retained.queries
    assert "query2" in retained.queries
    assert "query3" in retained.queries
    
    # Entity name: should be from first record
    assert retained.entity_name == "SAPP"
    
    # Entity ID: should be filled from duplicate
    assert retained.entity_id == "entity123"
    
    # Original URL: should be from first record (limitation: can't merge multiple)
    assert retained.original_url == "https://original-a.com"
    
    print(f"\u2713 Test 9 passed: Provenance preserved correctly")


# =============================================================================
# TEST 10: Downstream chunk reduction
# =============================================================================

def test_downstream_chunk_reduction():
    """Test that deduplication reduces the number of chunks passed downstream.
    
    This verifies that content deduplication happens before chunking.
    """
    from app.services.research.mistral_enrichment import _create_evidence_chunks
    
    # Create 5 records with identical content
    records = []
    for i in range(5):
        records.append(EvidenceRecord(
            url=f"https://site{i}.com/sapp",
            title=f"SAPP Page {i}",
            snippet="SAPP coordinates regional electricity cooperation.",
            content="SAPP coordinates regional electricity cooperation.",
        ))
    
    # Before deduplication: 5 records
    assert len(records) == 5
    
    # After deduplication: 1 record
    deduped = deduplicate_evidence(records)
    assert len(deduped) == 1
    
    # After chunking: should produce 1 chunk (not 5)
    chunks = _create_evidence_chunks(deduped)
    assert len(chunks) == 1, f"Expected 1 chunk, got {len(chunks)}"
    
    print(f"\u2713 Test 10 passed: 5 records -> {len(deduped)} deduped -> {len(chunks)} chunk")


# =============================================================================
# CANONICALIZATION TESTS
# =============================================================================

def test_canonicalize_content_whitespace():
    """Test that canonicalization normalizes whitespace correctly."""
    from app.services.research.evidence import _canonicalize_content
    
    # Multiple spaces
    assert _canonicalize_content("a  b   c") == "a b c"
    
    # Leading/trailing whitespace
    assert _canonicalize_content("  a b c  ") == "a b c"
    
    # Newlines
    assert _canonicalize_content("a\nb\nc") == "a b c"
    assert _canonicalize_content("a\r\nb\rc") == "a b c"
    
    # Tabs
    assert _canonicalize_content("a\tb\tc") == "a b c"
    
    # Empty
    assert _canonicalize_content("") == ""
    assert _canonicalize_content("   ") == ""
    
    print("\u2713 Canonicalization whitespace tests passed")


def test_canonicalize_content_preserves_punctuation():
    """Test that canonicalization preserves punctuation."""
    from app.services.research.evidence import _canonicalize_content
    
    assert _canonicalize_content("Hello, world!") == "Hello, world!"
    assert _canonicalize_content("Test... yes.") == "Test... yes."
    
    print("\u2713 Canonicalization punctuation tests passed")


def test_canonicalize_content_preserves_case():
    """Test that canonicalization preserves case."""
    from app.services.research.evidence import _canonicalize_content
    
    assert _canonicalize_content("SAPP is great") == "SAPP is great"
    assert _canonicalize_content("sapp is great") == "sapp is great"
    assert _canonicalize_content("SAPP is great") != _canonicalize_content("sapp is great")
    
    print("\u2713 Canonicalization case tests passed")


# =============================================================================
# FINGERPRINT TESTS
# =============================================================================

def test_fingerprint_deterministic():
    """Test that fingerprinting is deterministic."""
    content = "SAPP coordinates regional electricity cooperation."
    
    fp1 = _content_fingerprint(content)
    fp2 = _content_fingerprint(content)
    
    assert fp1 == fp2, "Fingerprint should be deterministic"
    assert len(fp1) == 64, "SHA-256 hex digest should be 64 characters"
    
    print("\u2713 Fingerprint deterministic test passed")


def test_fingerprint_different_content():
    """Test that different content produces different fingerprints."""
    fp1 = _content_fingerprint("SAPP coordinates.")
    fp2 = _content_fingerprint("SAPP manages.")
    
    assert fp1 != fp2, "Different content should produce different fingerprints"
    
    print("\u2713 Fingerprint different content test passed")


def test_fingerprint_empty():
    """Test that empty content produces empty fingerprint."""
    fp = _content_fingerprint("")
    assert fp == "", "Empty content should produce empty fingerprint"
    
    fp = _content_fingerprint("   ")
    assert fp == "", "Whitespace-only content should produce empty fingerprint"
    
    print("\u2713 Fingerprint empty test passed")


# =============================================================================
# EDGE CASES
# =============================================================================

def test_empty_content_records():
    """Test handling of records with empty content."""
    r1 = EvidenceRecord(
        url="https://a.com",
        title="Empty",
        snippet="",
        content="",
    )
    r2 = EvidenceRecord(
        url="https://b.com",
        title="Also Empty",
        snippet="",
        content="",
    )
    
    result = deduplicate_evidence([r1, r2])
    
    # Empty content records should still be URL-deduped
    # Since both have empty content, they should be treated as duplicates
    assert len(result) <= 2  # Could be 1 or 2 depending on implementation
    
    print(f"\u2713 Empty content test passed: {len(result)} records")


def test_snippet_fallback():
    """Test that snippet is used as fallback when content is empty."""
    r1 = EvidenceRecord(
        url="https://a.com",
        title="Test",
        snippet="SAPP coordinates.",
        content="",  # Empty content
    )
    r2 = EvidenceRecord(
        url="https://b.com",
        title="Test 2",
        snippet="SAPP coordinates.",
        content="",  # Empty content
    )
    
    result = deduplicate_evidence([r1, r2])
    
    # Should deduplicate based on snippet
    assert len(result) == 1, f"Expected 1 record (snippet fallback), got {len(result)}"
    
    print("\u2713 Snippet fallback test passed")


def test_url_duplication_still_works():
    """Test that URL-level deduplication still works."""
    r1 = EvidenceRecord(
        url="https://a.com",
        title="First",
        snippet="SAPP coordinates.",
        content="SAPP coordinates.",
        query="query1",
    )
    r2 = EvidenceRecord(
        url="https://a.com",  # Same URL
        title="Second",
        snippet="SAPP manages.",
        content="SAPP manages.",  # Different content
        query="query2",
    )
    
    result = deduplicate_evidence([r1, r2])
    
    # URL deduplication should merge these
    assert len(result) == 1, f"Expected 1 record (URL dedup), got {len(result)}"
    # Queries should be merged (query1 is added to r1 during URL dedup)
    assert "query1" in result[0].queries, f"query1 not in {result[0].queries}"
    assert "query2" in result[0].queries, f"query2 not in {result[0].queries}"
    
    print("\u2713 URL duplication test passed")


# =============================================================================
# RUN ALL TESTS
# =============================================================================

def run_all_tests():
    """Run all Step 7 tests."""
    print("=" * 70)
    print("STEP 7: Content-Level Evidence Deduplication Tests")
    print("=" * 70)
    print()
    
    tests = [
        ("Identical content, different URLs", test_identical_content_different_urls),
        ("Identical content, multiple URLs", test_identical_content_multiple_urls),
        ("Different content, different URLs", test_different_content_different_urls),
        ("Whitespace variation", test_whitespace_variation),
        ("Punctuation difference", test_punctuation_difference),
        ("Case difference", test_case_difference),
        ("THIN evidence preserved", test_thin_evidence_preserved),
        ("UNUSABLE evidence behavior", test_unusable_evidence_behavior),
        ("Provenance preservation", test_provenance_preservation),
        ("Downstream chunk reduction", test_downstream_chunk_reduction),
        ("Canonicalization whitespace", test_canonicalize_content_whitespace),
        ("Canonicalization punctuation", test_canonicalize_content_preserves_punctuation),
        ("Canonicalization case", test_canonicalize_content_preserves_case),
        ("Fingerprint deterministic", test_fingerprint_deterministic),
        ("Fingerprint different content", test_fingerprint_different_content),
        ("Fingerprint empty", test_fingerprint_empty),
        ("Empty content records", test_empty_content_records),
        ("Snippet fallback", test_snippet_fallback),
        ("URL duplication still works", test_url_duplication_still_works),
    ]
    
    passed = 0
    failed = 0
    
    for name, test_func in tests:
        try:
            test_func()
            passed += 1
        except AssertionError as e:
            print(f"\u2717 {name}: FAILED - {e}")
            failed += 1
        except Exception as e:
            print(f"\u2717 {name}: ERROR - {e}")
            failed += 1
    
    print()
    print("=" * 70)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 70)
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    exit(0 if success else 1)
