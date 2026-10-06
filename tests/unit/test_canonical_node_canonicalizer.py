"""Tests for Canonical Node Canonicalizer.

These tests verify that:
1. Raw webpage text is NOT treated as canonical node data
2. All fields are validated against the ontology
3. Backlinks point to resolvable entities
4. Missing fields remain None (not hallucinated)
5. The Theotechnic College regression case passes
"""
from __future__ import annotations

import pytest

from app.services.canonical_node_canonicalizer import (
    CanonicalNodeCanonicalizer,
    CanonicalNodeValidator,
    EvidenceBundle,
    ExtractedClaim,
    FieldValidator,
    BacklinkValidator,
    ValidationError,
    ValidationResult,
)
from app.models import CanonicalNodeRow


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def ontology():
    from app.services.ontology import get_ontology
    return get_ontology()


@pytest.fixture
def field_validator(ontology):
    return FieldValidator()


@pytest.fixture
def canonicalizer(ontology):
    return CanonicalNodeCanonicalizer()


@pytest.fixture
def validator(ontology):
    return CanonicalNodeValidator()


# =============================================================================
# Backlink Validator Tests
# =============================================================================

class TestBacklinkValidator:
    """Test backlink validation."""
    
    def test_valid_backlink_targets(self, ontology):
        validator = BacklinkValidator()
        
        # Valid: known ontology concepts
        assert validator.is_valid_backlink_target("Zimbabwe")
        assert validator.is_valid_backlink_target("Energy Sector")
        assert validator.is_valid_backlink_target("ACTIVE Ministry")
        
        # Valid: proper nouns
        assert validator.is_valid_backlink_target("Theotechnic College")
        assert validator.is_valid_backlink_target("ACTIVE Ministry")
    
    def test_invalid_backlink_targets(self, ontology):
        validator = BacklinkValidator()
        
        # Invalid: sentence fragments
        assert not validator.is_valid_backlink_target("Now Open! All applicants will be placed on a prospective list")
        assert not validator.is_valid_backlink_target("STUDENTSYour Journey of Faith and Learning Begins Here")
        
        # Invalid: single letters
        assert not validator.is_valid_backlink_target("c")
        assert not validator.is_valid_backlink_target("a")
        
        # Invalid: Bible verses
        assert not validator.is_valid_backlink_target("2 Timothy 2:15")
        
        # Invalid: CTA text
        assert not validator.is_valid_backlink_target("Apply Now")
        assert not validator.is_valid_backlink_target("Click Here")
        
        # Invalid: navigation text
        assert not validator.is_valid_backlink_target("About Us")
        assert not validator.is_valid_backlink_target("Contact Us")
        
        # Invalid: excessively long
        long_text = "A" * 200
        assert not validator.is_valid_backlink_target(long_text)
    
    def test_validate_backlink_format(self, ontology):
        validator = BacklinkValidator()
        
        # Valid format
        result = validator.validate_backlink("[[ACTIVE Ministry]]")
        assert result.is_valid
        
        # Invalid format
        result = validator.validate_backlink("ACTIVE Ministry")
        assert not result.is_valid
        assert "Invalid backlink format" in result.errors[0]
    
    def test_validate_text_for_invalid_backlinks(self, ontology):
        validator = BacklinkValidator()
        
        # Text with valid backlinks
        result = validator.validate_text_for_invalid_backlinks(
            "[[Theotechnic College]] is supported by [[ACTIVE Ministry]]"
        )
        assert result.is_valid
        
        # Text with invalid backlinks
        result = validator.validate_text_for_invalid_backlinks(
            "[[Theotechnic College]] provides [[Comprehensive]] education"
        )
        assert not result.is_valid
        assert any("Comprehensive" in e for e in result.errors)


# =============================================================================
# Field Validator Tests
# =============================================================================

class TestFieldValidator:
    """Test individual field validation."""
    
    def test_validate_uid(self, field_validator):
        # Valid UID
        result = field_validator.validate_uid("theotechnic-college", "Theotechnic College")
        assert result.is_valid
        
        # Invalid: does not match entity
        result = field_validator.validate_uid("wrong-uid", "Theotechnic College")
        assert not result.is_valid
        assert "does not match expected format" in result.errors[0]
        
        # Invalid: empty
        result = field_validator.validate_uid("", "Theotechnic College")
        assert not result.is_valid
    
    def test_validate_entity(self, field_validator):
        # Valid entity
        result = field_validator.validate_entity("Theotechnic College")
        assert result.is_valid
        
        # Invalid: sentence
        result = field_validator.validate_entity("Theotechnic College is great.")
        assert not result.is_valid
        assert "appears to be a sentence" in result.errors[0]
        
        # Invalid: empty
        result = field_validator.validate_entity("")
        assert not result.is_valid
    
    def test_validate_entity_type(self, field_validator):
        # Valid entity type
        result = field_validator.validate_entity_type("institution")
        assert result.is_valid
        
        # Invalid: not in ontology
        result = field_validator.validate_entity_type("Now Open! All applicants")
        assert not result.is_valid
        assert "Invalid entity_type" in result.errors[0]
        
        # None is valid
        result = field_validator.validate_entity_type(None)
        assert result.is_valid
    
    def test_validate_sector(self, field_validator):
        # Valid sector
        result = field_validator.validate_sector("Education Sector")
        assert result.is_valid
        
        # Invalid: not in ontology
        result = field_validator.validate_sector("Power")
        assert not result.is_valid
        assert "Invalid sector" in result.errors[0]
        
        # None is valid
        result = field_validator.validate_sector(None)
        assert result.is_valid
    
    def test_validate_country(self, field_validator):
        # Valid country
        result = field_validator.validate_country("Zimbabwe")
        assert result.is_valid
        
        # Invalid: not in ontology
        result = field_validator.validate_country("Mars")
        assert not result.is_valid
        assert "Invalid country" in result.errors[0]
        
        # None is valid
        result = field_validator.validate_country(None)
        assert result.is_valid
    
    def test_validate_status(self, field_validator):
        # Valid status
        result = field_validator.validate_status("active")
        assert result.is_valid
        
        # Invalid: not in ontology
        result = field_validator.validate_status("STUDENTSYour Journey")
        assert not result.is_valid
        assert "Invalid status" in result.errors[0]
        
        # None is valid
        result = field_validator.validate_status(None)
        assert result.is_valid
    
    def test_validate_aliases(self, field_validator):
        # Valid aliases
        result = field_validator.validate_aliases(["Theotechnic", "TC"])
        assert result.is_valid
        
        # Invalid: contains sentence
        result = field_validator.validate_aliases(["Now Open! All applicants"])
        assert not result.is_valid
        assert "is a sentence" in result.errors[0]
        
        # Invalid: contains Bible verse
        result = field_validator.validate_aliases(["2 Timothy 2:15"])
        assert not result.is_valid
        assert "is a Bible verse" in result.errors[0]
        
        # Invalid: single letter
        result = field_validator.validate_aliases(["c"])
        assert not result.is_valid
        assert "is a single letter" in result.errors[0]
    
    def test_validate_summary(self, field_validator):
        # Valid summary
        result = field_validator.validate_summary(
            "[[Theotechnic College]] is an educational institution.",
            "Theotechnic College",
            []
        )
        assert result.is_valid
        
        # Invalid: does not reference entity
        result = field_validator.validate_summary(
            "Some other organization does things.",
            "Theotechnic College",
            []
        )
        assert not result.is_valid
        assert "does not reference entity" in result.errors[0]
        
        # Invalid: contains CTA
        result = field_validator.validate_summary(
            "[[Theotechnic College]] Apply Now for admission.",
            "Theotechnic College",
            []
        )
        assert not result.is_valid
        assert "CTA text" in result.errors[0]
        
        # Invalid: too long
        long_summary = "word " * 600
        result = field_validator.validate_summary(
            long_summary,
            "Theotechnic College",
            []
        )
        assert not result.is_valid
        assert "too long" in result.errors[0]
    
    def test_validate_relationships(self, field_validator):
        # Valid relationship
        result = field_validator.validate_relationships(["supported_by::[[ACTIVE Ministry]]"])
        assert result.is_valid
        
        # Invalid: invalid format
        result = field_validator.validate_relationships(["provides Comprehensive"])
        assert not result.is_valid
        assert "Invalid relationship format" in result.errors[0]
        
        # Invalid: invalid predicate
        result = field_validator.validate_relationships(["provides::[[Comprehensive]]"])
        assert not result.is_valid
        assert "Invalid relationship predicate" in result.errors[0]
        
        # Invalid: invalid target
        result = field_validator.validate_relationships(["supported_by::[[Now Open! All applicants]]"])
        assert not result.is_valid
        assert "Invalid relationship target" in result.errors[0]
    
    def test_validate_associations(self, field_validator):
        # Valid association
        result = field_validator.validate_associations(["part_of::[[ACTIVE Ministry]]"])
        assert result.is_valid
        
        # Invalid: invalid target
        result = field_validator.validate_associations(["member_of::[[College Family Dedicates Themselves]]"])
        assert not result.is_valid
        assert "Invalid association target" in result.errors[0]
    
    def test_validate_sources(self, field_validator):
        # Valid sources
        result = field_validator.validate_sources(["https://example.com"])
        assert result.is_valid
        
        # Invalid: empty
        result = field_validator.validate_sources([])
        assert not result.is_valid
        assert "At least one source is required" in result.errors[0]
        
        # Invalid: non-URL
        result = field_validator.validate_sources(["not a url"])
        assert not result.is_valid
        assert "Invalid source URL" in result.errors[0]


# =============================================================================
# Canonical Node Validator Tests
# =============================================================================

class TestCanonicalNodeValidator:
    """Test full node validation."""
    
    def test_valid_node_passes(self, validator):
        row = CanonicalNodeRow(
            uid="theotechnic-college",
            entity="Theotechnic College",
            aliases=["Theotechnic"],
            entity_type="institution",
            subtype=None,
            country="Zimbabwe",
            sector="Education Sector",
            status="active",
            summary="[[Theotechnic College]] is a Christian higher-education and vocational training institution. It combines theological education with practical ministry training.",
            relationships=["supported_by::[[ACTIVE Ministry]]"],
            associations=["part_of::[[ACTIVE Ministry]]"],
            sources=["https://www.activeministry.org/theotechnic"],
        )
        
        result = validator.validate(row)
        
        assert result.is_valid
        assert len(result.errors) == 0
    
    def test_invalid_node_fails(self, validator):
        # Node with invalid fields from the problem description
        row = CanonicalNodeRow(
            uid="theotechnic-college",
            entity="Theotechnic College",
            aliases=["Now Open! All applicants will be placed on a prospective list"],
            entity_type="Now Open! All applicants will be placed on a prospective list...",
            subtype=None,
            country=None,
            sector="Power",  # Wrong sector for a college
            status="STUDENTSYour Journey of Faith and Learning Begins Here...",
            summary="[[Theotechnic College]] is Now Open!... [thousands of words]",
            relationships=["provides::[[Comprehensive]]", "provides::[[Foundational]]", "provides::[[Quality]]"],
            associations=["member_of::[[College Family Dedicates Themselves To The Great Commission...]]"],
            sources=["https://www.activeministry.org/theotechnic"],
        )
        
        result = validator.validate(row)
        
        assert not result.is_valid
        assert len(result.errors) > 0
        
        # Check for specific error patterns
        errors_str = " ".join(result.errors)
        assert "Invalid entity_type" in errors_str or "Invalid sector" in errors_str or "Invalid status" in errors_str
    
    def test_validate_and_raise(self, validator):
        row = CanonicalNodeRow(
            uid="invalid",
            entity="Invalid Entity",
            aliases=[],
            entity_type=None,
            subtype=None,
            country=None,
            sector=None,
            status=None,
            summary="No subject or function",
            relationships=[],
            associations=[],
            sources=["https://example.com"]
        )
        
        with pytest.raises(ValidationError):
            validator.validate_and_raise(row)


# =============================================================================
# Canonicalizer Tests
# =============================================================================

class TestCanonicalNodeCanonicalizer:
    """Test the full canonicalization pipeline."""
    
    def test_theotechnic_college_regression(self, canonicalizer, validator):
        """Test that Theotechnic College is canonicalized correctly.
        
        This is the primary regression test for the problem described.
        """
        # Create evidence bundle with Theotechnic College data
        evidence_bundle = EvidenceBundle(
            entity_name="Theotechnic College",
            entity_seed="Theotechnic College",
            claims=[
                ExtractedClaim(
                    claim_text="Theotechnic College is a Christian higher-education and vocational training institution",
                    field_name="summary",
                    source_urls=["https://www.activeministry.org/theotechnic"],
                    confidence=0.9,
                    is_verified=True,
                ),
                ExtractedClaim(
                    claim_text="Theotechnic College is supported by ACTIVE Ministry",
                    field_name="relationship",
                    source_urls=["https://www.activeministry.org/theotechnic"],
                    confidence=0.9,
                    is_verified=True,
                ),
                ExtractedClaim(
                    claim_text="Theotechnic College is part of ACTIVE Ministry",
                    field_name="association",
                    source_urls=["https://www.activeministry.org/theotechnic"],
                    confidence=0.9,
                    is_verified=True,
                ),
                ExtractedClaim(
                    claim_text="Theotechnic College is located in Zimbabwe",
                    field_name="metadata",
                    source_urls=["https://www.activeministry.org/theotechnic"],
                    confidence=0.8,
                    is_verified=True,
                ),
            ],
            raw_evidence=[
                "Theotechnic College is Now Open! All applicants will be placed on a prospective list...",
                "STUDENTSYour Journey of Faith and Learning Begins Here...",
            ],
            source_urls=["https://www.activeministry.org/theotechnic"],
            metadata_hints={
                "entity_type": "institution",
                "sector": "Education Sector",
                "country": "Zimbabwe",
                "status": "active",
            }
        )
        
        # Canonicalize
        row = canonicalizer.canonicalize("Theotechnic College", evidence_bundle)
        
        # Verify all fields
        assert row.uid == "theotechnic-college"
        assert row.entity == "Theotechnic College"
        
        # Verify aliases do not contain invalid entries
        for alias in row.aliases:
            assert "Now Open!" not in alias
            assert "2 Timothy" not in alias
            assert "STUDENTSYour" not in alias
        
        # Verify entity_type is valid
        assert row.entity_type in canonicalizer.ontology.all_entity_types or row.entity_type is None
        
        # Verify sector is valid
        assert row.sector in canonicalizer.ontology.sectors or row.sector is None
        
        # Verify status is valid
        assert row.status in canonicalizer.ontology.statuses or row.status is None
        
        # Verify country is valid
        assert row.country in canonicalizer.ontology.countries or row.country is None
        
        # Verify summary is concise
        assert len(row.summary.split()) < 100
        assert "Now Open!" not in row.summary
        assert "STUDENTSYour" not in row.summary
        assert "thousands of words" not in row.summary.lower()
        
        # Verify summary references entity
        assert "[[Theotechnic College]]" in row.summary or "Theotechnic College" in row.summary
        
        # Verify relationships are valid
        for rel in row.relationships:
            assert "provides::[[Comprehensive]]" != rel
            assert "provides::[[Foundational]]" != rel
            assert "provides::[[Quality]]" != rel
        
        # Verify associations are valid
        for assoc in row.associations:
            assert "member_of::[[College Family Dedicates Themselves" not in assoc
        
        # Verify sources
        assert len(row.sources) > 0
        assert "https://www.activeministry.org/theotechnic" in row.sources
        
        # Verify validation passes
        result = validator.validate(row)
        assert result.is_valid
    
    def test_canonicalization_with_minimal_evidence(self, canonicalizer):
        """Test canonicalization with minimal evidence."""
        evidence_bundle = EvidenceBundle(
            entity_name="Test Entity",
            entity_seed="Test Entity",
            claims=[
                ExtractedClaim(
                    claim_text="Test Entity is a test organization",
                    field_name="summary",
                    source_urls=["https://example.com"],
                    confidence=0.5,
                    is_verified=True,
                ),
            ],
            source_urls=["https://example.com"],
        )
        
        row = canonicalizer.canonicalize("Test Entity", evidence_bundle)
        
        assert row.uid == "test-entity"
        assert row.entity == "Test Entity"
        assert len(row.sources) > 0
    
    def test_canonicalization_preserves_entity_seed(self, canonicalizer):
        """Test that entity seed is preserved as canonical name."""
        evidence_bundle = EvidenceBundle(
            entity_name="Some Name From Webpage",
            entity_seed="Theotechnic College",
            claims=[
                ExtractedClaim(
                    claim_text="Theotechnic College is great",
                    field_name="summary",
                    source_urls=["https://example.com"],
                    confidence=0.5,
                    is_verified=True,
                ),
            ],
            source_urls=["https://example.com"],
        )
        
        row = canonicalizer.canonicalize("Theotechnic College", evidence_bundle)
        
        # Entity should be the seed, not the webpage text
        assert row.entity == "Theotechnic College"
    
    def test_canonicalization_handles_no_metadata(self, canonicalizer):
        """Test canonicalization when evidence does not support metadata fields."""
        evidence_bundle = EvidenceBundle(
            entity_name="Mystery Entity",
            entity_seed="Mystery Entity",
            claims=[
                ExtractedClaim(
                    claim_text="Mystery Entity exists",
                    field_name="summary",
                    source_urls=["https://example.com"],
                    confidence=0.5,
                    is_verified=True,
                ),
            ],
            source_urls=["https://example.com"],
        )
        
        row = canonicalizer.canonicalize("Mystery Entity", evidence_bundle)
        
        # Fields should be None, not hallucinated
        assert row.entity_type is None
        assert row.sector is None
        assert row.country is None
        assert row.status is None


# =============================================================================
# Specific Failure Mode Tests
# =============================================================================

class TestSpecificFailureModes:
    """Test that specific failure modes from the problem description are caught."""
    
    def test_rejects_webpage_text_as_entity_name(self, canonicalizer):
        """Entity name should not be extracted from webpage text."""
        evidence_bundle = EvidenceBundle(
            entity_name="Now Open! All applicants will be placed on a prospective list",
            entity_seed="Theotechnic College",
            claims=[
                ExtractedClaim(
                    claim_text="Theotechnic College is great",
                    field_name="summary",
                    source_urls=["https://example.com"],
                    confidence=0.5,
                    is_verified=True,
                ),
            ],
            source_urls=["https://example.com"],
        )
        
        row = canonicalizer.canonicalize("Theotechnic College", evidence_bundle)
        
        # Entity should be the seed, not the webpage text
        assert row.entity == "Theotechnic College"
        assert "Now Open!" not in row.entity
    
    def test_rejects_sentence_as_alias(self, canonicalizer):
        """Aliases should not contain sentences."""
        evidence_bundle = EvidenceBundle(
            entity_name="Theotechnic College",
            entity_seed="Theotechnic College",
            claims=[
                ExtractedClaim(
                    claim_text="Now Open! All applicants will be placed on a prospective list",
                    field_name="metadata",
                    source_urls=["https://example.com"],
                    confidence=0.5,
                    is_verified=True,
                ),
            ],
            source_urls=["https://example.com"],
        )
        
        row = canonicalizer.canonicalize("Theotechnic College", evidence_bundle)
        
        # No alias should contain the sentence
        for alias in row.aliases:
            assert "Now Open!" not in alias
    
    def test_rejects_bible_verse_as_alias(self, canonicalizer):
        """Aliases should not contain Bible verses."""
        evidence_bundle = EvidenceBundle(
            entity_name="Theotechnic College",
            entity_seed="Theotechnic College",
            claims=[
                ExtractedClaim(
                    claim_text="2 Timothy 2:15 Study to shew thyself approved",
                    field_name="summary",
                    source_urls=["https://example.com"],
                    confidence=0.5,
                    is_verified=True,
                ),
            ],
            source_urls=["https://example.com"],
        )
        
        row = canonicalizer.canonicalize("Theotechnic College", evidence_bundle)
        
        # No alias should contain the Bible verse
        for alias in row.aliases:
            assert "2 Timothy" not in alias
    
    def test_rejects_cta_as_status(self, canonicalizer):
        """Status should not contain CTA text."""
        evidence_bundle = EvidenceBundle(
            entity_name="Theotechnic College",
            entity_seed="Theotechnic College",
            claims=[
                ExtractedClaim(
                    claim_text="STUDENTSYour Journey of Faith and Learning Begins Here",
                    field_name="metadata",
                    source_urls=["https://example.com"],
                    confidence=0.5,
                    is_verified=True,
                ),
            ],
            source_urls=["https://example.com"],
        )
        
        row = canonicalizer.canonicalize("Theotechnic College", evidence_bundle)
        
        # Status should not contain CTA text
        if row.status:
            assert "STUDENTSYour" not in row.status
    
    def test_rejects_adjectives_as_relationship_targets(self, canonicalizer):
        """Relationship targets should not be adjectives."""
        evidence_bundle = EvidenceBundle(
            entity_name="Theotechnic College",
            entity_seed="Theotechnic College",
            claims=[
                ExtractedClaim(
                    claim_text="Theotechnic College provides Comprehensive education",
                    field_name="relationship",
                    source_urls=["https://example.com"],
                    confidence=0.5,
                    is_verified=True,
                ),
            ],
            source_urls=["https://example.com"],
        )
        
        row = canonicalizer.canonicalize("Theotechnic College", evidence_bundle)
        
        # No relationship should have an adjective as target
        for rel in row.relationships:
            assert "provides::[[Comprehensive]]" != rel
    
    def test_rejects_sentence_fragments_as_association_targets(self, canonicalizer):
        """Association targets should not be sentence fragments."""
        evidence_bundle = EvidenceBundle(
            entity_name="Theotechnic College",
            entity_seed="Theotechnic College",
            claims=[
                ExtractedClaim(
                    claim_text="Theotechnic College is member of College Family Dedicates Themselves To The Great Commission",
                    field_name="association",
                    source_urls=["https://example.com"],
                    confidence=0.5,
                    is_verified=True,
                ),
            ],
            source_urls=["https://example.com"],
        )
        
        row = canonicalizer.canonicalize("Theotechnic College", evidence_bundle)
        
        # No association should have a sentence fragment as target
        for assoc in row.associations:
            assert "College Family Dedicates Themselves" not in assoc


# =============================================================================
# Second Entity Test
# =============================================================================

class TestSecondEntity:
    """Test canonicalization against a second entity to ensure generalization."""
    
    def test_energy_authority_canonicalization(self, canonicalizer, validator):
        """Test canonicalization with a different entity type."""
        evidence_bundle = EvidenceBundle(
            entity_name="Zimbabwe Energy Regulatory Authority",
            entity_seed="Zimbabwe Energy Regulatory Authority",
            claims=[
                ExtractedClaim(
                    claim_text="Zimbabwe Energy Regulatory Authority regulates electricity licensing",
                    field_name="relationship",
                    source_urls=["https://zera.co.zw"],
                    confidence=0.9,
                    is_verified=True,
                ),
                ExtractedClaim(
                    claim_text="Zimbabwe Energy Regulatory Authority is a government agency",
                    field_name="metadata",
                    source_urls=["https://zera.co.zw"],
                    confidence=0.9,
                    is_verified=True,
                ),
                ExtractedClaim(
                    claim_text="Zimbabwe Energy Regulatory Authority is based in Zimbabwe",
                    field_name="metadata",
                    source_urls=["https://zera.co.zw"],
                    confidence=0.8,
                    is_verified=True,
                ),
            ],
            source_urls=["https://zera.co.zw"],
            metadata_hints={
                "entity_type": "government agency",
                "sector": "Energy Sector",
                "country": "Zimbabwe",
                "status": "active",
            }
        )
        
        row = canonicalizer.canonicalize("Zimbabwe Energy Regulatory Authority", evidence_bundle)
        
        # Verify fields
        assert row.uid == "zimbabwe-energy-regulatory-authority"
        assert row.entity == "Zimbabwe Energy Regulatory Authority"
        assert row.entity_type == "government agency"
        assert row.sector == "Energy Sector"
        assert row.country == "Zimbabwe"
        assert row.status == "Active"
        
        # Verify summary
        assert "[[Zimbabwe Energy Regulatory Authority]]" in row.summary or "Zimbabwe Energy Regulatory Authority" in row.summary
        assert len(row.summary.split()) < 100
        
        # Verify relationships
        assert any("regulates" in rel.lower() for rel in row.relationships)
        
        # Verify sources
        assert "https://zera.co.zw" in row.sources
        
        # Verify validation passes
        result = validator.validate(row)
        assert result.is_valid
    
    def test_concept_entity_canonicalization(self, canonicalizer, validator):
        """Test canonicalization with a concept entity."""
        evidence_bundle = EvidenceBundle(
            entity_name="Energy Security",
            entity_seed="Energy Security",
            claims=[
                ExtractedClaim(
                    claim_text="Energy Security is a concept related to energy policy",
                    field_name="summary",
                    source_urls=["https://example.com/energy-security"],
                    confidence=0.8,
                    is_verified=True,
                ),
            ],
            source_urls=["https://example.com/energy-security"],
            metadata_hints={
                "entity_type": "concept",
            }
        )
        
        row = canonicalizer.canonicalize("Energy Security", evidence_bundle)
        
        assert row.uid == "energy-security"
        assert row.entity == "Energy Security"
        assert row.entity_type == "concept"
        assert len(row.sources) > 0
        
        # Verify validation passes
        result = validator.validate(row)
        assert result.is_valid
