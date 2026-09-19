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

    async def search(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
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
    assert empty_claims.status == "insufficient"
    assert empty_claims.node_draft is None


@pytest.mark.asyncio
async def test_pipeline_batch_preserves_order_and_ignores_duplicates():
    registry = EntityRegistry()
    registry.create_entity("Zimbabwe Energy Regulatory Authority", entity_type="government agency")
    resolver = EntityResolver(registry)

    async def fake_enricher(entity_name: str, evidence_records: List[EvidenceRecord], **kwargs: Any):
        return [
            ResearchClaim(
                subject=entity_name,
                predicate="regulates",
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
