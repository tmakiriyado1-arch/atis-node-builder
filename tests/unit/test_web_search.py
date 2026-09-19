from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.services.research.web_search import WebSearchProvider


class DummyResponse:
    def __init__(self, payload: Any = None, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("bad status", request=None, response=self)

    def json(self):
        return self._payload


@pytest.mark.asyncio
async def test_web_search_parses_successful_response(monkeypatch):
    async def fake_get(self, url, params=None, timeout=None):
        return DummyResponse(
            {
                "RelatedTopics": [
                    {
                        "FirstURL": "https://example.com/zera",
                        "Text": "Zimbabwe Energy Regulatory Authority is the energy regulator.",
                    },
                    {"FirstURL": "https://example.com/licensing", "Text": "Licensing guidance."},
                ]
            }
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    provider = WebSearchProvider()
    results = await provider.search("Zimbabwe Energy Regulatory Authority")

    assert len(results) == 2
    assert results[0]["url"] == "https://example.com/zera"
    assert "Zimbabwe Energy Regulatory Authority" in results[0]["snippet"]


@pytest.mark.asyncio
async def test_web_search_returns_empty_on_http_failure(monkeypatch):
    async def fake_get(self, url, params=None, timeout=None):
        return DummyResponse(status_code=503)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    provider = WebSearchProvider()
    results = await provider.search("Zimbabwe Energy Regulatory Authority")

    assert results == []


@pytest.mark.asyncio
async def test_web_search_handles_malformed_response(monkeypatch):
    async def fake_get(self, url, params=None, timeout=None):
        return DummyResponse("nope")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    provider = WebSearchProvider()
    results = await provider.search("Zimbabwe Energy Regulatory Authority")

    assert results == []


@pytest.mark.asyncio
async def test_web_search_handles_timeout_errors(monkeypatch):
    async def fake_get(self, url, params=None, timeout=None):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    provider = WebSearchProvider()
    results = await provider.search("Zimbabwe Energy Regulatory Authority")

    assert results == []
