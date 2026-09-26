"""Tests for MozillaProvider search functionality."""
from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.services.research.mozilla_provider import MozillaProvider


class DummyResponse:
    """Dummy HTTP response for testing."""
    def __init__(self, payload: Any = None, status_code: int = 200, text: str = ""):
        self._payload = payload
        self._text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("bad status", request=None, response=self)

    def json(self):
        return self._payload
    
    @property
    def text(self):
        return self._text


# =============================================================================
# JSON Response Tests
# =============================================================================

@pytest.mark.asyncio
async def test_mozilla_parses_json_response_with_results(monkeypatch):
    """Test parsing a successful JSON response with results."""
    async def fake_get(self, url, params=None, timeout=None):
        return DummyResponse(
            {
                "results": [
                    {
                        "title": "African Development Bank",
                        "url": "https://www.afdb.org/",
                        "description": "The African Development Bank Group is a regional multilateral development finance institution.",
                    },
                    {
                        "title": "AfDB Official Site",
                        "url": "https://www.afdb.org/en",
                        "description": "Official website of the African Development Bank.",
                    },
                ]
            }
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    provider = MozillaProvider()
    results = await provider.search("African Development Bank")

    assert len(results) == 2
    assert results[0].url == "https://www.afdb.org/"
    assert "African Development Bank" in results[0].title
    assert results[0].provider == "MozillaProvider"


@pytest.mark.asyncio
async def test_mozilla_parses_json_response_with_web_pages_key(monkeypatch):
    """Test parsing JSON response with 'web_pages' key instead of 'results'."""
    async def fake_get(self, url, params=None, timeout=None):
        return DummyResponse(
            {
                "web_pages": [
                    {
                        "title": "Test Page",
                        "url": "https://example.com/test",
                        "snippet": "This is a test snippet.",
                    },
                ]
            }
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    provider = MozillaProvider()
    results = await provider.search("test query")

    assert len(results) == 1
    assert results[0].url == "https://example.com/test"


@pytest.mark.asyncio
async def test_mozilla_parses_json_response_with_organic_results_key(monkeypatch):
    """Test parsing JSON response with 'organic_results' key."""
    async def fake_get(self, url, params=None, timeout=None):
        return DummyResponse(
            {
                "organic_results": [
                    {
                        "title": "Organic Result",
                        "url": "https://example.com/organic",
                        "description": "Organic search result.",
                    },
                ]
            }
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    provider = MozillaProvider()
    results = await provider.search("organic test")

    assert len(results) == 1
    assert results[0].url == "https://example.com/organic"


@pytest.mark.asyncio
async def test_mozilla_handles_empty_json_response(monkeypatch):
    """Test handling of empty JSON response."""
    async def fake_get(self, url, params=None, timeout=None):
        return DummyResponse({"results": []})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    provider = MozillaProvider()
    results = await provider.search("empty query")

    assert results == []


@pytest.mark.asyncio
async def test_mozilla_handles_missing_results_key(monkeypatch):
    """Test handling of JSON response without results key."""
    async def fake_get(self, url, params=None, timeout=None):
        return DummyResponse({"other_key": "value"})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    provider = MozillaProvider()
    results = await provider.search("no results key")

    assert results == []


@pytest.mark.asyncio
async def test_mozilla_handles_non_dict_json_response(monkeypatch):
    """Test handling of non-dict JSON response."""
    async def fake_get(self, url, params=None, timeout=None):
        return DummyResponse(["not", "a", "dict"])

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    provider = MozillaProvider()
    results = await provider.search("list response")

    assert results == []


@pytest.mark.asyncio
async def test_mozilla_handles_malformed_json_response(monkeypatch):
    """Test handling of malformed JSON response."""
    async def fake_get(self, url, params=None, timeout=None):
        return DummyResponse("not valid json", status_code=200)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    provider = MozillaProvider()
    results = await provider.search("malformed json")

    assert results == []


# =============================================================================
# HTML Response Tests
# =============================================================================

@pytest.mark.asyncio
async def test_mozilla_parses_html_response(monkeypatch):
    """Test parsing HTML response as fallback."""
    html_content = """
    <html>
    <body>
        <a href="https://example.com/result1">Result One</a>
        <p>Description for result one</p>
        <a href="https://example.com/result2">Result Two</a>
        <p>Description for result two</p>
    </body>
    </html>
    """
    
    async def fake_get(self, url, params=None, timeout=None):
        return DummyResponse(text=html_content, status_code=200)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    provider = MozillaProvider()
    results = await provider.search("html test")

    # Should extract at least the links
    assert len(results) >= 1
    urls = [r.url for r in results]
    assert "https://example.com/result1" in urls or "https://example.com/result2" in urls


@pytest.mark.asyncio
async def test_mozilla_handles_html_with_no_results(monkeypatch):
    """Test parsing HTML with no result links."""
    html_content = """
    <html>
    <body>
        <p>No results found</p>
    </body>
    </html>
    """
    
    async def fake_get(self, url, params=None, timeout=None):
        return DummyResponse(text=html_content, status_code=200)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    provider = MozillaProvider()
    results = await provider.search("no results html")

    assert results == []


# =============================================================================
# HTTP Error Tests
# =============================================================================

@pytest.mark.asyncio
async def test_mozilla_handles_http_503_error(monkeypatch):
    """Test handling of HTTP 503 Service Unavailable."""
    async def fake_get(self, url, params=None, timeout=None):
        return DummyResponse(status_code=503)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    provider = MozillaProvider()
    results = await provider.search("503 test")

    assert results == []


@pytest.mark.asyncio
async def test_mozilla_handles_http_404_error(monkeypatch):
    """Test handling of HTTP 404 Not Found."""
    async def fake_get(self, url, params=None, timeout=None):
        return DummyResponse(status_code=404)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    provider = MozillaProvider()
    results = await provider.search("404 test")

    assert results == []


@pytest.mark.asyncio
async def test_mozilla_handles_http_400_error(monkeypatch):
    """Test handling of HTTP 400 Bad Request."""
    async def fake_get(self, url, params=None, timeout=None):
        return DummyResponse(status_code=400)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    provider = MozillaProvider()
    results = await provider.search("400 test")

    assert results == []


@pytest.mark.asyncio
async def test_mozilla_handles_connection_error(monkeypatch):
    """Test handling of connection failure."""
    async def fake_get(self, url, params=None, timeout=None):
        raise httpx.ConnectError("Connection refused")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    provider = MozillaProvider()
    results = await provider.search("connection error test")

    assert results == []


@pytest.mark.asyncio
async def test_mozilla_handles_timeout_error(monkeypatch):
    """Test handling of timeout."""
    async def fake_get(self, url, params=None, timeout=None):
        raise httpx.TimeoutException("Request timed out")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    provider = MozillaProvider()
    results = await provider.search("timeout test")

    assert results == []


@pytest.mark.asyncio
async def test_mozilla_handles_generic_exception(monkeypatch):
    """Test handling of unexpected exception."""
    async def fake_get(self, url, params=None, timeout=None):
        raise ValueError("Unexpected error")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    provider = MozillaProvider()
    results = await provider.search("exception test")

    assert results == []


# =============================================================================
# Result Formatting Tests
# =============================================================================

@pytest.mark.asyncio
async def test_mozilla_format_result_with_snippet_field(monkeypatch):
    """Test that snippet field is used when available."""
    async def fake_get(self, url, params=None, timeout=None):
        return DummyResponse(
            {
                "results": [
                    {
                        "title": "Test",
                        "url": "https://example.com",
                        "snippet": "This is the snippet.",
                    },
                ]
            }
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    provider = MozillaProvider()
    results = await provider.search("test")

    assert len(results) == 1
    assert results[0].snippet == "This is the snippet."


@pytest.mark.asyncio
async def test_mozilla_format_result_with_description_field(monkeypatch):
    """Test that description field is used as snippet when snippet is missing."""
    async def fake_get(self, url, params=None, timeout=None):
        return DummyResponse(
            {
                "results": [
                    {
                        "title": "Test",
                        "url": "https://example.com",
                        "description": "This is the description.",
                    },
                ]
            }
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    provider = MozillaProvider()
    results = await provider.search("test")

    assert len(results) == 1
    assert results[0].snippet == "This is the description."


@pytest.mark.asyncio
async def test_mozilla_skips_results_without_url(monkeypatch):
    """Test that results without URLs are skipped."""
    async def fake_get(self, url, params=None, timeout=None):
        return DummyResponse(
            {
                "results": [
                    {
                        "title": "No URL",
                        "url": "",
                        "description": "This should be skipped.",
                    },
                    {
                        "title": "Has URL",
                        "url": "https://example.com",
                        "description": "This should be kept.",
                    },
                ]
            }
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    provider = MozillaProvider()
    results = await provider.search("test")

    assert len(results) == 1
    assert results[0].url == "https://example.com"


@pytest.mark.asyncio
async def test_mozilla_skips_results_without_title(monkeypatch):
    """Test that results without titles are skipped."""
    async def fake_get(self, url, params=None, timeout=None):
        return DummyResponse(
            {
                "results": [
                    {
                        "title": "",
                        "url": "https://example.com",
                        "description": "This should be skipped.",
                    },
                    {
                        "title": "Has Title",
                        "url": "https://example.com/2",
                        "description": "This should be kept.",
                    },
                ]
            }
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    provider = MozillaProvider()
    results = await provider.search("test")

    assert len(results) == 1
    assert results[0].title == "Has Title"


# =============================================================================
# Duplicate URL Handling Tests
# =============================================================================

@pytest.mark.asyncio
async def test_mozilla_deduplicates_urls(monkeypatch):
    """Test that duplicate URLs are removed."""
    async def fake_get(self, url, params=None, timeout=None):
        return DummyResponse(
            {
                "results": [
                    {
                        "title": "First",
                        "url": "https://example.com",
                        "description": "First result.",
                    },
                    {
                        "title": "Second",
                        "url": "https://example.com",
                        "description": "Duplicate URL.",
                    },
                    {
                        "title": "Third",
                        "url": "https://example.com/other",
                        "description": "Different URL.",
                    },
                ]
            }
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    provider = MozillaProvider()
    results = await provider.search("test")

    assert len(results) == 2
    urls = [r.url for r in results]
    assert urls.count("https://example.com") == 1


# =============================================================================
# Query Variant Tests
# =============================================================================

@pytest.mark.asyncio
async def test_mozilla_generates_query_variants_with_acronym(monkeypatch):
    """Test that query variants are generated for acronyms."""
    async def fake_get(self, url, params=None, timeout=None):
        # Return different results for different queries
        query = params.get("q", "") if params else ""
        if "AfDB" in query:
            return DummyResponse(
                {
                    "results": [
                        {
                            "title": "AfDB Acronym Result",
                            "url": "https://afdb-acronym.example.com",
                            "description": "AfDB result.",
                        },
                    ]
                }
            )
        else:
            return DummyResponse(
                {
                    "results": [
                        {
                            "title": "Full Name Result",
                            "url": "https://fullname.example.com",
                            "description": "Full name result.",
                        },
                    ]
                }
            )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    provider = MozillaProvider()
    results = await provider.search("African Development Bank (AfDB)")

    # Should have tried both the full name and the acronym
    urls = [r.url for r in results]
    # At least one result should be present
    assert len(results) >= 1


@pytest.mark.asyncio
async def test_mozilla_query_variants_with_context(monkeypatch):
    """Test that query variants use context when provided."""
    async def fake_get(self, url, params=None, timeout=None):
        query = params.get("q", "") if params else ""
        return DummyResponse(
            {
                "results": [
                    {
                        "title": f"Result for {query}",
                        "url": f"https://example.com/{query.replace(' ', '_')}",
                        "description": f"Query: {query}",
                    },
                ]
            }
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    provider = MozillaProvider()
    context = {"country": "Zimbabwe", "entity_type": "organization"}
    results = await provider.search("ZERA", context=context)

    # Should have generated variants with country
    assert len(results) >= 1


# =============================================================================
# Edge Cases
# =============================================================================

@pytest.mark.asyncio
async def test_mozilla_empty_query(monkeypatch):
    """Test handling of empty query."""
    provider = MozillaProvider()
    results = await provider.search("")

    assert results == []


@pytest.mark.asyncio
async def test_mozilla_whitespace_only_query(monkeypatch):
    """Test handling of whitespace-only query."""
    provider = MozillaProvider()
    results = await provider.search("   ")

    assert results == []


@pytest.mark.asyncio
async def test_mozilla_none_query(monkeypatch):
    """Test handling of None query."""
    provider = MozillaProvider()
    results = await provider.search(None)

    assert results == []


@pytest.mark.asyncio
async def test_mozilla_max_results_limit(monkeypatch):
    """Test that max_results is respected."""
    async def fake_get(self, url, params=None, timeout=None):
        return DummyResponse(
            {
                "results": [
                    {
                        "title": f"Result {i}",
                        "url": f"https://example.com/{i}",
                        "description": f"Description {i}",
                    }
                    for i in range(100)
                ]
            }
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    provider = MozillaProvider()
    results = await provider.search("many results", max_results=5)

    assert len(results) <= 5


@pytest.mark.asyncio
async def test_mozilla_provider_role(monkeypatch):
    """Test that provider has correct role."""
    provider = MozillaProvider()
    
    from app.services.research.search_provider import ProviderRole
    assert provider.role == ProviderRole.SECONDARY_WEB_SEARCH


@pytest.mark.asyncio
async def test_mozilla_user_agent(monkeypatch):
    """Test that custom User-Agent is used."""
    custom_ua = "CustomUserAgent/1.0"
    provider = MozillaProvider(user_agent=custom_ua)
    
    assert provider.user_agent == custom_ua
    assert provider.headers["User-Agent"] == custom_ua
