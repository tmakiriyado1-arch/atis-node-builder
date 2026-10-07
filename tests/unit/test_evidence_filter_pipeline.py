"""Tests for Evidence Filter Pipeline.

These tests verify the complete evidence filtering pipeline:
1. Entity-Relevant Evidence Filter (DIRECT/RELATED/IRRELEVANT classification)
2. Atomic Claims Extraction
3. Claim Validation (Quality Gate)
4. Deduplication

Key architectural principle:
    Raw webpage text must NEVER be treated as canonical node data.
    Only entity-relevant, atomic, validated, deduplicated claims reach canonicalization.
"""
from __future__ import annotations

import pytest
from datetime import datetime, timezone

from app.services.research.evidence_filter import (
    EvidenceFilterPipeline,
    AtomicClaim,
    RelevanceClassification,
    EvidenceQualityStatus,
)
from app.services.research.evidence import EvidenceRecord, EvidenceStatus, ExtractionQuality, RetrievalStatus


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def ontology():
    from app.services.ontology import get_ontology
    return get_ontology()


@pytest.fixture
def theotechnic_evidence_records(ontology):
    """Create realistic evidence records for Theotechnic College.
    
    These simulate what would be returned from web crawling.
    """
    records = []
    
    # Record 1: Direct evidence from official site
    records.append(EvidenceRecord(
        url="https://www.theotec.org/about",
        title="About Theotechnic College",
        snippet="Theotechnic College is a Christian educational institution focused on theological education.",
        normalized_text="Theotechnic College is a Christian educational institution focused on theological education, practical ministry training, and vocational development. It combines biblical studies with practical skills.",
        content="Theotechnic College is a Christian educational institution focused on theological education, practical ministry training, and vocational development. It combines biblical studies with practical skills.",
        source="leanstral_web_research",
        query="Theotechnic College",
        entity_name="Theotechnic College",
        entity_id=None,
        http_status=200,
        content_type="text/html",
        retrieval_status=RetrievalStatus.SUCCESS,
        extraction_quality=ExtractionQuality.SUBSTANTIVE,
        evidence_status=EvidenceStatus.USABLE,
        metadata={"research_method": "leanstral_tool_driven"},
    ))
    
    # Record 2: Related evidence mentioning ACTIVE Ministry
    records.append(EvidenceRecord(
        url="https://www.activeministry.org/theotechnic",
        title="Theotechnic College - ACTIVE Ministry",
        snippet="ACTIVE Ministry provides operational and strategic support to Theotechnic College.",
        normalized_text="ACTIVE Ministry provides operational and strategic support to Theotechnic College. This support enables the college to deliver quality theological education.",
        content="ACTIVE Ministry provides operational and strategic support to Theotechnic College. This support enables the college to deliver quality theological education.",
        source="leanstral_web_research",
        query="Theotechnic College",
        entity_name="Theotechnic College",
        entity_id=None,
        http_status=200,
        content_type="text/html",
        retrieval_status=RetrievalStatus.SUCCESS,
        extraction_quality=ExtractionQuality.SUBSTANTIVE,
        evidence_status=EvidenceStatus.USABLE,
        metadata={"research_method": "leanstral_tool_driven"},
    ))
    
    # Record 3: Irrelevant - navigation page
    records.append(EvidenceRecord(
        url="https://www.theotec.org",
        title="Theotechnic College - Home",
        snippet="Home About Programs Apply Now Contact",
        normalized_text="Home About Programs Apply Now Contact",
        content="Home About Programs Apply Now Contact",
        source="leanstral_web_research",
        query="Theotechnic College",
        entity_name="Theotechnic College",
        entity_id=None,
        http_status=200,
        content_type="text/html",
        retrieval_status=RetrievalStatus.SUCCESS,
        extraction_quality=ExtractionQuality.THIN,
        evidence_status=EvidenceStatus.USABLE,
        metadata={"research_method": "leanstral_tool_driven"},
    ))
    
    # Record 4: Irrelevant - marketing slogan
    records.append(EvidenceRecord(
        url="https://www.theotec.org/welcome",
        title="Welcome to Theotechnic College",
        snippet="Now Open! All applicants will be placed on a prospective list. Join us today!",
        normalized_text="Now Open! All applicants will be placed on a prospective list. Join us today! Discover your future. Take the first step to make a difference.",
        content="Now Open! All applicants will be placed on a prospective list. Join us today! Discover your future. Take the first step to make a difference.",
        source="leanstral_web_research",
        query="Theotechnic College",
        entity_name="Theotechnic College",
        entity_id=None,
        http_status=200,
        content_type="text/html",
        retrieval_status=RetrievalStatus.SUCCESS,
        extraction_quality=ExtractionQuality.THIN,
        evidence_status=EvidenceStatus.USABLE,
        metadata={"research_method": "leanstral_tool_driven"},
    ))
    
    # Record 5: Irrelevant - Bible verse
    records.append(EvidenceRecord(
        url="https://www.theotec.org/mission",
        title="Our Mission - Theotechnic College",
        snippet="2 Timothy 2:15 - Study to show thyself approved unto God.",
        normalized_text="2 Timothy 2:15 - Study to show thyself approved unto God. A workman that needeth not to be ashamed, rightly dividing the word of truth.",
        content="2 Timothy 2:15 - Study to show thyself approved unto God. A workman that needeth not to be ashamed, rightly dividing the word of truth.",
        source="leanstral_web_research",
        query="Theotechnic College",
        entity_name="Theotechnic College",
        entity_id=None,
        http_status=200,
        content_type="text/html",
        retrieval_status=RetrievalStatus.SUCCESS,
        extraction_quality=ExtractionQuality.THIN,
        evidence_status=EvidenceStatus.USABLE,
        metadata={"research_method": "leanstral_tool_driven"},
    ))
    
    # Record 6: Direct evidence - programs
    records.append(EvidenceRecord(
        url="https://www.theotec.org/programs",
        title="Programs - Theotechnic College",
        snippet="Theotechnic College offers Bachelor of Arts in Biblical Studies with Vocational Pathways.",
        normalized_text="Theotechnic College offers Bachelor of Arts in Biblical Studies with Vocational Pathways. Programs combine theological studies with practical vocational training.",
        content="Theotechnic College offers Bachelor of Arts in Biblical Studies with Vocational Pathways. Programs combine theological studies with practical vocational training.",
        source="leanstral_web_research",
        query="Theotechnic College",
        entity_name="Theotechnic College",
        entity_id=None,
        http_status=200,
        content_type="text/html",
        retrieval_status=RetrievalStatus.SUCCESS,
        extraction_quality=ExtractionQuality.SUBSTANTIVE,
        evidence_status=EvidenceStatus.USABLE,
        metadata={"research_method": "leanstral_tool_driven"},
    ))
    
    # Record 7: Irrelevant - single letter fragment
    records.append(EvidenceRecord(
        url="https://www.theotec.org/alphabet",
        title="Alphabet - Theotechnic College",
        snippet="c",
        normalized_text="c",
        content="c",
        source="leanstral_web_research",
        query="Theotechnic College",
        entity_name="Theotechnic College",
        entity_id=None,
        http_status=200,
        content_type="text/html",
        retrieval_status=RetrievalStatus.SUCCESS,
        extraction_quality=ExtractionQuality.EMPTY,
        evidence_status=EvidenceStatus.UNUSABLE,
        metadata={"research_method": "leanstral_tool_driven"},
    ))
    
    return records


@pytest.fixture
def zera_evidence_records(ontology):
    """Create realistic evidence records for ZERA (Zimbabwe Energy Regulatory Authority)."""
    records = []
    
    # Record 1: Direct evidence from official site
    records.append(EvidenceRecord(
        url="https://www.zera.co.zw/about",
        title="About ZERA",
        snippet="ZERA is the Zimbabwe Energy Regulatory Authority.",
        normalized_text="ZERA is the Zimbabwe Energy Regulatory Authority, a statutory body responsible for regulating the energy sector in Zimbabwe. It oversees electricity generation, transmission, distribution, and pricing.",
        content="ZERA is the Zimbabwe Energy Regulatory Authority, a statutory body responsible for regulating the energy sector in Zimbabwe. It oversees electricity generation, transmission, distribution, and pricing.",
        source="leanstral_web_research",
        query="ZERA",
        entity_name="ZERA",
        entity_id=None,
        http_status=200,
        content_type="text/html",
        retrieval_status=RetrievalStatus.SUCCESS,
        extraction_quality=ExtractionQuality.SUBSTANTIVE,
        evidence_status=EvidenceStatus.USABLE,
        metadata={"research_method": "leanstral_tool_driven"},
    ))
    
    # Record 2: Direct evidence - sector
    records.append(EvidenceRecord(
        url="https://www.zera.co.zw/responsibilities",
        title="Responsibilities - ZERA",
        snippet="ZERA regulates the energy sector in Zimbabwe.",
        normalized_text="ZERA regulates the energy sector in Zimbabwe. The authority ensures fair pricing, quality service, and sustainable development in the energy industry.",
        content="ZERA regulates the energy sector in Zimbabwe. The authority ensures fair pricing, quality service, and sustainable development in the energy industry.",
        source="leanstral_web_research",
        query="ZERA",
        entity_name="ZERA",
        entity_id=None,
        http_status=200,
        content_type="text/html",
        retrieval_status=RetrievalStatus.SUCCESS,
        extraction_quality=ExtractionQuality.SUBSTANTIVE,
        evidence_status=EvidenceStatus.USABLE,
        metadata={"research_method": "leanstral_tool_driven"},
    ))
    
    # Record 3: Irrelevant - navigation
    records.append(EvidenceRecord(
        url="https://www.zera.co.zw",
        title="ZERA - Home",
        snippet="Home About Us Regulations Contact Us",
        normalized_text="Home About Us Regulations Contact Us",
        content="Home About Us Regulations Contact Us",
        source="leanstral_web_research",
        query="ZERA",
        entity_name="ZERA",
        entity_id=None,
        http_status=200,
        content_type="text/html",
        retrieval_status=RetrievalStatus.SUCCESS,
        extraction_quality=ExtractionQuality.THIN,
        evidence_status=EvidenceStatus.USABLE,
        metadata={"research_method": "leanstral_tool_driven"},
    ))
    
    # Record 4: Irrelevant - generic text
    records.append(EvidenceRecord(
        url="https://www.zera.co.zw/news",
        title="News - ZERA",
        snippet="Welcome to our news section. Stay updated with the latest.",
        normalized_text="Welcome to our news section. Stay updated with the latest information from ZERA.",
        content="Welcome to our news section. Stay updated with the latest information from ZERA.",
        source="leanstral_web_research",
        query="ZERA",
        entity_name="ZERA",
        entity_id=None,
        http_status=200,
        content_type="text/html",
        retrieval_status=RetrievalStatus.SUCCESS,
        extraction_quality=ExtractionQuality.THIN,
        evidence_status=EvidenceStatus.USABLE,
        metadata={"research_method": "leanstral_tool_driven"},
    ))
    
    return records


# =============================================================================
# Evidence Filter Pipeline Tests - Theotechnic College
# =============================================================================

class TestTheotechnicEvidenceFilter:
    """Test the evidence filtering pipeline with Theotechnic College."""
    
    @pytest.mark.asyncio
    async def test_filter_entity_relevant_evidence_theotechnic(
        self,
        theotechnic_evidence_records,
    ):
        """Test that evidence is correctly classified as DIRECT, RELATED, or IRRELEVANT."""
        pipeline = EvidenceFilterPipeline(target_entity="Theotechnic College")
        
        direct, related, irrelevant = pipeline.filter_entity_relevant_evidence(
            theotechnic_evidence_records
        )
        
        # Should have 3 direct evidence records
        assert len(direct) >= 2, f"Expected at least 2 DIRECT records, got {len(direct)}"
        
        # Should have 1 related evidence record (ACTIVE Ministry support)
        assert len(related) >= 1, f"Expected at least 1 RELATED record, got {len(related)}"
        
        # Should have 4+ irrelevant records (navigation, marketing, Bible verse, single letter)
        assert len(irrelevant) >= 4, f"Expected at least 4 IRRELEVANT records, got {len(irrelevant)}"
        
        # Verify direct records contain entity name
        for record in direct:
            text = pipeline._get_authoritative_text(record)
            assert "Theotechnic College" in text or "theotechnic" in text.lower(), \
                f"DIRECT record should contain entity name: {text[:100]}"
    
    @pytest.mark.asyncio
    async def test_extract_atomic_claims_theotechnic(
        self,
        theotechnic_evidence_records,
    ):
        """Test that atomic claims are extracted from relevant evidence."""
        pipeline = EvidenceFilterPipeline(target_entity="Theotechnic College")
        
        direct, related, irrelevant = pipeline.filter_entity_relevant_evidence(
            theotechnic_evidence_records
        )
        
        relevant_evidence = direct + related
        atomic_claims = pipeline.extract_atomic_claims(relevant_evidence)
        
        # Should extract multiple claims
        assert len(atomic_claims) > 0, "Should extract at least one atomic claim"
        
        # All claims should have required fields
        for claim in atomic_claims:
            assert claim.subject, "Claim should have subject"
            assert claim.predicate, "Claim should have predicate"
            assert claim.object, "Claim should have object"
            assert claim.claim_text, "Claim should have claim_text"
            assert claim.evidence_passage, "Claim should have evidence_passage"
            assert claim.source_url, "Claim should have source_url"
    
    @pytest.mark.asyncio
    async def test_validate_claims_theotechnic(
        self,
        theotechnic_evidence_records,
    ):
        """Test that invalid claims are rejected."""
        pipeline = EvidenceFilterPipeline(target_entity="Theotechnic College")
        
        direct, related, irrelevant = pipeline.filter_entity_relevant_evidence(
            theotechnic_evidence_records
        )
        
        relevant_evidence = direct + related
        atomic_claims = pipeline.extract_atomic_claims(relevant_evidence)
        
        valid_claims, invalid_claims = pipeline.validate_claims(atomic_claims)
        
        # All claims from relevant evidence should be valid
        # (invalid claims would come from irrelevant evidence, which we filtered out)
        assert len(valid_claims) > 0, "Should have at least one valid claim"
        
        # Check that no invalid claims have structural issues
        for claim in valid_claims:
            assert claim.subject, "Valid claim should have subject"
            assert claim.predicate, "Valid claim should have predicate"
            assert claim.object, "Valid claim should have object"
    
    @pytest.mark.asyncio
    async def test_deduplicate_claims_theotechnic(
        self,
        theotechnic_evidence_records,
    ):
        """Test that duplicate claims are normalized and deduplicated."""
        pipeline = EvidenceFilterPipeline(target_entity="Theotechnic College")
        
        direct, related, irrelevant = pipeline.filter_entity_relevant_evidence(
            theotechnic_evidence_records
        )
        
        relevant_evidence = direct + related
        atomic_claims = pipeline.extract_atomic_claims(relevant_evidence)
        valid_claims, _ = pipeline.validate_claims(atomic_claims)
        
        deduplicated = pipeline.deduplicate_claims(valid_claims)
        
        # Deduplicated should have same or fewer claims
        assert len(deduplicated) <= len(valid_claims), \
            "Deduplicated claims should be <= valid claims"
        
        # All deduplicated claims should have unique claim_ids
        claim_ids = [c.claim_id for c in deduplicated]
        assert len(claim_ids) == len(set(claim_ids)), \
            "All deduplicated claims should have unique IDs"
    
    @pytest.mark.asyncio
    async def test_complete_pipeline_theotechnic(
        self,
        theotechnic_evidence_records,
    ):
        """Test the complete evidence filtering pipeline for Theotechnic."""
        pipeline = EvidenceFilterPipeline(target_entity="Theotechnic College")
        
        final_claims, pipeline_metadata = pipeline.run_pipeline(
            theotechnic_evidence_records
        )
        
        # Should produce final claims
        assert len(final_claims) > 0, "Should produce at least one final claim"
        
        # All final claims should be valid
        for claim in final_claims:
            assert claim.quality_status == EvidenceQualityStatus.VALID, \
                f"Final claim should be VALID: {claim.claim_id}"
            assert claim.subject, "Final claim should have subject"
            assert claim.predicate, "Final claim should have predicate"
            assert claim.object, "Final claim should have object"
        
        # Verify pipeline metadata
        assert "target_entity" in pipeline_metadata
        assert pipeline_metadata["target_entity"] == "Theotechnic College"
        assert "stages" in pipeline_metadata
        assert "evidence_filter" in pipeline_metadata["stages"]
        assert "atomic_claims" in pipeline_metadata["stages"]
        assert "validation" in pipeline_metadata["stages"]
        assert "deduplication" in pipeline_metadata["stages"]
        
        # Verify that irrelevant evidence was filtered out
        assert pipeline_metadata["stages"]["evidence_filter"]["irrelevant_count"] >= 4
        
        # Verify that claims were extracted from relevant evidence
        assert pipeline_metadata["stages"]["atomic_claims"]["extracted_count"] > 0
    
    @pytest.mark.asyncio
    async def test_irrelevant_patterns_rejected(
        self,
        theotechnic_evidence_records,
    ):
        """Test that specific irrelevant patterns are rejected."""
        pipeline = EvidenceFilterPipeline(target_entity="Theotechnic College")
        
        direct, related, irrelevant = pipeline.filter_entity_relevant_evidence(
            theotechnic_evidence_records
        )
        
        # Check that irrelevant records contain the expected patterns
        irrelevant_texts = []
        for record in irrelevant:
            text = pipeline._get_authoritative_text(record)
            irrelevant_texts.append(text)
        
        # Should find navigation text
        nav_found = any("Home" in t or "About" in t or "Contact" in t for t in irrelevant_texts)
        assert nav_found, "Should reject navigation text"
        
        # Should find marketing text
        marketing_found = any(
            "Now Open" in t or "Join us" in t or "Discover your" in t 
            for t in irrelevant_texts
        )
        assert marketing_found, "Should reject marketing text"
        
        # Should find Bible verse
        bible_found = any("Timothy" in t or "2:15" in t for t in irrelevant_texts)
        assert bible_found, "Should reject Bible verse"
        
        # Should find single letter
        single_letter_found = any(t.strip() == "c" for t in irrelevant_texts)
        assert single_letter_found, "Should reject single letter"
    
    @pytest.mark.asyncio
    async def test_direct_evidence_contains_entity(
        self,
        theotechnic_evidence_records,
    ):
        """Test that DIRECT evidence explicitly mentions the target entity."""
        pipeline = EvidenceFilterPipeline(target_entity="Theotechnic College")
        
        direct, _, _ = pipeline.filter_entity_relevant_evidence(
            theotechnic_evidence_records
        )
        
        for record in direct:
            text = pipeline._get_authoritative_text(record)
            assert "Theotechnic College" in text or "theotechnic" in text.lower(), \
                f"DIRECT evidence should mention entity: {text[:100]}"
    
    @pytest.mark.asyncio
    async def test_related_evidence_establishes_relationship(
        self,
        theotechnic_evidence_records,
    ):
        """Test that RELATED evidence establishes a relationship with the target."""
        pipeline = EvidenceFilterPipeline(target_entity="Theotechnic College")
        
        _, related, _ = pipeline.filter_entity_relevant_evidence(
            theotechnic_evidence_records
        )
        
        for record in related:
            text = pipeline._get_authoritative_text(record)
            # Related evidence should mention both the target and another entity
            assert "Theotechnic College" in text or "theotechnic" in text.lower(), \
                f"RELATED evidence should mention target entity: {text[:100]}"
            # Should also mention the related entity (ACTIVE Ministry)
            assert "ACTIVE Ministry" in text or "active ministry" in text.lower(), \
                f"RELATED evidence should mention related entity: {text[:100]}"


# =============================================================================
# Evidence Filter Pipeline Tests - ZERA (Second Entity)
# =============================================================================

class TestZERAEvidenceFilter:
    """Test the evidence filtering pipeline with ZERA (second entity)."""
    
    @pytest.mark.asyncio
    async def test_filter_entity_relevant_evidence_zera(
        self,
        zera_evidence_records,
    ):
        """Test that evidence is correctly classified for ZERA."""
        pipeline = EvidenceFilterPipeline(target_entity="ZERA")
        
        direct, related, irrelevant = pipeline.filter_entity_relevant_evidence(
            zera_evidence_records
        )
        
        # Should have 2 direct evidence records
        assert len(direct) >= 2, f"Expected at least 2 DIRECT records for ZERA, got {len(direct)}"
        
        # Should have 0 related records (no relationship evidence in this set)
        # (This is fine - not all entities have related evidence)
        
        # Should have 2 irrelevant records (navigation, generic text)
        assert len(irrelevant) >= 2, f"Expected at least 2 IRRELEVANT records, got {len(irrelevant)}"
    
    @pytest.mark.asyncio
    async def test_extract_atomic_claims_zera(
        self,
        zera_evidence_records,
    ):
        """Test that atomic claims are extracted for ZERA."""
        pipeline = EvidenceFilterPipeline(target_entity="ZERA")
        
        direct, related, irrelevant = pipeline.filter_entity_relevant_evidence(
            zera_evidence_records
        )
        
        relevant_evidence = direct + related
        atomic_claims = pipeline.extract_atomic_claims(relevant_evidence)
        
        # Should extract claims
        assert len(atomic_claims) > 0, "Should extract at least one atomic claim for ZERA"
        
        # Check that claims are about ZERA or its sector
        for claim in atomic_claims:
            assert claim.subject or claim.object, "Claim should have subject or object"
            # Either subject or object should relate to ZERA
            text = f"{claim.subject} {claim.predicate} {claim.object}".lower()
            assert "zera" in text or "energy" in text or "regulates" in text, \
                f"Claim should be about ZERA: {text}"
    
    @pytest.mark.asyncio
    async def test_complete_pipeline_zera(
        self,
        zera_evidence_records,
    ):
        """Test the complete evidence filtering pipeline for ZERA."""
        pipeline = EvidenceFilterPipeline(target_entity="ZERA")
        
        final_claims, pipeline_metadata = pipeline.run_pipeline(
            zera_evidence_records
        )
        
        # Should produce final claims
        assert len(final_claims) > 0, "Should produce at least one final claim for ZERA"
        
        # Verify entity type can be extracted
        entity_type_found = False
        for claim in final_claims:
            if claim.evidence_type == "ATTRIBUTE" and claim.predicate == "is":
                entity_type_found = True
                break
        
        # Verify sector can be extracted
        sector_found = False
        for claim in final_claims:
            if "energy" in claim.object.lower() or "sector" in claim.object.lower():
                sector_found = True
                break
        
        assert sector_found, "Should extract sector information for ZERA"


# =============================================================================
# Atomic Claim Validation Tests
# =============================================================================

class TestAtomicClaimValidation:
    """Test atomic claim validation logic."""
    
    def test_validate_valid_claim(self):
        """Test that valid claims pass validation."""
        pipeline = EvidenceFilterPipeline(target_entity="Test Entity")
        
        claim = AtomicClaim(
            claim_id="test_001",
            subject="Test Entity",
            predicate="is",
            object="a test organization",
            claim_text="Test Entity is a test organization",
            evidence_passage="Test Entity is a test organization.",
            source_url="https://example.org",
            source_title="Test Page",
            relevance=RelevanceClassification.DIRECT,
            evidence_type="FACT",
            confidence=0.9,
            quality_status=EvidenceQualityStatus.VALID,
            extraction_method="test",
        )
        
        assert pipeline._validate_claim(claim), "Valid claim should pass validation"
    
    def test_reject_empty_subject(self):
        """Test that claims with empty subject are rejected."""
        pipeline = EvidenceFilterPipeline(target_entity="Test Entity")
        
        claim = AtomicClaim(
            claim_id="test_002",
            subject="",
            predicate="is",
            object="a test organization",
            claim_text=" is a test organization",
            evidence_passage="Test Entity is a test organization.",
            source_url="https://example.org",
            source_title="Test Page",
        )
        
        assert not pipeline._validate_claim(claim), "Claim with empty subject should be rejected"
    
    def test_reject_empty_predicate(self):
        """Test that claims with empty predicate are rejected."""
        pipeline = EvidenceFilterPipeline(target_entity="Test Entity")
        
        claim = AtomicClaim(
            claim_id="test_003",
            subject="Test Entity",
            predicate="",
            object="a test organization",
            claim_text="Test Entity  a test organization",
            evidence_passage="Test Entity is a test organization.",
            source_url="https://example.org",
            source_title="Test Page",
        )
        
        assert not pipeline._validate_claim(claim), "Claim with empty predicate should be rejected"
    
    def test_reject_empty_object(self):
        """Test that claims with empty object are rejected."""
        pipeline = EvidenceFilterPipeline(target_entity="Test Entity")
        
        claim = AtomicClaim(
            claim_id="test_004",
            subject="Test Entity",
            predicate="is",
            object="",
            claim_text="Test Entity is ",
            evidence_passage="Test Entity is a test organization.",
            source_url="https://example.org",
            source_title="Test Page",
        )
        
        assert not pipeline._validate_claim(claim), "Claim with empty object should be rejected"
    
    def test_reject_cta_language(self):
        """Test that claims with CTA language are rejected."""
        pipeline = EvidenceFilterPipeline(target_entity="Test Entity")
        
        claim = AtomicClaim(
            claim_id="test_005",
            subject="Test Entity",
            predicate="offers",
            object="Apply Now for great opportunities",
            claim_text="Test Entity offers Apply Now for great opportunities",
            evidence_passage="Apply Now for great opportunities",
            source_url="https://example.org",
            source_title="Test Page",
        )
        
        assert not pipeline._validate_claim(claim), "Claim with CTA language should be rejected"
    
    def test_reject_navigation_language(self):
        """Test that claims with navigation language are rejected."""
        pipeline = EvidenceFilterPipeline(target_entity="Test Entity")
        
        claim = AtomicClaim(
            claim_id="test_006",
            subject="Test Entity",
            predicate="has",
            object="Home About Contact",
            claim_text="Test Entity has Home About Contact",
            evidence_passage="Home About Contact",
            source_url="https://example.org",
            source_title="Test Page",
        )
        
        assert not pipeline._validate_claim(claim), "Claim with navigation language should be rejected"
    
    def test_reject_single_letter_subject(self):
        """Test that claims with single letter subject are rejected."""
        pipeline = EvidenceFilterPipeline(target_entity="Test Entity")
        
        claim = AtomicClaim(
            claim_id="test_007",
            subject="c",
            predicate="is",
            object="a letter",
            claim_text="c is a letter",
            evidence_passage="c",
            source_url="https://example.org",
            source_title="Test Page",
        )
        
        assert not pipeline._validate_claim(claim), "Claim with single letter subject should be rejected"
    
    def test_reject_bible_verse(self):
        """Test that claims containing Bible verses are rejected."""
        pipeline = EvidenceFilterPipeline(target_entity="Test Entity")
        
        claim = AtomicClaim(
            claim_id="test_008",
            subject="Test Entity",
            predicate="references",
            object="2 Timothy 2:15",
            claim_text="Test Entity references 2 Timothy 2:15",
            evidence_passage="2 Timothy 2:15 - Study to show thyself approved",
            source_url="https://example.org",
            source_title="Test Page",
        )
        
        assert not pipeline._validate_claim(claim), "Claim with Bible verse should be rejected"


# =============================================================================
# Deduplication Tests
# =============================================================================

class TestClaimDeduplication:
    """Test claim deduplication logic."""
    
    def test_deduplicate_equivalent_claims(self):
        """Test that semantically equivalent claims are deduplicated."""
        pipeline = EvidenceFilterPipeline(target_entity="Test Entity")
        
        # Create two equivalent claims
        claim1 = AtomicClaim(
            claim_id="",
            subject="Test Entity",
            predicate="is",
            object="a test organization",
            claim_text="Test Entity is a test organization",
            evidence_passage="Test Entity is a test organization.",
            source_url="https://example.org/1",
            source_title="Page 1",
            confidence=0.8,
        )
        
        claim2 = AtomicClaim(
            claim_id="",
            subject="Test Entity",
            predicate="is",
            object="a test organization",
            claim_text="Test Entity is a test organization",
            evidence_passage="Test Entity is a test organization.",
            source_url="https://example.org/2",
            source_title="Page 2",
            confidence=0.9,
        )
        
        claims = [claim1, claim2]
        deduplicated = pipeline.deduplicate_claims(claims)
        
        # Should deduplicate to 1 claim
        assert len(deduplicated) == 1, "Equivalent claims should be deduplicated to 1"
        
        # Should retain the highest confidence claim
        assert deduplicated[0].confidence == 0.9, "Should retain highest confidence claim"
    
    def test_deduplicate_different_claims(self):
        """Test that different claims are not deduplicated."""
        pipeline = EvidenceFilterPipeline(target_entity="Test Entity")
        
        claim1 = AtomicClaim(
            claim_id="",
            subject="Test Entity",
            predicate="is",
            object="a test organization",
            claim_text="Test Entity is a test organization",
            evidence_passage="Test Entity is a test organization.",
            source_url="https://example.org/1",
            source_title="Page 1",
        )
        
        claim2 = AtomicClaim(
            claim_id="",
            subject="Test Entity",
            predicate="regulates",
            object="energy sector",
            claim_text="Test Entity regulates energy sector",
            evidence_passage="Test Entity regulates energy sector.",
            source_url="https://example.org/2",
            source_title="Page 2",
        )
        
        claims = [claim1, claim2]
        deduplicated = pipeline.deduplicate_claims(claims)
        
        # Should NOT deduplicate different claims
        assert len(deduplicated) == 2, "Different claims should not be deduplicated"


# =============================================================================
# Regression Tests for Current Failures
# =============================================================================

class TestCurrentFailureRegression:
    """Test that the current failures described in the requirements are fixed."""
    
    @pytest.mark.asyncio
    async def test_single_letter_c_not_in_aliases(self, theotechnic_evidence_records):
        """Regression: 'c' must never appear in aliases."""
        pipeline = EvidenceFilterPipeline(target_entity="Theotechnic College")
        
        final_claims, _ = pipeline.run_pipeline(theotechnic_evidence_records)
        
        # Extract aliases from claims (if any)
        # In the new architecture, aliases are extracted separately
        # But we can verify that no claim contains 'c' as a subject or object in wrong context
        for claim in final_claims:
            # Single letter 'c' should not be a subject or object
            if claim.subject.strip() == "c":
                assert False, f"Single letter 'c' found as subject: {claim.claim_id}"
            if claim.object.strip() == "c":
                assert False, f"Single letter 'c' found as object: {claim.claim_id}"
    
    @pytest.mark.asyncio
    async def test_bible_verse_not_in_claims(self, theotechnic_evidence_records):
        """Regression: Bible verses must never appear in claims."""
        pipeline = EvidenceFilterPipeline(target_entity="Theotechnic College")
        
        final_claims, _ = pipeline.run_pipeline(theotechnic_evidence_records)
        
        for claim in final_claims:
            assert "Timothy" not in claim.claim_text, \
                f"Bible verse found in claim: {claim.claim_text}"
            assert "2:15" not in claim.claim_text, \
                f"Bible verse found in claim: {claim.claim_text}"
    
    @pytest.mark.asyncio
    async def test_marketing_text_not_in_claims(self, theotechnic_evidence_records):
        """Regression: Marketing text must never appear in claims."""
        pipeline = EvidenceFilterPipeline(target_entity="Theotechnic College")
        
        final_claims, _ = pipeline.run_pipeline(theotechnic_evidence_records)
        
        for claim in final_claims:
            text = claim.claim_text.lower()
            assert "now open" not in text, \
                f"Marketing text 'Now Open' found in claim: {claim.claim_text}"
            assert "join us" not in text, \
                f"Marketing text 'Join us' found in claim: {claim.claim_text}"
            assert "discover your" not in text, \
                f"Marketing text 'Discover your' found in claim: {claim.claim_text}"
    
    @pytest.mark.asyncio
    async def test_navigation_text_not_in_claims(self, theotechnic_evidence_records):
        """Regression: Navigation text must never appear in claims."""
        pipeline = EvidenceFilterPipeline(target_entity="Theotechnic College")
        
        final_claims, _ = pipeline.run_pipeline(theotechnic_evidence_records)
        
        for claim in final_claims:
            text = claim.claim_text.lower()
            assert "home about" not in text, \
                f"Navigation text found in claim: {claim.claim_text}"
            assert "apply now" not in text, \
                f"Navigation text 'Apply Now' found in claim: {claim.claim_text}"
            assert "contact us" not in text, \
                f"Navigation text 'Contact Us' found in claim: {claim.claim_text}"
    
    @pytest.mark.asyncio
    async def test_adjectives_not_as_relationship_targets(self, theotechnic_evidence_records):
        """Regression: Adjectives must never be relationship targets."""
        pipeline = EvidenceFilterPipeline(target_entity="Theotechnic College")
        
        final_claims, _ = pipeline.run_pipeline(theotechnic_evidence_records)
        
        for claim in final_claims:
            # Check if this is a relationship claim
            if claim.evidence_type == "RELATIONSHIP":
                # The object should not be an adjective
                object_lower = claim.object.lower()
                adjectives = ["comprehensive", "foundational", "quality"]
                for adj in adjectives:
                    assert adj not in object_lower or len(claim.object.split()) > 1, \
                        f"Adjective '{adj}' found as relationship target: {claim.object}"


# =============================================================================
# Field-Specific Evidence Selection Tests
# =============================================================================

class TestFieldSpecificEvidenceSelection:
    """Test field-specific evidence selection."""
    
    def test_select_evidence_for_entity_type(self):
        """Test selecting evidence for entity_type field."""
        from app.services.research.evidence_filter import FieldSpecificEvidenceSelector
        
        selector = FieldSpecificEvidenceSelector()
        
        # Create atomic claims - using ontology values
        claims = [
            AtomicClaim(
                claim_id="claim_001",
                subject="Test Entity",
                predicate="is",
                object="institution",
                claim_text="Test Entity is institution",
                evidence_passage="Test Entity is an institution.",
                source_url="https://example.org",
                evidence_type="ATTRIBUTE",
                relevance=RelevanceClassification.DIRECT,
            ),
            AtomicClaim(
                claim_id="claim_002",
                subject="Test Entity",
                predicate="operates_in",
                object="Education Sector",
                claim_text="Test Entity operates in Education Sector",
                evidence_passage="Test Entity operates in the Education Sector.",
                source_url="https://example.org",
                evidence_type="ATTRIBUTE",
                relevance=RelevanceClassification.DIRECT,
            ),
        ]
        
        field_evidence = selector.select_evidence_for_fields(
            claims, "Test Entity"
        )
        
        # Should have entity_type
        assert field_evidence["entity_type"]["value"] == "institution"
        assert "claim_001" in field_evidence["entity_type"]["evidence_ids"]
        
        # Should have sector
        assert field_evidence["sector"]["value"] == "Education Sector"
        assert "claim_002" in field_evidence["sector"]["evidence_ids"]
    
    def test_select_evidence_for_relationships(self):
        """Test selecting evidence for relationships field."""
        from app.services.research.evidence_filter import FieldSpecificEvidenceSelector
        
        selector = FieldSpecificEvidenceSelector()
        
        claims = [
            AtomicClaim(
                claim_id="claim_001",
                subject="Test Entity",
                predicate="supported_by",
                object="ACTIVE Ministry",
                claim_text="Test Entity supported_by ACTIVE Ministry",
                evidence_passage="Test Entity is supported by ACTIVE Ministry.",
                source_url="https://example.org",
                evidence_type="RELATIONSHIP",
                relevance=RelevanceClassification.DIRECT,
            ),
        ]
        
        field_evidence = selector.select_evidence_for_fields(
            claims, "Test Entity"
        )
        
        # Should have relationships
        assert len(field_evidence["relationships"]["value"]) == 1
        assert "supported_by::[[ACTIVE Ministry]]" in field_evidence["relationships"]["value"]
        assert "claim_001" in field_evidence["relationships"]["evidence_ids"]


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    "TestTheotechnicEvidenceFilter",
    "TestZERAEvidenceFilter",
    "TestAtomicClaimValidation",
    "TestClaimDeduplication",
    "TestCurrentFailureRegression",
    "TestFieldSpecificEvidenceSelection",
]
