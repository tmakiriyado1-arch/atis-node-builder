"""Research must fail honestly until providers are implemented."""
import pytest

from app.services.research_engine import ResearchEngine, SearchProvider


@pytest.mark.asyncio
async def test_unconfigured_search_provider_is_explicitly_unavailable():
    with pytest.raises(NotImplementedError):
        await SearchProvider().search("test")


@pytest.mark.asyncio
async def test_research_does_not_report_placeholder_success():
    result = await ResearchEngine(SearchProvider(), object()).research("Test Entity")

    assert result.status == "failed"
    assert result.claims == []
    assert result.error_message