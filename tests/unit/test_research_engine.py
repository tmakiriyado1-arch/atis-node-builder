from __future__ import annotations

import json
from typing import Any, Dict, List

import pytest

from app.services.research.evidence import EvidenceRecord, normalize_search_result
from app.services.research.mistral_enrichment import enrich_evidence_with_mistral
from app.services.research.search_provider import SearchProvider
from app.services.research_engine import ResearchEngine


class FakeProvider(SearchProvider):
    def __init__(self, results: List[Dict[str, Any]] | None = None, exc: Exception | None = None):
        self._results = results or []
        self._exc = exc

    async def search(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        if self._exc is not None:
            raise self._exc
        return self._results


@pytest.mark.asyncio
async def test_unconfigured_search_provider_is_explicitly_unavailable():
    with pytest.raises(NotImplementedError):
        await SearchProvider().search("test")


def test_entity_name_produces_a_query():
    engine = ResearchEngine(FakeProvider())

    queries = engine.generate_queries("Zimbabwe Energy Regulatory Authority")

    assert queries[0] == "Zimbabwe Energy Regulatory Authority"
    assert len(queries) >= 1


def test_contextual_entity_produces_no_more_than_two_queries():
    engine = ResearchEngine(FakeProvider())

    queries = engine.generate_queries(
        "Zimbabwe Energy Regulatory Authority",
        entity_type="government agency",
        context="registry and licensing",
    )

    assert len(queries) <= 2
    assert queries[0] == "Zimbabwe Energy Regulatory Authority"


@pytest.mark.asyncio
async def test_research_success_returns_completed_result():
    provider = FakeProvider(
        [
            {
                "title": "ZERA overview",
                "url": "https://example.com/zera",
                "snippet": "The authority regulates electricity and licensing.",
            },
            {
                "title": "ZERA licensing",
                "url": "https://example.com/licensing",
                "snippet": "The regulator manages mining and energy licenses.",
            },
        ]
    )
    engine = ResearchEngine(provider)

    result = await engine.research(
        "Zimbabwe Energy Regulatory Authority",
        entity_type="government agency",
        fields_to_research=["name", "entity_type"],
    )

    assert result.status == "completed"
    assert result.sources_count == 2
    assert len(result.claims) == 2
    assert result.claims[0].source_title == "ZERA overview"
    assert result.claims[0].source_url == "https://example.com/zera"
    assert result.claims[0].evidence_passage == "The authority regulates electricity and licensing."


@pytest.mark.asyncio
async def test_duplicate_urls_are_removed():
    provider = FakeProvider(
        [
            {
                "title": "ZERA overview",
                "url": "https://example.com/zera",
                "snippet": "The authority regulates licensing.",
            },
            {
                "title": "Same result",
                "url": "https://example.com/zera",
                "snippet": "duplicate record",
            },
        ]
    )
    engine = ResearchEngine(provider)

    result = await engine.research("Zimbabwe Energy Regulatory Authority")

    assert result.status == "completed"
    assert result.sources_count == 1
    assert len(result.claims) == 1


@pytest.mark.asyncio
async def test_empty_provider_result_produces_clear_failure():
    engine = ResearchEngine(FakeProvider([]))

    result = await engine.research("Missing Entity")

    assert result.status == "failed"
    assert result.claims == []
    assert "No usable search results" in result.error_message


@pytest.mark.asyncio
async def test_provider_exception_is_handled_cleanly():
    engine = ResearchEngine(FakeProvider(exc=RuntimeError("temporary outage")))

    result = await engine.research("Zimbabwe Energy Regulatory Authority")

    assert result.status == "failed"
    assert "Search provider failed" in result.error_message
    assert result.claims == []


def test_evidence_normalizes_provider_result():
    evidence = normalize_search_result(
        {
            "title": "Example Result",
            "url": "https://example.com/page/?utm_source=google#section",
            "snippet": "Energy regulator information",
        },
        entity_id="RITA-123",
        entity_name="Zimbabwe Energy Regulatory Authority",
        query="Zimbabwe Energy Regulatory Authority",
        source="public_web_search",
    )

    assert isinstance(evidence, EvidenceRecord)
    assert evidence.url == "https://example.com/page"
    assert evidence.original_url == "https://example.com/page/?utm_source=google#section"
    assert evidence.entity_id == "RITA-123"
    assert evidence.entity_name == "Zimbabwe Energy Regulatory Authority"
    assert evidence.source == "public_web_search"
    assert evidence.query == "Zimbabwe Energy Regulatory Authority"
    assert evidence.retrieved_at.tzinfo is not None


def test_duplicate_evidence_resolves_to_one_canonical_url():
    first = normalize_search_result(
        {"title": "Page", "url": "https://example.com/page", "snippet": "One"},
        entity_id="RITA-1",
        entity_name="Acme",
        query="Acme",
    )
    second = normalize_search_result(
        {"title": "Page", "url": "https://example.com/page/#section", "snippet": "Two"},
        entity_id="RITA-1",
        entity_name="Acme",
        query="Acme research",
    )

    assert first is not None and second is not None
    assert first.url == second.url
    assert first.original_url != second.original_url or first.url == second.url


def test_invalid_urls_are_rejected():
    evidence = normalize_search_result({"title": "Bad", "url": "not-a-url", "snippet": "text"})

    assert evidence is None


def test_meaningful_query_parameter_is_preserved():
    evidence = normalize_search_result(
        {"title": "Search", "url": "https://example.com/search?q=energy", "snippet": "energy"},
        entity_name="Acme",
        query="Acme",
    )

    assert evidence is not None
    assert "q=energy" in evidence.url


@pytest.mark.asyncio
async def test_mistral_enrichment_returns_valid_claims(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "claims": [
                                        {
                                            "subject": "Zimbabwe Energy Regulatory Authority",
                                            "predicate": "regulates",
                                            "object": "energy licensing",
                                            "claim_text": "Zimbabwe Energy Regulatory Authority regulates energy licensing.",
                                            "evidence_urls": ["https://example.com/zera"],
                                        }
                                    ]
                                }
                            )
                        }
                    }
                ]
            }

    async def fake_post(self, url, headers=None, json=None, timeout=None):
        return FakeResponse()

    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)
    evidence = [
        EvidenceRecord(
            url="https://example.com/zera",
            title="ZERA overview",
            snippet="The authority regulates energy licensing.",
            source="public_web_search",
            query="Zimbabwe Energy Regulatory Authority",
            entity_name="Zimbabwe Energy Regulatory Authority",
        )
    ]

    claims = await enrich_evidence_with_mistral("Zimbabwe Energy Regulatory Authority", evidence, api_key="test-key")

    assert len(claims) == 1
    assert claims[0].source_url == "https://example.com/zera"
    assert claims[0].claim == "Zimbabwe Energy Regulatory Authority regulates energy licensing."
    assert claims[0].extraction_method == "mistral"


@pytest.mark.asyncio
async def test_mistral_enrichment_rejects_claims_with_unprovided_evidence(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "claims": [
                                        {
                                            "subject": "Example",
                                            "predicate": "says",
                                            "object": "X",
                                            "claim_text": "Example says X.",
                                            "evidence_urls": ["https://example.com/other"],
                                        }
                                    ]
                                }
                            )
                        }
                    }
                ]
            }

    async def fake_post(self, url, headers=None, json=None, timeout=None):
        return FakeResponse()

    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)
    evidence = [
        EvidenceRecord(
            url="https://example.com/zera",
            title="ZERA overview",
            snippet="The authority regulates energy licensing.",
            source="public_web_search",
            query="Zimbabwe Energy Regulatory Authority",
            entity_name="Zimbabwe Energy Regulatory Authority",
        )
    ]

    claims = await enrich_evidence_with_mistral("Zimbabwe Energy Regulatory Authority", evidence, api_key="test-key")

    assert claims == []


@pytest.mark.asyncio
async def test_mistral_enrichment_skips_empty_evidence(monkeypatch):
    called = False

    async def fake_post(self, url, headers=None, json=None, timeout=None):
        nonlocal called
        called = True
        raise AssertionError("unexpected API call")

    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)

    claims = await enrich_evidence_with_mistral("Entity", [], api_key="test-key")

    assert claims == []
    assert called is False


@pytest.mark.asyncio
async def test_mistral_enrichment_handles_invalid_json(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "not valid json"}}]}

    async def fake_post(self, url, headers=None, json=None, timeout=None):
        return FakeResponse()

    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)
    evidence = [
        EvidenceRecord(
            url="https://example.com/zera",
            title="ZERA overview",
            snippet="The authority regulates energy licensing.",
            source="public_web_search",
            query="Zimbabwe Energy Regulatory Authority",
            entity_name="Zimbabwe Energy Regulatory Authority",
        )
    ]

    claims = await enrich_evidence_with_mistral("Zimbabwe Energy Regulatory Authority", evidence, api_key="test-key")

    assert claims == []


@pytest.mark.asyncio
async def test_mistral_enrichment_handles_api_failure(monkeypatch):
    async def fake_post(self, url, headers=None, json=None, timeout=None):
        raise RuntimeError("API is down")

    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)
    evidence = [
        EvidenceRecord(
            url="https://example.com/zera",
            title="ZERA overview",
            snippet="The authority regulates energy licensing.",
            source="public_web_search",
            query="Zimbabwe Energy Regulatory Authority",
            entity_name="Zimbabwe Energy Regulatory Authority",
        )
    ]

    claims = await enrich_evidence_with_mistral("Zimbabwe Energy Regulatory Authority", evidence, api_key="test-key")

    assert claims == []
