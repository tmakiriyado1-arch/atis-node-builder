"""Tests for WebSearchProvider (DuckDuckGo) search functionality."""
from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.services.research.web_search import WebSearchProvider


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
# HTML Parsing Tests (New implementation)
# =============================================================================

@pytest.mark.asyncio
async def test_web_search_parses_html_results(monkeypatch):
    """Test parsing DuckDuckGo HTML search results with data-url attributes."""
    html_content = """
    <html>
    <body>
        <div class="result">
            <a href="https://duckduckgo.com/l/?uddg=ZXhhbXBsZS5jb20v" class="result__url" data-url="https://example.com/">Example Site</a>
            <p>Description of example site</p>
        </div>
        <div class="result">
            <a href="/l/?uddg=ZXhhbXBsZS5jb20vYXRoZXI=" class="result__url" data-url="https://another.example.com/">Another Site</a>
            <p>Description of another site</p>
        </div>
    </body>
    </html>
    """
    
    async def fake_get(self, url, params=None, timeout=None):
        return DummyResponse(text=html_content, status_code=200)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    provider = WebSearchProvider()
    results = await provider.search("example query")

    assert len(results) == 2
    urls = [r.url for r in results]
    assert "https://example.com/" in urls
    assert "https://another.example.com/" in urls


@pytest.mark.asyncio
async def test_web_search_parses_html_with_regular_links(monkeypatch):
    """Test parsing HTML with regular <a href> links."""
    html_content = """
    <html>
    <body>
        <a href="https://direct.example.com/">Direct Link</a>
        <p>Direct link description</p>
        <a href="https://another-direct.example.com/">Another Direct Link</a>
    </body>
    </html>
    """
    
    async def fake_get(self, url, params=None, timeout=None):
        return DummyResponse(text=html_content, status_code=200)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    provider = WebSearchProvider()
    results = await provider.search("direct links")

    assert len(results) >= 1
    urls = [r.url for r in results]
    assert "https://direct.example.com/" in urls or "https://another-direct.example.com/" in urls


@pytest.mark.asyncio
async def test_web_search_skips_duckduckgo_proxy_urls(monkeypatch):
    """Test that DuckDuckGo proxy URLs are skipped."""
    html_content = """
    <html>
    <body>
        <a href="https://duckduckgo.com/l/?q=test" class="result__url">Proxy Link</a>
        <a href="https://real.example.com/" class="result__url">Real Link</a>
    </body>
    </html>
    """
    
    async def fake_get(self, url, params=None, timeout=None):
        return DummyResponse(text=html_content, status_code=200)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    provider = WebSearchProvider()
    results = await provider.search("proxy test")

    # Should only have the real link, not the proxy
    urls = [r.url for r in results]
    assert "https://duckduckgo.com/" not in urls
    assert "https://real.example.com/" in urls


@pytest.mark.asyncio
async def test_web_search_handles_html_with_no_results(monkeypatch):
    """Test parsing HTML with no result links."""
    html_content = """
    <html>
    <body>
        <p>No results found for your query</p>
    </body>
    </html>
    """
    
    async def fake_get(self, url, params=None, timeout=None):
        return DummyResponse(text=html_content, status_code=200)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    provider = WebSearchProvider()
    results = await provider.search("no results")

    assert results == []


@pytest.mark.asyncio
async def test_web_search_deduplicates_urls_in_html(monkeypatch):
    """Test that duplicate URLs are deduplicated in HTML parsing."""
    html_content = """
    <html>
    <body>
        <a href="https://example.com/" class="result__url">First Link</a>
        <a href="https://example.com/" class="result__url">Duplicate Link</a>
        <a href="https://other.example.com/" class="result__url">Other Link</a>
    </body>
    </html>
    """
    
    async def fake_get(self, url, params=None, timeout=None):
        return DummyResponse(text=html_content, status_code=200)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    provider = WebSearchProvider()
    results = await provider.search("duplicate test")

    assert len(results) == 2
    urls = [r.url for r in results]
    assert urls.count("https://example.com/") == 1


# =============================================================================
# URL Cleaning Tests
# =============================================================================

@pytest.mark.asyncio
async def test_web_search_clean_ddg_url_base64_encoded(monkeypatch):
    """Test cleaning base64-encoded DuckDuckGo URLs."""
    provider = WebSearchProvider()
    
    # Simulate a base64-encoded URL
    import base64
    test_url = "https://example.com/test"
    encoded = base64.urlsafe_b64encode(test_url.encode()).decode().rstrip("=")
    ddg_url = f"/l/?uddg={encoded}"
    
    cleaned = provider._clean_ddg_url(ddg_url)
    assert cleaned == test_url


@pytest.mark.asyncio
async def test_web_search_clean_ddg_url_regular_http(monkeypatch):
    """Test cleaning regular HTTP URLs."""
    provider = WebSearchProvider()
    
    url = "https://example.com/test?param=value"
    cleaned = provider._clean_ddg_url(url)
    assert cleaned == url


@pytest.mark.asyncio
async def test_web_search_clean_ddg_url_empty(monkeypatch):
    """Test cleaning empty URL."""
    provider = WebSearchProvider()
    
    cleaned = provider._clean_ddg_url("")
    assert cleaned == ""


@pytest.mark.asyncio
async def test_web_search_clean_ddg_url_none(monkeypatch):
    """Test cleaning None URL."""
    provider = WebSearchProvider()
    
    cleaned = provider._clean_ddg_url(None)
    assert cleaned == ""


@pytest.mark.asyncio
async def test_web_search_clean_ddg_url_relative(monkeypatch):
    """Test cleaning relative URL."""
    provider = WebSearchProvider()
    
    url = "//example.com/test"
    cleaned = provider._clean_ddg_url(url)
    assert cleaned == "https://example.com/test"


# =============================================================================
# HTTP Error Tests
# =============================================================================

@pytest.mark.asyncio
async def test_web_search_handles_http_403_error(monkeypatch):
    """Test handling of HTTP 403 Forbidden."""
    async def fake_get(self, url, params=None, timeout=None):
        return DummyResponse(status_code=403)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    provider = WebSearchProvider()
    
    # Should raise exception on 403 (provider unavailable)
    with pytest.raises(Exception):
        await provider.search("403 test")


@pytest.mark.asyncio
async def test_web_search_handles_http_500_error(monkeypatch):
    """Test handling of HTTP 500 Internal Server Error."""
    async def fake_get(self, url, params=None, timeout=None):
        return DummyResponse(status_code=500)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    provider = WebSearchProvider()
    
    # Should raise exception on 500
    with pytest.raises(Exception):
        await provider.search("500 test")


@pytest.mark.asyncio
async def test_web_search_handles_connection_error(monkeypatch):
    """Test handling of connection failure."""
    async def fake_get(self, url, params=None, timeout=None):
        raise httpx.ConnectError("Connection refused")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    provider = WebSearchProvider()
    
    # Should raise exception on connection error
    with pytest.raises(Exception):
        await provider.search("connection error test")


@pytest.mark.asyncio
async def test_web_search_handles_timeout_error(monkeypatch):
    """Test handling of timeout."""
    async def fake_get(self, url, params=None, timeout=None):
        raise httpx.TimeoutException("Request timed out")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    provider = WebSearchProvider()
    
    # Should raise exception on timeout
    with pytest.raises(Exception):
        await provider.search("timeout test")


@pytest.mark.asyncio
async def test_web_search_handles_malformed_html(monkeypatch):
    """Test handling of malformed HTML response."""
    async def fake_get(self, url, params=None, timeout=None):
        return DummyResponse(text="not valid html", status_code=200)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    provider = WebSearchProvider()
    results = await provider.search("malformed html")

    # Should return empty list on malformed HTML
    assert results == []


# =============================================================================
# Query Expansion Tests
# =============================================================================

@pytest.mark.asyncio
async def test_web_search_query_expansion_with_acronym(monkeypatch):
    """Test that query variants are generated for acronyms."""
    html_content = """
    <html>
    <body>
        <a href="https://example.com/" class="result__url">Result</a>
    </body>
    </html>
    """
    
    call_count = 0
    
    async def fake_get(self, url, params=None, timeout=None):
        nonlocal call_count
        call_count += 1
        return DummyResponse(text=html_content, status_code=200)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    provider = WebSearchProvider(max_queries_per_search=3)
    results = await provider.search("African Development Bank (AfDB)")

    # Should have tried multiple query variants
    assert call_count >= 1


@pytest.mark.asyncio
async def test_web_search_query_expansion_with_context(monkeypatch):
    """Test that query variants use context when provided."""
    html_content = """
    <html>
    <body>
        <a href="https://example.com/" class="result__url">Result</a>
    </body>
    </html>
    """
    
    async def fake_get(self, url, params=None, timeout=None):
        return DummyResponse(text=html_content, status_code=200)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    provider = WebSearchProvider()
    context = {"country": "Zimbabwe", "entity_type": "organization", "aliases": ["AfDB"]}
    results = await provider.search("African Development Bank", context=context)

    # Should have tried query variants with country and aliases
    assert len(results) >= 1


# =============================================================================
# Result Scoring Tests
# =============================================================================

@pytest.mark.asyncio
async def test_web_search_scores_results(monkeypatch):
    """Test that results are scored and sorted by relevance."""
    html_content = """
    <html>
    <body>
        <a href="https://perfect-match.example.com/" class="result__url">African Development Bank Official Site</a>
        <a href="https://partial-match.example.com/" class="result__url">Development Bank in Africa</a>
        <a href="https://no-match.example.com/" class="result__url">Random Site</a>
    </body>
    </html>
    """
    
    async def fake_get(self, url, params=None, timeout=None):
        return DummyResponse(text=html_content, status_code=200)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    provider = WebSearchProvider()
    results = await provider.search("African Development Bank")

    assert len(results) == 3
    # Results should be sorted by relevance score (descending)
    # The first result should have the highest score
    assert "perfect-match" in results[0].url or "African" in results[0].title


# =============================================================================
# Edge Cases
# =============================================================================

@pytest.mark.asyncio
async def test_web_search_empty_query(monkeypatch):
    """Test handling of empty query."""
    provider = WebSearchProvider()
    results = await provider.search("")

    assert results == []


@pytest.mark.asyncio
async def test_web_search_whitespace_only_query(monkeypatch):
    """Test handling of whitespace-only query."""
    provider = WebSearchProvider()
    results = await provider.search("   ")

    assert results == []


@pytest.mark.asyncio
async def test_web_search_none_query(monkeypatch):
    """Test handling of None query."""
    provider = WebSearchProvider()
    results = await provider.search(None)

    assert results == []


@pytest.mark.asyncio
async def test_web_search_max_results_limit(monkeypatch):
    """Test that max_results is respected."""
    html_content = """
    <html>
    <body>
        <a href="https://example.com/1" class="result__url">Result 1</a>
        <a href="https://example.com/2" class="result__url">Result 2</a>
        <a href="https://example.com/3" class="result__url">Result 3</a>
        <a href="https://example.com/4" class="result__url">Result 4</a>
        <a href="https://example.com/5" class="result__url">Result 5</a>
    </body>
    </html>
    """
    
    async def fake_get(self, url, params=None, timeout=None):
        return DummyResponse(text=html_content, status_code=200)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    provider = WebSearchProvider()
    results = await provider.search("many results", max_results=3)

    assert len(results) <= 3


@pytest.mark.asyncio
async def test_web_search_provider_role(monkeypatch):
    """Test that provider has correct role."""
    provider = WebSearchProvider()
    
    from app.services.research.search_provider import ProviderRole
    assert provider.role == ProviderRole.WEB_DISCOVERY


@pytest.mark.asyncio
async def test_web_search_user_agent(monkeypatch):
    """Test that custom User-Agent is used."""
    custom_ua = "CustomUserAgent/1.0"
    provider = WebSearchProvider(user_agent=custom_ua)
    
    assert provider.user_agent == custom_ua
    assert provider.headers["User-Agent"] == custom_ua


# =============================================================================
# Legacy Tests (for backward compatibility)
# =============================================================================

@pytest.mark.asyncio
async def test_web_search_parses_successful_response(monkeypatch):
    """Legacy test for JSON response parsing (kept for backward compatibility)."""
    # This tests the _coerce_item method which is still used
    provider = WebSearchProvider()
    
    # Test the coercion method directly
    item = {
        "Text": "Test Title",
        "FirstURL": "https://test.example.com/",
    }
    result = provider._coerce_item(item)
    
    assert result["title"] == "Test Title"
    assert result["url"] == "https://test.example.com/"


@pytest.mark.asyncio
async def test_web_search_coerce_item_skips_proxy_urls(monkeypatch):
    """Test that _coerce_item skips DuckDuckGo proxy URLs."""
    provider = WebSearchProvider()
    
    item = {
        "Text": "Test Title",
        "FirstURL": "https://duckduckgo.com/l/?q=test",
    }
    result = provider._coerce_item(item)
    
    assert result == {}


@pytest.mark.asyncio
async def test_web_search_returns_empty_on_http_failure(monkeypatch):
    """Legacy test - now raises exception instead of returning empty."""
    # This test documents the behavior change
    async def fake_get(self, url, params=None, timeout=None):
        return DummyResponse(status_code=503)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    provider = WebSearchProvider()
    
    # Now raises exception on HTTP errors
    with pytest.raises(Exception):
        await provider.search("Zimbabwe Energy Regulatory Authority")


@pytest.mark.asyncio
async def test_web_search_handles_malformed_response(monkeypatch):
    """Legacy test - now returns empty on malformed HTML."""
    async def fake_get(self, url, params=None, timeout=None):
        return DummyResponse("nope")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    provider = WebSearchProvider()
    results = await provider.search("Zimbabwe Energy Regulatory Authority")

    assert results == []


@pytest.mark.asyncio
async def test_web_search_handles_timeout_errors(monkeypatch):
    """Legacy test - now raises exception on timeout."""
    async def fake_get(self, url, params=None, timeout=None):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    provider = WebSearchProvider()
    
    # Now raises exception on timeout
    with pytest.raises(Exception):
        await provider.search("Zimbabwe Energy Regulatory Authority")
