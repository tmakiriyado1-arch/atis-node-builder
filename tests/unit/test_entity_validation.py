"""Tests for entity validation and semantic mismatch detection."""
import pytest

from app.services.entity_resolution.validator import (
    CandidateStatus,
    CandidateValidation,
    EntityResolution,
    EntityValidator,
    RejectionReason,
)


class TestEntityValidator:
    """Test entity validation."""

    def test_exact_match(self):
        """Test exact name match is accepted."""
        validator = EntityValidator()
        validation = validator.validate_candidate(
            candidate_id="Q123",
            candidate_name="Zimbabwe Energy Regulatory Authority",
            requested_entity="Zimbabwe Energy Regulatory Authority",
        )
        
        assert validation.status == CandidateStatus.ACCEPTED
        assert validation.confidence == 1.0

    def test_acronym_match(self):
        """Test acronym match."""
        validator = EntityValidator()
        validation = validator.validate_candidate(
            candidate_id="Q456",
            candidate_name="ZERA",
            requested_entity="Zimbabwe Energy Regulatory Authority (ZERA)",
        )
        
        # Should have some confidence from acronym match
        assert validation.confidence > 0

    def test_semantic_mismatch_biological(self):
        """Test that biological entity is rejected for organization query."""
        validator = EntityValidator()
        validation = validator.validate_candidate(
            candidate_id="Q1761087",
            candidate_name="Zera",
            candidate_description="genus of insects",
            requested_entity="Zimbabwe Energy Regulatory Authority",
            entity_type="organization",
        )
        
        assert validation.status == CandidateStatus.REJECTED
        assert validation.rejection_reason == RejectionReason.SEMANTIC_MISMATCH

    def test_semantic_mismatch_genus_vs_authority(self):
        """Test genus vs authority semantic mismatch."""
        validator = EntityValidator()
        validation = validator.validate_candidate(
            candidate_id="Q1761087",
            candidate_name="Zera",
            candidate_description="genus of insects",
            requested_entity="Zimbabwe Energy Regulatory Authority (ZERA)",
            entity_type="organization",
        )
        
        assert validation.status == CandidateStatus.REJECTED
        non_matching = [t for t in validation.non_matching_terms if "mismatch" in t]
        assert len(non_matching) > 0

    def test_organization_keywords_match(self):
        """Test that organization keywords increase confidence."""
        validator = EntityValidator()
        validation = validator.validate_candidate(
            candidate_id="Q789",
            candidate_name="Zimbabwe Energy Regulatory Authority",
            candidate_description="regulatory body for energy sector",
            requested_entity="Zimbabwe Energy Regulatory Authority",
            entity_type="organization",
        )
        
        assert validation.status == CandidateStatus.ACCEPTED
        assert validation.confidence > 0.5

    def test_country_context_match(self):
        """Test that country context increases confidence."""
        validator = EntityValidator()
        validation = validator.validate_candidate(
            candidate_id="Q101",
            candidate_name="ZERA",
            candidate_description="Energy Regulatory Authority",
            requested_entity="Zimbabwe Energy Regulatory Authority",
            entity_type="organization",
            context={"country": "Zimbabwe"},
        )
        
        # Should have higher confidence due to country match
        assert validation.confidence > 0

    def test_metadata_compatibility(self):
        """Test metadata compatibility checking."""
        validator = EntityValidator()
        validation = validator.validate_candidate(
            candidate_id="Q111",
            candidate_name="ZERA",
            candidate_metadata={
                "instance_of": "regulatory authority",
                "country": "Zimbabwe",
            },
            requested_entity="Zimbabwe Energy Regulatory Authority",
            entity_type="organization",
            context={"country": "Zimbabwe"},
        )
        
        assert validation.status == CandidateStatus.ACCEPTED

    def test_instance_of_mismatch(self):
        """Test instance_of mismatch (genus vs organization)."""
        validator = EntityValidator()
        validation = validator.validate_candidate(
            candidate_id="Q1761087",
            candidate_name="Zera",
            candidate_metadata={"instance_of": "genus"},
            requested_entity="Zimbabwe Energy Regulatory Authority",
            entity_type="organization",
        )
        
        assert validation.status == CandidateStatus.REJECTED

    def test_wikidata_q1761087_explicit_rejection(self):
        """Test explicit rejection of Q1761087 (Zera genus of insects)."""
        validator = EntityValidator()
        validation = validator.validate_candidate(
            candidate_id="Q1761087",
            candidate_name="Zera",
            candidate_description="genus of insects",
            candidate_metadata={"instance_of": "genus"},
            requested_entity="Zimbabwe Energy Regulatory Authority (ZERA)",
            entity_type="organization",
        )
        
        assert validation.status == CandidateStatus.REJECTED
        assert validation.rejection_reason == RejectionReason.SEMANTIC_MISMATCH
        assert "insects" in validation.rejection_details.lower() or \
               "genus" in validation.rejection_details.lower()


class TestEntityResolution:
    """Test complete entity resolution."""

    def test_resolve_with_accepted_candidate(self):
        """Test resolution with accepted candidate."""
        validator = EntityValidator()
        candidates = [
            {
                "id": "Q123",
                "name": "Zimbabwe Energy Regulatory Authority",
                "description": "Energy regulatory body in Zimbabwe",
                "metadata": {"instance_of": "regulatory authority"},
            }
        ]
        
        resolution = validator.resolve_entity(
            requested_entity="Zimbabwe Energy Regulatory Authority",
            candidates=candidates,
            entity_type="organization",
        )
        
        assert resolution.status == "RESOLVED"
        assert resolution.resolved_entity == "Zimbabwe Energy Regulatory Authority"
        assert len(resolution.accepted_candidates) == 1
        assert len(resolution.rejected_candidates) == 0

    def test_resolve_with_rejected_candidate(self):
        """Test resolution with rejected candidate."""
        validator = EntityValidator()
        candidates = [
            {
                "id": "Q1761087",
                "name": "Zera",
                "description": "genus of insects",
                "metadata": {"instance_of": "genus"},
            }
        ]
        
        resolution = validator.resolve_entity(
            requested_entity="Zimbabwe Energy Regulatory Authority",
            candidates=candidates,
            entity_type="organization",
        )
        
        assert resolution.status == "REJECTED"
        assert len(resolution.accepted_candidates) == 0
        assert len(resolution.rejected_candidates) == 1

    def test_resolve_with_mixed_candidates(self):
        """Test resolution with both accepted and rejected candidates."""
        validator = EntityValidator()
        candidates = [
            {
                "id": "Q123",
                "name": "Zimbabwe Energy Regulatory Authority",
                "description": "Energy regulatory body in Zimbabwe",
                "metadata": {"instance_of": "regulatory authority"},
            },
            {
                "id": "Q1761087",
                "name": "Zera",
                "description": "genus of insects",
                "metadata": {"instance_of": "genus"},
            }
        ]
        
        resolution = validator.resolve_entity(
            requested_entity="Zimbabwe Energy Regulatory Authority",
            candidates=candidates,
            entity_type="organization",
        )
        
        assert resolution.status == "RESOLVED"
        assert len(resolution.accepted_candidates) == 1
        assert len(resolution.rejected_candidates) == 1
        assert resolution.rejected_candidates[0].candidate_id == "Q1761087"

    def test_resolve_ambiguous(self):
        """Test resolution with ambiguous candidates."""
        validator = EntityValidator()
        candidates = [
            {
                "id": "Q111",
                "name": "ZERA",
                "description": "Energy authority",
            },
            {
                "id": "Q222",
                "name": "ZERA",
                "description": "Different energy authority",
            }
        ]
        
        resolution = validator.resolve_entity(
            requested_entity="ZERA",
            candidates=candidates,
        )
        
        # Should be either AMBIGUOUS or UNRESOLVED depending on confidence
        assert resolution.status in ["AMBIGUOUS", "UNRESOLVED"]

    def test_resolve_no_candidates(self):
        """Test resolution with no candidates."""
        validator = EntityValidator()
        resolution = validator.resolve_entity(
            requested_entity="Zimbabwe Energy Regulatory Authority",
            candidates=[],
        )
        
        assert resolution.status == "UNRESOLVED"


class TestValidationReport:
    """Test validation report serialization."""

    def test_candidate_validation_to_dict(self):
        """Test candidate validation serialization."""
        validation = CandidateValidation(
            candidate_id="Q123",
            candidate_name="Test Entity",
            candidate_description="Test description",
            status=CandidateStatus.ACCEPTED,
            confidence=0.9,
        )
        
        result = validation.to_dict()
        assert result["candidate_id"] == "Q123"
        assert result["status"] == "accepted"
        assert result["confidence"] == 0.9

    def test_entity_resolution_to_dict(self):
        """Test entity resolution serialization."""
        resolution = EntityResolution(
            requested_entity="Test Entity",
            resolved_entity="Resolved Entity",
            status="RESOLVED",
        )
        
        result = resolution.to_dict()
        assert result["requested_entity"] == "Test Entity"
        assert result["resolved_entity"] == "Resolved Entity"
        assert result["status"] == "RESOLVED"


class TestRejectionReasons:
    """Test rejection reasons."""

    def test_all_rejection_reasons_exist(self):
        """Test that all expected rejection reasons exist."""
        expected_reasons = [
            "semantic_mismatch",
            "type_mismatch",
            "country_mismatch",
            "sector_mismatch",
            "domain_mismatch",
            "low_confidence",
            "no_evidence",
            "contradictory_evidence",
        ]
        
        for reason in expected_reasons:
            assert hasattr(RejectionReason, reason.upper())


class TestCandidateStatus:
    """Test candidate status values."""

    def test_all_statuses_exist(self):
        """Test that all expected statuses exist."""
        expected_statuses = ["accepted", "rejected", "ambiguous", "pending"]
        
        for status in expected_statuses:
            assert hasattr(CandidateStatus, status.upper())
