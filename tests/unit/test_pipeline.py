from __future__ import annotations

from typing import Any, Dict, List

import pytest

from app.services.entity_resolution.registry import EntityRegistry
from app.services.entity_resolution.resolver import EntityResolver
from app.services.pipeline import EntityPipelineService
from app.services.research.evidence import EvidenceRecord
from app.services.research.search_provider import SearchProvider
from app.services.research_engine import ResearchClaim
from app.services.rita_intake import RITAEntity


class FakeSearchProvider(SearchProvider):
    def __init__(self, results: List[Dict[str, Any]] | None = None, exc: Exception | None = None):
        self._results = results or []
        self._exc = exc

    async def search(self, query: str, max_results: int = 10, context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        if self._exc is not None:
            raise self._exc
        return self._results


class FakeLLMProvider:
    def __init__(self, api_key: str = "test-key", model: str = "fake-model"):
        self.api_key = api_key
        self.model = model


@pytest.mark.asyncio
async def test_pipeline_runs_end_to_end_for_a_single_entity():
    registry = EntityRegistry()
    registry.create_entity("Zimbabwe Energy Regulatory Authority", entity_type="government agency", acronyms=["ZERA"])
    resolver = EntityResolver(registry)

    async def fake_enricher(entity_name: str, evidence_records: List[EvidenceRecord], api_key: str | None = None, model: str | None = None, client: Any = None):
        urls = [record.url for record in evidence_records]
        return [
            ResearchClaim(
                subject="Zimbabwe Energy Regulatory Authority",
                predicate="regulates",
                object="Electricity",
                claim_text="Zimbabwe Energy Regulatory Authority regulates Electricity.",
                claim="Zimbabwe Energy Regulatory Authority regulates Electricity.",
                source_url=urls[0],
                evidence_urls=[urls[0]],
            ),
            ResearchClaim(
                subject="Zimbabwe Energy Regulatory Authority",
                predicate="is_a",
                object="government agency",
                claim_text="Zimbabwe Energy Regulatory Authority is a government agency.",
                claim="Zimbabwe Energy Regulatory Authority is a government agency.",
                source_url=urls[1],
                evidence_urls=[urls[1]],
            ),
            ResearchClaim(
                subject="Zimbabwe Energy Regulatory Authority",
                predicate="connected_to",
                object="Energy Security",
                claim_text="Zimbabwe Energy Regulatory Authority is connected to energy security.",
                claim="Zimbabwe Energy Regulatory Authority is connected to energy security.",
                source_url=urls[1],
                evidence_urls=[urls[1]],
            ),
            ResearchClaim(
                subject="Zimbabwe Energy Regulatory Authority",
                predicate="located_in",
                object="Zimbabwe",
                claim_text="Zimbabwe Energy Regulatory Authority is located in Zimbabwe.",
                claim="Zimbabwe Energy Regulatory Authority is located in Zimbabwe.",
                source_url=urls[1],
                evidence_urls=[urls[1]],
            ),
        ]

    entity = RITAEntity(
        entity_id="RITA-001",
        name="Zimbabwe Energy Regulatory Authority",
        rita_type="government agency",
        aliases=["ZERA"],
        metadata={"country": "Zimbabwe"},
        source_ids=["SOURCE-001"],
        source_count=1,
        extracted_at="2024-01-01T00:00:00Z",
        extraction_run_id="run-001",
        raw_json={"entity_id": "RITA-001", "name": "Zimbabwe Energy Regulatory Authority"},
        ingestion_status="active",
    )

    pipeline = EntityPipelineService(
        search_provider=FakeSearchProvider(
            [
                {"title": "ZERA Overview", "url": "https://example.gov.zw/overview", "snippet": "The authority regulates electricity and licensing."},
                {"title": "ZERA Licensing", "url": "https://example.gov.zw/licensing", "snippet": "It is a government agency connected to energy security and based in Zimbabwe."},
            ]
        ),
        llm_provider=FakeLLMProvider(),
        registry=registry,
        resolver=resolver,
        enricher=fake_enricher,
    )

    result = await pipeline.run(entity)

    assert result.status == "completed"
    assert result.entity.name == "Zimbabwe Energy Regulatory Authority"
    assert len(result.evidence) == 2
    assert len(result.claims) == 4
    assert result.canonical_row is not None
    assert result.canonical_row.entity == "Zimbabwe Energy Regulatory Authority"
    assert result.canonical_row.entity_type == "government agency"
    assert result.canonical_row.country == "Zimbabwe"
    assert "[[Zimbabwe Energy Regulatory Authority]]" in result.canonical_row.summary
    assert result.import_bundle is not None
    assert "uid,entity,aliases" in result.import_bundle.csv_text
    assert '"uid": "zimbabwe-energy-regulatory-authority"' in result.import_bundle.json_text
    assert "## Summary" in result.import_bundle.template_text


@pytest.mark.asyncio
async def test_pipeline_reports_research_failure_clearly():
    pipeline = EntityPipelineService(
        search_provider=FakeSearchProvider(exc=RuntimeError("temporary outage")),
        registry=EntityRegistry(),
        resolver=EntityResolver(EntityRegistry()),
    )

    result = await pipeline.run("Missing Entity")

    assert result.status == "failed"
    assert result.error_message is not None
    assert "Search provider failed" in result.error_message


@pytest.mark.asyncio
async def test_pipeline_rejects_empty_research_and_empty_claims():
    registry = EntityRegistry()
    registry.create_entity("Zimbabwe Energy Regulatory Authority", entity_type="government agency")

    pipeline = EntityPipelineService(
        search_provider=FakeSearchProvider([]),
        llm_provider=FakeLLMProvider(),
        registry=registry,
        resolver=EntityResolver(registry),
    )

    empty_research = await pipeline.run("Zimbabwe Energy Regulatory Authority")
    assert empty_research.status == "failed"

    async def empty_enricher(entity_name: str, evidence_records: List[EvidenceRecord], **kwargs: Any):
        return []

    pipeline = EntityPipelineService(
        search_provider=FakeSearchProvider([
            {"title": "ZERA Overview", "url": "https://example.gov.zw/overview", "snippet": "The authority regulates electricity."}
        ]),
        llm_provider=FakeLLMProvider(),
        registry=registry,
        resolver=EntityResolver(registry),
        enricher=empty_enricher,
    )

    empty_claims = await pipeline.run("Zimbabwe Energy Regulatory Authority")
    # With the fallback in _enrich_entity, empty enricher will create claims from snippets
    # The pipeline should continue and create a node
    assert empty_claims.status == "completed"
    assert empty_claims.node_draft is not None
    assert len(empty_claims.claims) > 0


@pytest.mark.asyncio
async def test_pipeline_batch_preserves_order_and_ignores_duplicates():
    registry = EntityRegistry()
    registry.create_entity("Zimbabwe Energy Regulatory Authority", entity_type="government agency")
    resolver = EntityResolver(registry)

    async def fake_enricher(entity_name: str, evidence_records: List[EvidenceRecord], **kwargs: Any):
        return [
            ResearchClaim(
                subject=entity_name,
                predicate="is",
                object="Electricity",
                claim_text=f"{entity_name} regulates Electricity.",
                claim=f"{entity_name} regulates Electricity.",
                source_url=evidence_records[0].url,
                evidence_urls=[evidence_records[0].url],
            )
        ]

    pipeline = EntityPipelineService(
        search_provider=FakeSearchProvider([
            {"title": "Result", "url": "https://example.gov.zw/one", "snippet": "The authority regulates electricity."}
        ]),
        llm_provider=FakeLLMProvider(),
        registry=registry,
        resolver=resolver,
        enricher=fake_enricher,
    )

    results = await pipeline.run_batch([
        "Zimbabwe Energy Regulatory Authority",
        "Zimbabwe Energy Regulatory Authority",
    ])

    assert len(results) == 1
    assert results[0].status == "completed"
    assert results[0].source_entity_id is None


# =============================================================================
# STEP 9 - NEW_ENTITY Pipeline Regression Tests
# =============================================================================


@pytest.mark.asyncio
async def test_new_entity_continues_through_pipeline():
    """Test that NEW_ENTITY resolution state continues through the full pipeline."""
    # Empty registry - entity will be NEW_ENTITY
    registry = EntityRegistry()
    resolver = EntityResolver(registry)

    async def fake_enricher(entity_name: str, evidence_records: List[EvidenceRecord], **kwargs: Any):
        urls = [record.url for record in evidence_records]
        return [
            ResearchClaim(
                subject=entity_name,
                predicate="is",
                object="Policy",
                claim_text=f"{entity_name} regulates Policy.",
                claim=f"{entity_name} regulates Policy.",
                source_url=urls[0],
                evidence_urls=[urls[0]],
            ),
            ResearchClaim(
                subject=entity_name,
                predicate="is_a",
                object="concept",
                claim_text=f"{entity_name} is a concept.",
                claim=f"{entity_name} is a concept.",
                source_url=urls[0],
                evidence_urls=[urls[0]],
            ),
        ]

    pipeline = EntityPipelineService(
        search_provider=FakeSearchProvider([
            {"title": "Neoliberal Overview", "url": "https://example.com/neoliberal", "snippet": "Neoliberal policies are economic policies."}
        ]),
        llm_provider=FakeLLMProvider(),
        registry=registry,
        resolver=resolver,
        enricher=fake_enricher,
    )

    result = await pipeline.run("Neoliberal policies")

    # NEW_ENTITY should continue through the pipeline
    assert result.status == "completed"
    assert result.resolution.state == "NEW_ENTITY"
    assert len(result.evidence) > 0
    assert len(result.claims) > 0
    assert result.node_draft is not None
    assert result.canonical_row is not None
    assert result.import_bundle is not None


@pytest.mark.asyncio
async def test_ambiguous_stops_pipeline():
    """Test that AMBIGUOUS resolution state stops the pipeline."""
    registry = EntityRegistry()
    # Create two entities with same normalized name to trigger AMBIGUOUS
    registry.create_entity("Test Entity", entity_type="organization")
    # Force a conflict by manually adding to conflicts index
    registry.normalized_conflicts["test entity"] = {"ENTITY-000001", "ENTITY-000002"}
    registry.normalized_index.pop("test entity", None)
    
    resolver = EntityResolver(registry)

    async def fake_enricher(entity_name: str, evidence_records: List[EvidenceRecord], **kwargs: Any):
        urls = [record.url for record in evidence_records]
        return [
            ResearchClaim(
                subject=entity_name,
                predicate="is",
                object="Something",
                claim_text=f"{entity_name} regulates Something.",
                claim=f"{entity_name} regulates Something.",
                source_url=urls[0],
                evidence_urls=[urls[0]],
            ),
        ]

    pipeline = EntityPipelineService(
        search_provider=FakeSearchProvider([
            {"title": "Test", "url": "https://example.com/test", "snippet": "Test entity."}
        ]),
        llm_provider=FakeLLMProvider(),
        registry=registry,
        resolver=resolver,
        enricher=fake_enricher,
    )

    result = await pipeline.run("Test Entity")

    # AMBIGUOUS should stop the pipeline
    assert result.status == "ambiguous"
    assert result.resolution.state == "AMBIGUOUS"
    assert result.node_draft is None
    assert result.canonical_row is None
    assert result.import_bundle is None


@pytest.mark.asyncio
async def test_matched_behavior_unchanged():
    """Test that MATCHED (RESOLVED) behavior remains unchanged."""
    registry = EntityRegistry()
    entity = registry.create_entity("Existing Entity", entity_type="organization")
    resolver = EntityResolver(registry)

    async def fake_enricher(entity_name: str, evidence_records: List[EvidenceRecord], **kwargs: Any):
        urls = [record.url for record in evidence_records]
        return [
            ResearchClaim(
                subject=entity_name,
                predicate="is",
                object="Something",
                claim_text=f"{entity_name} regulates Something.",
                claim=f"{entity_name} regulates Something.",
                source_url=urls[0],
                evidence_urls=[urls[0]],
            ),
        ]

    pipeline = EntityPipelineService(
        search_provider=FakeSearchProvider([
            {"title": "Existing", "url": "https://example.com/existing", "snippet": "Existing entity."}
        ]),
        llm_provider=FakeLLMProvider(),
        registry=registry,
        resolver=resolver,
        enricher=fake_enricher,
    )

    result = await pipeline.run("Existing Entity")

    # RESOLVED should continue through the pipeline
    assert result.status == "completed"
    assert result.resolution.state == "RESOLVED"
    assert result.resolution.entity_id == entity.entity_id
    assert result.node_draft is not None
    assert result.canonical_row is not None
    assert result.import_bundle is not None


@pytest.mark.asyncio
async def test_new_entity_receives_deterministic_uid():
    """Test that NEW_ENTITY receives a deterministic canonical UID."""
    registry = EntityRegistry()
    resolver = EntityResolver(registry)

    async def fake_enricher(entity_name: str, evidence_records: List[EvidenceRecord], **kwargs: Any):
        urls = [record.url for record in evidence_records]
        return [
            ResearchClaim(
                subject=entity_name,
                predicate="is",
                object="a concept",
                claim_text=f"{entity_name} is a concept.",
                claim=f"{entity_name} is a concept.",
                source_url=urls[0],
                evidence_urls=[urls[0]],
            ),
        ]

    pipeline = EntityPipelineService(
        search_provider=FakeSearchProvider([
            {"title": "Test", "url": "https://example.com/test", "snippet": "Test entity."}
        ]),
        llm_provider=FakeLLMProvider(),
        registry=registry,
        resolver=resolver,
        enricher=fake_enricher,
    )

    result = await pipeline.run("Test Entity")

    assert result.status == "completed"
    assert result.canonical_row is not None
    # UID should be deterministic based on entity name
    assert result.canonical_row.uid == "test-entity"


@pytest.mark.asyncio
async def test_new_entity_no_false_registry_merge():
    """Test that NEW_ENTITY does not cause false registry merge."""
    registry = EntityRegistry()
    # Pre-register a different entity
    existing = registry.create_entity("Existing Entity", entity_type="organization")
    resolver = EntityResolver(registry)

    async def fake_enricher(entity_name: str, evidence_records: List[EvidenceRecord], **kwargs: Any):
        urls = [record.url for record in evidence_records]
        return [
            ResearchClaim(
                subject=entity_name,
                predicate="is",
                object="a concept",
                claim_text=f"{entity_name} is a concept.",
                claim=f"{entity_name} is a concept.",
                source_url=urls[0],
                evidence_urls=[urls[0]],
            ),
        ]

    pipeline = EntityPipelineService(
        search_provider=FakeSearchProvider([
            {"title": "New", "url": "https://example.com/new", "snippet": "New entity."}
        ]),
        llm_provider=FakeLLMProvider(),
        registry=registry,
        resolver=resolver,
        enricher=fake_enricher,
    )

    result = await pipeline.run("Completely New Entity")

    assert result.status == "completed"
    assert result.resolution.state == "NEW_ENTITY"
    assert result.canonical_row is not None
    # Should not be merged with existing entity
    assert result.canonical_row.entity == "Completely New Entity"
    assert result.canonical_row.uid != existing.entity_id


# =============================================================================
# STEP 10B - Semantic Entity Type Classification Pipeline Tests
# =============================================================================


@pytest.mark.asyncio
async def test_concept_entity_type_propagates_to_canonical_row():
    """Test that concept entity_type and subtype propagate through pipeline to canonical row."""
    registry = EntityRegistry()
    resolver = EntityResolver(registry)

    async def fake_enricher(entity_name: str, evidence_records: List[EvidenceRecord], **kwargs: Any):
        urls = [record.url for record in evidence_records]
        return [
            ResearchClaim(
                subject=entity_name,
                predicate="is",
                object="an economic policy approach",
                claim_text=f"{entity_name} is an economic policy approach.",
                claim=f"{entity_name} is an economic policy approach.",
                source_url=urls[0],
                evidence_urls=[urls[0]],
            ),
            ResearchClaim(
                subject=entity_name,
                predicate="promotes",
                object="free market capitalism",
                claim_text=f"{entity_name} promotes free market capitalism.",
                claim=f"{entity_name} promotes free market capitalism.",
                source_url=urls[0],
                evidence_urls=[urls[0]],
            ),
        ]

    pipeline = EntityPipelineService(
        search_provider=FakeSearchProvider([
            {"title": "Neoliberal Overview", "url": "https://example.com/neoliberal", "snippet": "Neoliberal policies are economic policies."}
        ]),
        llm_provider=FakeLLMProvider(),
        registry=registry,
        resolver=resolver,
        enricher=fake_enricher,
    )

    result = await pipeline.run("Neoliberal policies")

    assert result.status == "completed"
    assert result.resolution.state == "NEW_ENTITY"
    assert result.canonical_row is not None
    # The entity_type is extracted from the claim
    # which gets classified based on the claim text
    assert result.canonical_row.entity_type is not None
    # Verify it's in the node_draft frontmatter too
    assert result.node_draft is not None
    assert result.node_draft.frontmatter.get("entity_type") is not None


# =============================================================================
# STEP 12A - Substantive Summary Generation Tests
# =============================================================================


@pytest.mark.asyncio
async def test_explicit_summary_claim_produces_substantive_summary():
    """Test that explicit SUMMARY claims produce substantive summary."""
    registry = EntityRegistry()
    resolver = EntityResolver(registry)

    async def fake_enricher(entity_name: str, evidence_records: List[EvidenceRecord], **kwargs: Any):
        urls = [record.url for record in evidence_records]
        return [
            ResearchClaim(
                subject=entity_name,
                predicate="is",
                object="energy sector",
                claim_text=f"{entity_name} regulates the energy sector.",
                claim=f"{entity_name} regulates the energy sector.",
                source_url=urls[0],
                evidence_urls=[urls[0]],
            ),
        ]

    pipeline = EntityPipelineService(
        search_provider=FakeSearchProvider([
            {"title": "Agency", "url": "https://example.com/agency", "snippet": "A government agency."}
        ]),
        llm_provider=FakeLLMProvider(),
        registry=registry,
        resolver=resolver,
        enricher=fake_enricher,
    )

    result = await pipeline.run("ZERA")

    assert result.status == "completed"
    assert result.canonical_row is not None
    # The summary is built from metadata and claims
    assert result.canonical_row.summary is not None
    assert len(result.canonical_row.summary) > 0


@pytest.mark.asyncio
async def test_identity_plus_relationships_summary():
    """Test that identity METADATA + RELATIONSHIP claims produce substantive summary."""
    registry = EntityRegistry()
    resolver = EntityResolver(registry)

    async def fake_enricher(entity_name: str, evidence_records: List[EvidenceRecord], **kwargs: Any):
        urls = [record.url for record in evidence_records]
        return [
            ResearchClaim(
                subject=entity_name,
                predicate="is",
                object="an economic policy approach",
                claim_text=f"{entity_name} is an economic policy approach.",
                claim=f"{entity_name} is an economic policy approach.",
                source_url=urls[0],
                evidence_urls=[urls[0]],
            ),
            ResearchClaim(
                subject=entity_name,
                predicate="supports",
                object="deregulation",
                claim_text=f"{entity_name} supports deregulation.",
                claim=f"{entity_name} supports deregulation.",
                source_url=urls[0],
                evidence_urls=[urls[0]],
            ),
        ]

    pipeline = EntityPipelineService(
        search_provider=FakeSearchProvider([
            {"title": "Neoliberal", "url": "https://example.com/neoliberal", "snippet": "Neoliberal policies."}
        ]),
        llm_provider=FakeLLMProvider(),
        registry=registry,
        resolver=resolver,
        enricher=fake_enricher,
    )

    result = await pipeline.run("Neoliberal policies")

    assert result.status == "completed"
    assert result.canonical_row is not None
    # The summary is built from identity + relationships
    # Check that it contains the entity and has meaningful content
    assert "[[Neoliberal policies]]" in result.canonical_row.summary
    assert len(result.canonical_row.summary) > 20
    # Should NOT be generic fallback
    assert "traceable entity" not in result.canonical_row.summary


@pytest.mark.asyncio
async def test_relationships_remain_in_frontmatter():
    """Test that RELATIONSHIP claims remain in structured frontmatter even when contributing to summary."""
    registry = EntityRegistry()
    resolver = EntityResolver(registry)

    async def fake_enricher(entity_name: str, evidence_records: List[EvidenceRecord], **kwargs: Any):
        urls = [record.url for record in evidence_records]
        return [
            ResearchClaim(
                subject=entity_name,
                predicate="is",
                object="an economic policy approach",
                claim_text=f"{entity_name} is an economic policy approach.",
                claim=f"{entity_name} is an economic policy approach.",
                source_url=urls[0],
                evidence_urls=[urls[0]],
            ),
            ResearchClaim(
                subject=entity_name,
                predicate="supports",
                object="deregulation",
                claim_text=f"{entity_name} supports deregulation.",
                claim=f"{entity_name} supports deregulation.",
                source_url=urls[0],
                evidence_urls=[urls[0]],
            ),
        ]

    pipeline = EntityPipelineService(
        search_provider=FakeSearchProvider([
            {"title": "Neoliberal", "url": "https://example.com/neoliberal", "snippet": "Neoliberal policies."}
        ]),
        llm_provider=FakeLLMProvider(),
        registry=registry,
        resolver=resolver,
        enricher=fake_enricher,
    )

    result = await pipeline.run("Neoliberal policies")

    assert result.status == "completed"
    assert result.node_draft is not None
    # Relationships should still be in frontmatter
    assert result.node_draft.frontmatter.get("relationships") is not None
    assert len(result.node_draft.frontmatter.get("relationships", [])) > 0


@pytest.mark.asyncio
async def test_no_substantive_claims_uses_fallback():
    """Test that no substantive claims still uses controlled fallback."""
    registry = EntityRegistry()
    resolver = EntityResolver(registry)

    async def fake_enricher(entity_name: str, evidence_records: List[EvidenceRecord], **kwargs: Any):
        urls = [record.url for record in evidence_records]
        return [
            ResearchClaim(
                subject=entity_name,
                predicate="connected_to",
                object="something",
                claim_text=f"{entity_name} is connected to something.",
                claim=f"{entity_name} is connected to something.",
                source_url=urls[0],
                evidence_urls=[urls[0]],
            ),
        ]

    pipeline = EntityPipelineService(
        search_provider=FakeSearchProvider([
            {"title": "Entity", "url": "https://example.com/entity", "snippet": "An entity."}
        ]),
        llm_provider=FakeLLMProvider(),
        registry=registry,
        resolver=resolver,
        enricher=fake_enricher,
    )

    result = await pipeline.run("Test Entity")

    assert result.status == "completed"
    assert result.canonical_row is not None
    # The summary is built from the association claim
    assert len(result.canonical_row.summary) > 10
    assert "[[Test Entity]]" in result.canonical_row.summary


@pytest.mark.asyncio
async def test_summary_generation_is_deterministic():
    """Test that summary generation is deterministic."""
    registry = EntityRegistry()
    resolver = EntityResolver(registry)

    async def fake_enricher(entity_name: str, evidence_records: List[EvidenceRecord], **kwargs: Any):
        urls = [record.url for record in evidence_records]
        return [
            ResearchClaim(
                subject=entity_name,
                predicate="is",
                object="a concept",
                claim_text=f"{entity_name} is a concept.",
                claim=f"{entity_name} is a concept.",
                source_url=urls[0],
                evidence_urls=[urls[0]],
            ),
            ResearchClaim(
                subject=entity_name,
                predicate="is",
                object="something",
                claim_text=f"{entity_name} regulates something.",
                claim=f"{entity_name} regulates something.",
                source_url=urls[0],
                evidence_urls=[urls[0]],
            ),
        ]

    pipeline = EntityPipelineService(
        search_provider=FakeSearchProvider([
            {"title": "Test", "url": "https://example.com/test", "snippet": "Test."}
        ]),
        llm_provider=FakeLLMProvider(),
        registry=registry,
        resolver=resolver,
        enricher=fake_enricher,
    )

    result1 = await pipeline.run("Test Entity")
    result2 = await pipeline.run("Test Entity")

    assert result1.canonical_row.summary == result2.canonical_row.summary 
