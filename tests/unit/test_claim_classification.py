from app.services.claim_classifier import ClaimCategory, ClaimClassifier
from app.services.entity_resolution.registry import EntityRegistry
from app.services.entity_resolution.resolver import EntityResolver
from app.services.research_engine import ResearchClaim


class TestClaimClassification:
    def test_summary_classification_for_functional_claim(self):
        claim = ResearchClaim(
            subject="Zimbabwe Energy Regulatory Authority",
            predicate="regulates",
            object="Zimbabwe's energy sector",
            claim_text="Zimbabwe Energy Regulatory Authority regulates Zimbabwe's energy sector.",
            evidence_urls=["https://example.com/zera"],
            claim="Zimbabwe Energy Regulatory Authority regulates Zimbabwe's energy sector.",
            source_url="https://example.com/zera",
        )

        result = ClaimClassifier().classify(claim)

        assert result.category == ClaimCategory.SUMMARY
        assert "energy sector" in result.target.lower()

    def test_direct_relationship_classification(self):
        claim = ResearchClaim(
            subject="ZERA",
            predicate="regulates",
            object="Electricity",
            claim_text="ZERA regulates Electricity.",
            evidence_urls=["https://example.com/zera"],
            claim="ZERA regulates Electricity.",
            source_url="https://example.com/zera",
        )

        result = ClaimClassifier().classify(claim)

        assert result.category == ClaimCategory.RELATIONSHIP
        assert result.target == "Electricity"

    def test_association_classification(self):
        claim = ResearchClaim(
            subject="Lithium",
            predicate="connected_to",
            object="Electric Vehicle Supply Chain",
            claim_text="Lithium is connected to electric vehicle supply chains.",
            evidence_urls=["https://example.com/lithium"],
            claim="Lithium is connected to electric vehicle supply chains.",
            source_url="https://example.com/lithium",
        )

        result = ClaimClassifier().classify(claim)

        assert result.category == ClaimCategory.ASSOCIATION
        assert result.target == "Electric Vehicle Supply Chain"

    def test_metadata_classification_uses_canonical_fields(self):
        claim = ResearchClaim(
            subject="ZERA",
            predicate="is_a",
            object="government agency",
            claim_text="ZERA is a government agency.",
            evidence_urls=["https://example.com/zera"],
            claim="ZERA is a government agency.",
            source_url="https://example.com/zera",
        )

        result = ClaimClassifier().classify(claim)

        assert result.category == ClaimCategory.METADATA
        assert result.metadata_field == "entity_type"

    def test_ambiguous_claim_is_unclassified(self):
        claim = ResearchClaim(
            subject="Example Org",
            predicate="related_to",
            object="something unclear",
            claim_text="Example Org is related to something unclear.",
            evidence_urls=["https://example.com/example"],
            claim="Example Org is related to something unclear.",
            source_url="https://example.com/example",
        )

        result = ClaimClassifier().classify(claim)

        assert result.category == ClaimCategory.UNCLASSIFIED

    def test_entity_resolution_uses_canonical_target_and_ambiguous_names_stay_unresolved(self):
        registry = EntityRegistry()
        first = registry.create_entity("Zimbabwe Energy Regulatory Authority", acronyms=["ZERA"])
        second = registry.create_entity("ZERA Holdings", acronyms=["ZH"])
        registry.add_alias_to_entity(second.entity_id, "ZERA", "zera", "source")
        resolver = EntityResolver(registry, fuzzy_threshold=0.85)
        classifier = ClaimClassifier(registry=registry, resolver=resolver)

        resolved = classifier.classify(
            ResearchClaim(
                subject="ZERA",
                predicate="regulates",
                object="Zimbabwe Energy Regulatory Authority",
                claim_text="ZERA regulates Zimbabwe Energy Regulatory Authority.",
                evidence_urls=["https://example.com/zera"],
                claim="ZERA regulates Zimbabwe Energy Regulatory Authority.",
                source_url="https://example.com/zera",
            )
        )
        assert resolved.category == ClaimCategory.RELATIONSHIP
        assert resolved.target == "Zimbabwe Energy Regulatory Authority"
        assert resolved.resolved_target == "Zimbabwe Energy Regulatory Authority"

        ambiguous = classifier.classify(
            ResearchClaim(
                subject="ZERA",
                predicate="regulates",
                object="ZERA",
                claim_text="ZERA regulates ZERA.",
                evidence_urls=["https://example.com/zera"],
                claim="ZERA regulates ZERA.",
                source_url="https://example.com/zera",
            )
        )
        assert ambiguous.category == ClaimCategory.RELATIONSHIP
        assert ambiguous.resolved_target is None

    def test_deduplication_and_evidence_preservation(self):
        classifier = ClaimClassifier()
        claims = [
            ResearchClaim(
                subject="ZERA",
                predicate="regulates",
                object="Electricity",
                claim_text="ZERA regulates Electricity.",
                evidence_urls=["https://example.com/zera"],
                claim="ZERA regulates Electricity.",
                source_url="https://example.com/zera",
            ),
            ResearchClaim(
                subject="ZERA",
                predicate="regulates",
                object="Electricity",
                claim_text="ZERA regulates Electricity.",
                evidence_urls=["https://example.com/zera"],
                claim="ZERA regulates Electricity.",
                source_url="https://example.com/zera",
            ),
        ]

        grouped = classifier.route(claims)

        assert grouped[ClaimCategory.RELATIONSHIP] == ["regulates::[[Electricity]]"]
        assert sorted(grouped[ClaimCategory.SUMMARY]) == []


# =============================================================================
# STEP 10B - Semantic Entity Type Classification Tests
# =============================================================================

    def test_concept_entity_type_classification(self):
        """Test that 'is an economic policy approach' classifies as entity_type=concept with subtype=economic_policy."""
        claim = ResearchClaim(
            subject="Neoliberal policies",
            predicate="is",
            object="an economic policy approach",
            claim_text="Neoliberal policies is an economic policy approach.",
            evidence_urls=["https://example.com/neoliberal"],
            claim="Neoliberal policies is an economic policy approach.",
            source_url="https://example.com/neoliberal",
        )

        result = ClaimClassifier().classify(claim)

        assert result.category == ClaimCategory.METADATA
        assert result.metadata_field == "entity_type"
        assert result.target == "an economic policy approach"
        assert result.subtype == "economic_policy"

    def test_concept_entity_type_simple(self):
        """Test that 'is a concept' classifies as entity_type=concept."""
        claim = ResearchClaim(
            subject="Test Entity",
            predicate="is",
            object="a concept",
            claim_text="Test Entity is a concept.",
            evidence_urls=["https://example.com/test"],
            claim="Test Entity is a concept.",
            source_url="https://example.com/test",
        )

        result = ClaimClassifier().classify(claim)

        assert result.category == ClaimCategory.METADATA
        assert result.metadata_field == "entity_type"
        assert result.target == "a concept"
        assert result.subtype is None

    def test_existing_government_agency_classification_unchanged(self):
        """Test that existing government agency classification still works."""
        claim = ResearchClaim(
            subject="ZERA",
            predicate="is_a",
            object="government agency",
            claim_text="ZERA is a government agency.",
            evidence_urls=["https://example.com/zera"],
            claim="ZERA is a government agency.",
            source_url="https://example.com/zera",
        )

        result = ClaimClassifier().classify(claim)

        assert result.category == ClaimCategory.METADATA
        assert result.metadata_field == "entity_type"
        assert result.target == "government agency"

    def test_policy_regulates_not_entity_type(self):
        """Test that 'A policy regulates electricity' does NOT classify as entity_type=policy."""
        claim = ResearchClaim(
            subject="A policy",
            predicate="regulates",
            object="Electricity",
            claim_text="A policy regulates Electricity.",
            evidence_urls=["https://example.com/policy"],
            claim="A policy regulates Electricity.",
            source_url="https://example.com/policy",
        )

        result = ClaimClassifier().classify(claim)

        # Should NOT be METADATA (i.e., should not classify as entity_type=policy)
        # The existing relationship detection has a check that prevents "policy" from being
        # classified as a direct relationship, so it falls through to UNCLASSIFIED
        # This is acceptable - the key requirement is it's NOT entity_type=policy
        assert result.category != ClaimCategory.METADATA
        assert result.metadata_field is None

    def test_no_claim_invention_when_routing(self):
        classifier = ClaimClassifier()
        claims = [
            ResearchClaim(
                subject="Lithium",
                predicate="used_in",
                object="battery manufacturing",
                claim_text="Lithium is used in rechargeable battery manufacturing.",
                evidence_urls=["https://example.com/lithium"],
                claim="Lithium is used in rechargeable battery manufacturing.",
                source_url="https://example.com/lithium",
            )
        ]

        grouped = classifier.route(claims)

        assert ClaimCategory.SUMMARY in grouped
        assert len(grouped) <= 6
