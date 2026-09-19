from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from app.services.entity_resolution.registry import EntityRegistry
from app.services.entity_resolution.resolver import EntityResolver
from app.services.pipeline import EntityPipelineService
from app.services.production_runner import ProductionRunner
from app.services.research.evidence import EvidenceRecord
from app.services.research.search_provider import SearchProvider
from app.services.research_engine import ResearchClaim


class FakeSearchProvider(SearchProvider):
    def __init__(self, results=None):
        self._results = results or []

    async def search(self, query: str, max_results: int = 10):
        return self._results


class FakeLLMProvider:
    def __init__(self):
        self.api_key = "test-key"
        self.model = "fake-model"


async def _fake_enricher(entity_name: str, evidence_records: list[EvidenceRecord], **kwargs):
    if not evidence_records:
        return []
    first = evidence_records[0].url
    second = evidence_records[-1].url if len(evidence_records) > 1 else first
    return [
        ResearchClaim(
            subject=entity_name,
            predicate="regulates",
            object="Electricity",
            claim_text=f"{entity_name} regulates Electricity.",
            claim=f"{entity_name} regulates Electricity.",
            source_url=first,
            evidence_urls=[first],
        ),
        ResearchClaim(
            subject=entity_name,
            predicate="is_a",
            object="government agency",
            claim_text=f"{entity_name} is a government agency.",
            claim=f"{entity_name} is a government agency.",
            source_url=second,
            evidence_urls=[second],
        ),
        ResearchClaim(
            subject=entity_name,
            predicate="connected_to",
            object="Energy Security",
            claim_text=f"{entity_name} is connected to energy security.",
            claim=f"{entity_name} is connected to energy security.",
            source_url=second,
            evidence_urls=[second],
        ),
    ]


@pytest.mark.asyncio
async def test_production_runner_writes_bundle_files(tmp_path):
    registry = EntityRegistry()
    registry.create_entity("Zimbabwe Energy Regulatory Authority", entity_type="government agency", acronyms=["ZERA"])
    resolver = EntityResolver(registry)

    pipeline = EntityPipelineService(
        search_provider=FakeSearchProvider([
            {"title": "ZERA Overview", "url": "https://example.gov.zw/overview", "snippet": "The authority regulates electricity and licensing."},
            {"title": "ZERA Licensing", "url": "https://example.gov.zw/licensing", "snippet": "It is a government agency connected to energy security."},
        ]),
        llm_provider=FakeLLMProvider(),
        registry=registry,
        resolver=resolver,
        enricher=_fake_enricher,
    )

    rita_export = [
        {
            "entity_id": "ENTITY-001",
            "name": "Zimbabwe Energy Regulatory Authority",
            "rita_type": "government agency",
            "aliases": ["ZERA"],
            "metadata": {"country": "Zimbabwe", "sector": "Energy", "status": "active"},
            "source_ids": ["SOURCE-001"],
            "source_count": 1,
            "extracted_at": "2024-01-01T00:00:00Z",
            "extraction_run_id": "RUN-001",
            "raw_json": {"entity_id": "ENTITY-001", "name": "Zimbabwe Energy Regulatory Authority"},
            "ingestion_status": "active",
        }
    ]
    input_path = tmp_path / "rita.json"
    input_path.write_text(json.dumps(rita_export, ensure_ascii=False), encoding="utf-8")

    output_dir = tmp_path / "output"
    runner = ProductionRunner(pipeline=pipeline)
    result = await runner.run_file(input_path, output_dir)

    assert result.succeeded == 1
    assert result.failed == 0
    assert (output_dir / "nodes.csv").exists()
    assert (output_dir / "nodes.json").exists()
    assert (output_dir / "node_template.md").exists()

    csv_text = (output_dir / "nodes.csv").read_text(encoding="utf-8")
    json_text = (output_dir / "nodes.json").read_text(encoding="utf-8")
    template_text = (output_dir / "node_template.md").read_text(encoding="utf-8")
    assert "uid,entity,aliases" in csv_text
    assert '"entity": "Zimbabwe Energy Regulatory Authority"' in json_text
    assert "## Summary" in template_text
    assert result.bundle is not None
    assert csv_text == result.bundle.csv_text
    assert json_text == result.bundle.json_text
    assert template_text == result.bundle.template_text


@pytest.mark.asyncio
async def test_production_runner_preserves_order_and_reports_partial_failure(tmp_path):
    registry = EntityRegistry()
    registry.create_entity("Zimbabwe Energy Regulatory Authority", entity_type="government agency", acronyms=["ZERA"])
    registry.create_entity("Energy Commission", entity_type="government agency")
    resolver = EntityResolver(registry)

    async def bad_enricher(entity_name: str, evidence_records: list[EvidenceRecord], **kwargs):
        if entity_name == "Energy Commission":
            return []
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
            {"title": "Result", "url": "https://example.gov.zw/one", "snippet": "The authority regulates electricity."},
        ]),
        llm_provider=FakeLLMProvider(),
        registry=registry,
        resolver=resolver,
        enricher=bad_enricher,
    )

    export = [
        {
            "entity_id": "ENTITY-001",
            "name": "Zimbabwe Energy Regulatory Authority",
            "rita_type": "government agency",
            "aliases": ["ZERA"],
            "metadata": {"country": "Zimbabwe"},
            "source_ids": ["SOURCE-001"],
            "source_count": 1,
            "extracted_at": "2024-01-01T00:00:00Z",
            "extraction_run_id": "RUN-001",
            "raw_json": {"entity_id": "ENTITY-001", "name": "Zimbabwe Energy Regulatory Authority"},
            "ingestion_status": "active",
        },
        {
            "entity_id": "ENTITY-002",
            "name": "Energy Commission",
            "rita_type": "government agency",
            "aliases": [],
            "metadata": {"country": "Zimbabwe"},
            "source_ids": ["SOURCE-002"],
            "source_count": 1,
            "extracted_at": "2024-01-02T00:00:00Z",
            "extraction_run_id": "RUN-002",
            "raw_json": {"entity_id": "ENTITY-002", "name": "Energy Commission"},
            "ingestion_status": "active",
        },
    ]

    input_path = tmp_path / "batch.json"
    input_path.write_text(json.dumps(export, ensure_ascii=False), encoding="utf-8")

    result = await ProductionRunner(pipeline=pipeline).run_file(input_path, tmp_path / "batch-output")

    assert result.processed == 2
    assert result.succeeded == 1
    assert result.failed == 1
    assert len(result.results) == 2
    assert result.results[0].entity.name == "Zimbabwe Energy Regulatory Authority"
    assert result.results[1].status == "insufficient"


def test_production_runner_rejects_invalid_input_file(tmp_path):
    input_path = tmp_path / "bad.json"
    input_path.write_text('{"bad": true}', encoding="utf-8")

    with pytest.raises(ValueError):
        ProductionRunner().load_entities(input_path)
