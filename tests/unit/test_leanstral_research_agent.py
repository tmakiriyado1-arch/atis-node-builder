"""Tests for Leanstral Research Agent with Tool-Driven Research Loop."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch, Mock

import pytest

from app.services.research.leanstral_research_agent import (
    LeanstralResearchAgent,
    LeanstralResearchResult,
    Message,
    ResearchStatus,
    RetrievalResult,
    ToolCall,
    ToolDefinition,
    ToolResult,
    SEARCH_WEB_TOOL,
    OPEN_URL_TOOL,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_api_key():
    return "test-api-key"


@pytest.fixture
def mock_base_search_url():
    return "https://script.google.com/macros/s/test/exec"


@pytest.fixture
def mock_leanstral_agent(mock_api_key, mock_base_search_url):
    """Create a LeanstralResearchAgent with mocked providers."""
    with patch('app.services.research.leanstral_research_agent.config') as mock_config:
        mock_config.MISTRAL_API_KEY = mock_api_key
        mock_config.MISTRAL_MODEL = "labs-leanstral-1-5"
        mock_config.APPS_SCRIPT_SEARCH_URL = mock_base_search_url
        
        agent = LeanstralResearchAgent(
            api_key=mock_api_key,
            base_search_url=mock_base_search_url,
            max_tool_rounds=5,
            max_search_calls=2,
            max_open_url_calls=3,
            max_total_retrieved_chars=50000,
        )
        
        # Mock the providers
        agent.search_provider = AsyncMock()
        agent.page_crawler = AsyncMock()
        
        return agent


# =============================================================================
# Test 1: Leanstral requests search_web
# =============================================================================

@pytest.mark.asyncio
async def test_leanstral_requests_search_web(mock_leanstral_agent):
    """Test that Leanstral can request search_web and NORA executes it."""
    # Mock search provider to return test URLs
    mock_search_results = [
        {"url": "https://www.theotec.org/about", "title": "About Theotechnic College", "rank": 1},
        {"url": "https://www.activeministry.org/theotechnic", "title": "Theotechnic College", "rank": 2},
    ]
    mock_leanstral_agent.search_provider.search = AsyncMock(return_value=mock_search_results)
    
    # Mock Leanstral API to return a tool call for search_web, then a stop
    mock_tool_call_response = {
        "finish_reason": "tool_calls",
        "message": {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_123",
                    "type": "function",
                    "function": {
                        "name": "search_web",
                        "arguments": json.dumps({"query": "Theotechnic College"})
                    }
                }
            ]
        }
    }
    
    mock_stop_response = {
        "finish_reason": "stop",
        "message": {
            "content": json.dumps({
                "entity": {"name": "Theotechnic College", "type": "Educational Institution"},
                "status": "SUFFICIENT",
                "sources": [],
                "claims": [],
            }),
            "tool_calls": []
        }
    }
    
    with patch.object(mock_leanstral_agent, '_call_leanstral', new_callable=AsyncMock) as mock_call:
        mock_call.side_effect = [mock_tool_call_response, mock_stop_response]
        
        result = await mock_leanstral_agent.research(
            entity_name="Theotechnic College",
            entity_type="Educational Institution",
        )
        
        # Verify search was called
        assert mock_leanstral_agent.search_provider.search.called
        call_args = mock_leanstral_agent.search_provider.search.call_args
        assert call_args[1]['query'] == "Theotechnic College"
        
        # Verify tool call was executed
        assert len(result.tool_calls_executed) == 1
        assert result.tool_calls_executed[0].name == "search_web"
        assert result.tool_calls_executed[0].arguments == {"query": "Theotechnic College"}
        
        # Verify tool result was created
        assert len(result.tool_results) == 1
        assert result.tool_results[0].ok is True
        tool_content = json.loads(result.tool_results[0].content)
        assert tool_content["ok"] is True
        assert len(tool_content["results"]) == 2


# =============================================================================
# Test 2: Leanstral requests open_url
# =============================================================================

@pytest.mark.asyncio
async def test_leanstral_requests_open_url(mock_leanstral_agent):
    """Test that Leanstral can request open_url and NORA retrieves the page."""
    # Mock page crawler to return test content
    mock_crawl_result = MagicMock()
    mock_crawl_result.success = True
    mock_crawl_result.url = "https://www.theotec.org/about"
    mock_crawl_result.final_url = "https://www.theotec.org/about"
    mock_crawl_result.status_code = 200
    mock_crawl_result.content_type = "text/html"
    mock_crawl_result.title = "About Theotechnic College"
    mock_crawl_result.content = "Theotechnic College is an educational institution."
    mock_crawl_result.error = None
    
    mock_leanstral_agent.page_crawler.crawl_url = AsyncMock(return_value=mock_crawl_result)
    
    # Mock Leanstral API to return a tool call for open_url, then a stop
    mock_tool_call_response = {
        "finish_reason": "tool_calls",
        "message": {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_456",
                    "type": "function",
                    "function": {
                        "name": "open_url",
                        "arguments": json.dumps({"url": "https://www.theotec.org/about"})
                    }
                }
            ]
        }
    }
    
    mock_stop_response = {
        "finish_reason": "stop",
        "message": {
            "content": json.dumps({
                "entity": {"name": "Theotechnic College"},
                "status": "SUFFICIENT",
                "sources": [],
                "claims": [],
            }),
            "tool_calls": []
        }
    }
    
    with patch.object(mock_leanstral_agent, '_call_leanstral', new_callable=AsyncMock) as mock_call:
        mock_call.side_effect = [mock_tool_call_response, mock_stop_response]
        
        result = await mock_leanstral_agent.research(
            entity_name="Theotechnic College",
        )
        
        # Verify page crawler was called
        assert mock_leanstral_agent.page_crawler.crawl_url.called
        call_args = mock_leanstral_agent.page_crawler.crawl_url.call_args
        assert call_args[0][0] == "https://www.theotec.org/about"
        
        # Verify tool call was executed
        assert len(result.tool_calls_executed) == 1
        assert result.tool_calls_executed[0].name == "open_url"
        assert result.tool_calls_executed[0].arguments == {"url": "https://www.theotec.org/about"}
        
        # Verify tool result was created
        assert len(result.tool_results) == 1
        assert result.tool_results[0].ok is True
        tool_content = json.loads(result.tool_results[0].content)
        assert tool_content["ok"] is True
        assert tool_content["content"] == "Theotechnic College is an educational institution."


# =============================================================================
# Test 3: Tool result is returned correctly with tool_call_id
# =============================================================================

@pytest.mark.asyncio
async def test_tool_result_preserves_tool_call_id(mock_leanstral_agent):
    """Test that tool results preserve the exact tool_call_id."""
    # Mock search provider
    mock_leanstral_agent.search_provider.search = AsyncMock(return_value=[])
    
    # Mock Leanstral API to return a tool call, then stop
    mock_tool_call_response = {
        "finish_reason": "tool_calls",
        "message": {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_unique_12345",
                    "type": "function",
                    "function": {
                        "name": "search_web",
                        "arguments": json.dumps({"query": "test"})
                    }
                }
            ]
        }
    }
    
    mock_stop_response = {
        "finish_reason": "stop",
        "message": {
            "content": json.dumps({
                "entity": {"name": "Test Entity"},
                "status": "SUFFICIENT",
                "sources": [],
                "claims": [],
            }),
            "tool_calls": []
        }
    }
    
    with patch.object(mock_leanstral_agent, '_call_leanstral', new_callable=AsyncMock) as mock_call:
        mock_call.side_effect = [mock_tool_call_response, mock_stop_response]
        
        result = await mock_leanstral_agent.research(
            entity_name="Test Entity",
        )
        
        # Verify tool call ID is preserved
        assert len(result.tool_calls_executed) == 1
        assert result.tool_calls_executed[0].id == "call_unique_12345"
        
        assert len(result.tool_results) == 1
        assert result.tool_results[0].tool_call_id == "call_unique_12345"


# =============================================================================
# Test 4: Multi-step loop (search -> open_url -> stop)
# =============================================================================

@pytest.mark.asyncio
async def test_multi_step_tool_loop(mock_leanstral_agent):
    """Test a multi-step conversation: search_web -> open_url -> stop."""
    # Mock search provider
    mock_search_results = [
        {"url": "https://www.theotec.org/about", "title": "About", "rank": 1},
    ]
    mock_leanstral_agent.search_provider.search = AsyncMock(return_value=mock_search_results)
    
    # Mock page crawler
    mock_crawl_result = MagicMock()
    mock_crawl_result.success = True
    mock_crawl_result.url = "https://www.theotec.org/about"
    mock_crawl_result.final_url = "https://www.theotec.org/about"
    mock_crawl_result.status_code = 200
    mock_crawl_result.content_type = "text/html"
    mock_crawl_result.title = "About Theotechnic College"
    mock_crawl_result.content = "Theotechnic College offers engineering programs."
    mock_crawl_result.error = None
    mock_leanstral_agent.page_crawler.crawl_url = AsyncMock(return_value=mock_crawl_result)
    
    # Mock Leanstral API responses for multi-step
    # First call: search_web
    first_response = {
        "finish_reason": "tool_calls",
        "message": {
            "content": "I need to find information about Theotechnic College.",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "search_web",
                        "arguments": json.dumps({"query": "Theotechnic College"})
                    }
                }
            ]
        }
    }
    
    # Second call: open_url (after search results)
    second_response = {
        "finish_reason": "tool_calls",
        "message": {
            "content": "I found a URL, now I'll inspect it.",
            "tool_calls": [
                {
                    "id": "call_2",
                    "type": "function",
                    "function": {
                        "name": "open_url",
                        "arguments": json.dumps({"url": "https://www.theotec.org/about"})
                    }
                }
            ]
        }
    }
    
    # Third call: stop (final answer)
    final_content = json.dumps({
        "entity": {"name": "Theotechnic College", "type": "Educational Institution"},
        "status": "SUFFICIENT",
        "sources": [
            {
                "url": "https://www.theotec.org/about",
                "title": "About Theotechnic College",
                "content_preview": "Theotechnic College offers engineering programs.",
                "evidence": [
                    {
                        "claim": "Theotechnic College offers engineering programs",
                        "passage": "Theotechnic College offers engineering programs.",
                        "evidence_type": "FACT"
                    }
                ]
            }
        ],
        "claims": [
            {
                "claim": "Theotechnic College offers engineering programs",
                "source_urls": ["https://www.theotec.org/about"],
                "evidence_type": "FACT"
            }
        ],
        "uncertainties": [],
        "rejected_sources": []
    })
    third_response = {
        "finish_reason": "stop",
        "message": {
            "content": final_content,
            "tool_calls": []
        }
    }
    
    with patch.object(mock_leanstral_agent, '_call_leanstral', new_callable=AsyncMock) as mock_call:
        mock_call.side_effect = [first_response, second_response, third_response]
        
        result = await mock_leanstral_agent.research(
            entity_name="Theotechnic College",
        )
        
        # Verify all steps were executed
        assert result.tool_rounds == 3
        assert len(result.tool_calls_executed) == 2  # search_web + open_url
        assert result.tool_calls_executed[0].name == "search_web"
        assert result.tool_calls_executed[1].name == "open_url"
        
        # Verify final result
        assert result.status == ResearchStatus.COMPLETED
        assert result.entity_name == "Theotechnic College"
        assert len(result.claims) == 1
        assert result.claims[0]["claim"] == "Theotechnic College offers engineering programs"
        assert len(result.sources) == 1
        assert result.sources[0]["url"] == "https://www.theotec.org/about"


# =============================================================================
# Test 5: Retrieval failure
# =============================================================================

@pytest.mark.asyncio
async def test_retrieval_failure_handled(mock_leanstral_agent):
    """Test that retrieval failures are returned as tool results and don't crash."""
    # Mock page crawler to fail
    mock_crawl_result = MagicMock()
    mock_crawl_result.success = False
    mock_crawl_result.url = "https://www.example.com/blocked"
    mock_crawl_result.final_url = "https://www.example.com/blocked"
    mock_crawl_result.status_code = 403
    mock_crawl_result.content = ""
    mock_crawl_result.title = ""
    mock_crawl_result.error = "HTTP 403 Forbidden"
    mock_leanstral_agent.page_crawler.crawl_url = AsyncMock(return_value=mock_crawl_result)
    
    # Mock Leanstral API to request a URL that will fail, then stop
    mock_tool_call_response = {
        "finish_reason": "tool_calls",
        "message": {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_fail",
                    "type": "function",
                    "function": {
                        "name": "open_url",
                        "arguments": json.dumps({"url": "https://www.example.com/blocked"})
                    }
                }
            ]
        }
    }
    
    mock_stop_response = {
        "finish_reason": "stop",
        "message": {
            "content": json.dumps({
                "entity": {"name": "Test"},
                "status": "INSUFFICIENT",
                "sources": [],
                "claims": [],
            }),
            "tool_calls": []
        }
    }
    
    with patch.object(mock_leanstral_agent, '_call_leanstral', new_callable=AsyncMock) as mock_call:
        mock_call.side_effect = [mock_tool_call_response, mock_stop_response]
        
        result = await mock_leanstral_agent.research(
            entity_name="Test Entity",
        )
        
        # Verify the run didn't crash
        assert result.status != ResearchStatus.FAILED
        
        # Verify tool result shows failure
        assert len(result.tool_results) == 1
        assert result.tool_results[0].ok is False
        tool_content = json.loads(result.tool_results[0].content)
        assert tool_content["ok"] is False
        http_status = tool_content.get("http_status", 0)
        error = tool_content.get("error", "")
        assert "403" in str(http_status) or "403" in error or "Forbidden" in error


# =============================================================================
# Test 6: Tool limit enforcement
# =============================================================================

@pytest.mark.asyncio
async def test_tool_limit_enforcement(mock_leanstral_agent):
    """Test that tool limits are enforced."""
    # Set very low limits for testing
    mock_leanstral_agent.max_tool_rounds = 2
    mock_leanstral_agent.max_search_calls = 1
    
    # Mock search provider
    mock_leanstral_agent.search_provider.search = AsyncMock(return_value=[])
    
    # Mock Leanstral API to keep requesting tools
    mock_response = {
        "finish_reason": "tool_calls",
        "message": {
            "content": "",
            "tool_calls": [
                {
                    "id": f"call_{i}",
                    "type": "function",
                    "function": {
                        "name": "search_web",
                        "arguments": json.dumps({"query": f"test {i}"})
                    }
                }
                for i in range(10)  # Request more than limit
            ]
        }
    }
    
    with patch.object(mock_leanstral_agent, '_call_leanstral', new_callable=AsyncMock) as mock_call:
        mock_call.return_value = mock_response
        
        result = await mock_leanstral_agent.research(
            entity_name="Test Entity",
        )
        
        # Verify limits were enforced
        assert result.status == ResearchStatus.INCOMPLETE
        assert "limit" in result.error_message.lower() or "exceeded" in result.error_message.lower()
        assert result.tool_rounds <= 2


# =============================================================================
# Test 7: Invalid tool arguments
# =============================================================================

@pytest.mark.asyncio
async def test_invalid_tool_arguments(mock_leanstral_agent):
    """Test that malformed tool calls are rejected safely."""
    # Mock Leanstral API to return invalid tool call (missing required argument)
    mock_tool_call_response = {
        "finish_reason": "tool_calls",
        "message": {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_invalid",
                    "type": "function",
                    "function": {
                        "name": "search_web",
                        "arguments": json.dumps({})  # Missing query
                    }
                }
            ]
        }
    }
    
    mock_stop_response = {
        "finish_reason": "stop",
        "message": {
            "content": json.dumps({
                "entity": {"name": "Test"},
                "status": "INSUFFICIENT",
                "sources": [],
                "claims": [],
            }),
            "tool_calls": []
        }
    }
    
    with patch.object(mock_leanstral_agent, '_call_leanstral', new_callable=AsyncMock) as mock_call:
        mock_call.side_effect = [mock_tool_call_response, mock_stop_response]
        
        result = await mock_leanstral_agent.research(
            entity_name="Test Entity",
        )
        
        # Verify the run handled the error
        assert result.status != ResearchStatus.FAILED
        assert len(result.tool_results) == 1
        assert result.tool_results[0].ok is False
        tool_content = json.loads(result.tool_results[0].content)
        assert tool_content["ok"] is False


# =============================================================================
# Test 8: Conversation history preservation
# =============================================================================

@pytest.mark.asyncio
async def test_conversation_history_preservation(mock_leanstral_agent):
    """Test that conversation history is preserved across tool rounds."""
    # Mock providers
    mock_leanstral_agent.search_provider.search = AsyncMock(return_value=[])
    mock_crawl_result = MagicMock()
    mock_crawl_result.success = True
    mock_crawl_result.url = "https://example.com"
    mock_crawl_result.final_url = "https://example.com"
    mock_crawl_result.status_code = 200
    mock_crawl_result.content = "Test content"
    mock_leanstral_agent.page_crawler.crawl_url = AsyncMock(return_value=mock_crawl_result)
    
    # Mock responses
    first_response = {
        "finish_reason": "tool_calls",
        "message": {
            "content": "First message",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "search_web",
                        "arguments": json.dumps({"query": "test"})
                    }
                }
            ]
        }
    }
    
    second_response = {
        "finish_reason": "stop",
        "message": {
            "content": json.dumps({"status": "SUFFICIENT", "sources": [], "claims": []}),
            "tool_calls": []
        }
    }
    
    with patch.object(mock_leanstral_agent, '_call_leanstral', new_callable=AsyncMock) as mock_call:
        mock_call.side_effect = [first_response, second_response]
        
        result = await mock_leanstral_agent.research(
            entity_name="Test Entity",
        )
        
        # Verify conversation history
        assert len(result.messages) == 5  # system + user + assistant + tool + assistant
        assert result.messages[0].role == "system"
        assert result.messages[1].role == "user"
        assert result.messages[2].role == "assistant"
        assert result.messages[3].role == "tool"
        assert result.messages[4].role == "assistant"


# =============================================================================
# Test 9: Unknown tool handling
# =============================================================================

@pytest.mark.asyncio
async def test_unknown_tool_handling(mock_leanstral_agent):
    """Test that unknown tools are handled gracefully."""
    # Mock Leanstral API to request unknown tool
    mock_tool_call_response = {
        "finish_reason": "tool_calls",
        "message": {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_unknown",
                    "type": "function",
                    "function": {
                        "name": "unknown_tool",
                        "arguments": json.dumps({"param": "value"})
                    }
                }
            ]
        }
    }
    
    mock_stop_response = {
        "finish_reason": "stop",
        "message": {
            "content": json.dumps({
                "entity": {"name": "Test"},
                "status": "INSUFFICIENT",
                "sources": [],
                "claims": [],
            }),
            "tool_calls": []
        }
    }
    
    with patch.object(mock_leanstral_agent, '_call_leanstral', new_callable=AsyncMock) as mock_call:
        mock_call.side_effect = [mock_tool_call_response, mock_stop_response]
        
        result = await mock_leanstral_agent.research(
            entity_name="Test Entity",
        )
        
        # Verify unknown tool was handled
        assert len(result.tool_results) == 1
        assert result.tool_results[0].ok is False
        tool_content = json.loads(result.tool_results[0].content)
        assert tool_content["ok"] is False
        assert "Unknown tool" in tool_content.get("error", "")


# =============================================================================
# Test 10: Empty query handling
# =============================================================================

@pytest.mark.asyncio
async def test_empty_query_handling(mock_leanstral_agent):
    """Test that empty queries are handled safely."""
    # Mock Leanstral API to request search with empty query
    mock_tool_call_response = {
        "finish_reason": "tool_calls",
        "message": {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_empty",
                    "type": "function",
                    "function": {
                        "name": "search_web",
                        "arguments": json.dumps({"query": ""})
                    }
                }
            ]
        }
    }
    
    mock_stop_response = {
        "finish_reason": "stop",
        "message": {
            "content": json.dumps({
                "entity": {"name": "Test"},
                "status": "INSUFFICIENT",
                "sources": [],
                "claims": [],
            }),
            "tool_calls": []
        }
    }
    
    with patch.object(mock_leanstral_agent, '_call_leanstral', new_callable=AsyncMock) as mock_call:
        mock_call.side_effect = [mock_tool_call_response, mock_stop_response]
        
        result = await mock_leanstral_agent.research(
            entity_name="Test Entity",
        )
        
        # Verify empty query was handled
        assert len(result.tool_results) == 1
        assert result.tool_results[0].ok is False
        tool_content = json.loads(result.tool_results[0].content)
        assert tool_content["ok"] is False
        assert "Query is required" in tool_content.get("error", "") or "required" in tool_content.get("error", "").lower()


# =============================================================================
# Test 11: Theotechnic College integration test
# =============================================================================

@pytest.mark.asyncio
async def test_theotechnic_college_integration(mock_leanstral_agent):
    """Integration test for Theotechnic College research."""
    # Mock search provider to return Theotechnic URLs
    mock_search_results = [
        {"url": "https://www.theotec.org/about", "title": "About Theotechnic College", "rank": 1},
        {"url": "https://www.activeministry.org/theotechnic", "title": "Theotechnic College", "rank": 2},
        {"url": "https://www.pennco.tech", "title": "Pennco Tech", "rank": 3},  # Should be rejected
    ]
    mock_leanstral_agent.search_provider.search = AsyncMock(return_value=mock_search_results)
    
    # Mock page crawler for theotec.org
    mock_theotec_crawl = MagicMock()
    mock_theotec_crawl.success = True
    mock_theotec_crawl.url = "https://www.theotec.org/about"
    mock_theotec_crawl.final_url = "https://www.theotec.org/about"
    mock_theotec_crawl.status_code = 200
    mock_theotec_crawl.content_type = "text/html"
    mock_theotec_crawl.title = "About Theotechnic College"
    mock_theotec_crawl.content = (
        "Theotechnic College is a Christian educational institution in Zimbabwe. "
        "It is operated under the ACTIVE Ministry. "
        "The college offers engineering and construction programmes. "
        "Contact: info@theotec.org"
    )
    
    # Mock page crawler for activeministry.org
    mock_activeministry_crawl = MagicMock()
    mock_activeministry_crawl.success = True
    mock_activeministry_crawl.url = "https://www.activeministry.org/theotechnic"
    mock_activeministry_crawl.final_url = "https://www.activeministry.org/theotechnic"
    mock_activeministry_crawl.status_code = 200
    mock_activeministry_crawl.content_type = "text/html"
    mock_activeministry_crawl.title = "Theotechnic College - ACTIVE Ministry"
    mock_activeministry_crawl.content = (
        "Theotechnic College is operated by ACTIVE Ministry. "
        "We provide technical education and training."
    )
    
    # Mock page crawler for pennco.tech (should fail or be rejected)
    mock_pennco_crawl = MagicMock()
    mock_pennco_crawl.success = True
    mock_pennco_crawl.url = "https://www.pennco.tech"
    mock_pennco_crawl.final_url = "https://www.pennco.tech"
    mock_pennco_crawl.status_code = 200
    mock_pennco_crawl.content_type = "text/html"
    mock_pennco_crawl.title = "Pennco Tech - Trade School"
    mock_pennco_crawl.content = "Pennco Tech is a trade school in Pennsylvania."
    
    mock_leanstral_agent.page_crawler.crawl_url = AsyncMock()
    
    def mock_crawl_side_effect(url):
        if "theotec.org" in url:
            return mock_theotec_crawl
        elif "activeministry.org" in url:
            return mock_activeministry_crawl
        else:
            return mock_pennco_crawl
    
    mock_leanstral_agent.page_crawler.crawl_url.side_effect = mock_crawl_side_effect
    
    # Mock Leanstral responses
    # 1. Search for Theotechnic College
    first_response = {
        "finish_reason": "tool_calls",
        "message": {
            "content": "I need to find information about Theotechnic College.",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "search_web",
                        "arguments": json.dumps({"query": "Theotechnic College"})
                    }
                }
            ]
        }
    }
    
    # 2. Open theotec.org
    second_response = {
        "finish_reason": "tool_calls",
        "message": {
            "content": "I found candidate URLs. Let me inspect theotec.org first.",
            "tool_calls": [
                {
                    "id": "call_2",
                    "type": "function",
                    "function": {
                        "name": "open_url",
                        "arguments": json.dumps({"url": "https://www.theotec.org/about"})
                    }
                }
            ]
        }
    }
    
    # 3. Open activeministry.org for cross-check
    third_response = {
        "finish_reason": "tool_calls",
        "message": {
            "content": "Let me verify with another source.",
            "tool_calls": [
                {
                    "id": "call_3",
                    "type": "function",
                    "function": {
                        "name": "open_url",
                        "arguments": json.dumps({"url": "https://www.activeministry.org/theotechnic"})
                    }
                }
            ]
        }
    }
    
    # 4. Final answer
    final_content = json.dumps({
        "entity": {
            "name": "Theotechnic College",
            "type": "Educational Institution"
        },
        "status": "SUFFICIENT",
        "sources": [
            {
                "url": "https://www.theotec.org/about",
                "title": "About Theotechnic College",
                "content_preview": "Theotechnic College is a Christian educational institution...",
                "evidence": [
                    {
                        "claim": "Theotechnic College is a Christian educational institution in Zimbabwe",
                        "passage": "Theotechnic College is a Christian educational institution in Zimbabwe.",
                        "evidence_type": "FACT"
                    },
                    {
                        "claim": "Theotechnic College offers engineering and construction programmes",
                        "passage": "It offers engineering and construction programmes.",
                        "evidence_type": "FACT"
                    },
                    {
                        "claim": "Theotechnic College contact is info@theotec.org",
                        "passage": "Contact: info@theotec.org",
                        "evidence_type": "ATTRIBUTE"
                    }
                ]
            },
            {
                "url": "https://www.activeministry.org/theotechnic",
                "title": "Theotechnic College - ACTIVE Ministry",
                "content_preview": "Theotechnic College is operated by ACTIVE Ministry...",
                "evidence": [
                    {
                        "claim": "Theotechnic College is operated by ACTIVE Ministry",
                        "passage": "Theotechnic College is operated by ACTIVE Ministry.",
                        "evidence_type": "RELATIONSHIP"
                    }
                ]
            }
        ],
        "claims": [
            {
                "claim": "Theotechnic College is a Christian educational institution in Zimbabwe",
                "source_urls": ["https://www.theotec.org/about"],
                "evidence_type": "FACT"
            },
            {
                "claim": "Theotechnic College offers engineering and construction programmes",
                "source_urls": ["https://www.theotec.org/about"],
                "evidence_type": "FACT"
            },
            {
                "claim": "Theotechnic College is operated by ACTIVE Ministry",
                "source_urls": [
                    "https://www.theotec.org/about",
                    "https://www.activeministry.org/theotechnic"
                ],
                "evidence_type": "RELATIONSHIP"
            },
            {
                "claim": "Theotechnic College contact is info@theotec.org",
                "source_urls": ["https://www.theotec.org/about"],
                "evidence_type": "ATTRIBUTE"
            }
        ],
        "uncertainties": [],
        "rejected_sources": [
            {
                "url": "https://www.pennco.tech",
                "reason": "FALSE_ENTITY"
            }
        ]
    })
    fourth_response = {
        "finish_reason": "stop",
        "message": {
            "content": final_content,
            "tool_calls": []
        }
    }
    
    with patch.object(mock_leanstral_agent, '_call_leanstral', new_callable=AsyncMock) as mock_call:
        mock_call.side_effect = [first_response, second_response, third_response, fourth_response]
        
        result = await mock_leanstral_agent.research(
            entity_name="Theotechnic College",
            entity_type="Educational Institution",
            research_task=(
                "Research Theotechnic College. Determine: "
                "1) What the organization is, "
                "2) Its relationship with ACTIVE Ministry, "
                "3) Its stated educational focus, "
                "4) Its current registration/admission status, "
                "5) Relevant official contact information. "
                "Use web discovery and inspect primary sources. "
                "Do not invent information. Every factual claim must have a source."
            )
        )
        
        # Verify comprehensive research
        assert result.status == ResearchStatus.COMPLETED
        assert result.entity_name == "Theotechnic College"
        assert result.entity_type == "Educational Institution"
        
        # Verify tool usage
        assert result.tool_rounds == 4
        assert result.search_calls == 1
        assert result.open_url_calls == 2
        
        # Verify claims
        assert len(result.claims) >= 4
        claim_texts = [c["claim"] for c in result.claims]
        assert any("Christian educational institution" in c for c in claim_texts)
        assert any("engineering" in c.lower() for c in claim_texts)
        assert any("ACTIVE Ministry" in c for c in claim_texts)
        assert any("info@theotec.org" in c for c in claim_texts)
        
        # Verify sources
        assert len(result.sources) >= 2
        source_urls = [s["url"] for s in result.sources]
        assert "https://www.theotec.org/about" in source_urls
        assert "https://www.activeministry.org/theotechnic" in source_urls
        
        # Verify evidence
        assert len(result.evidence) >= 4
        
        # Verify rejected sources
        assert len(result.metadata.get("rejected_sources", [])) >= 1
        rejected_urls = [r["url"] for r in result.metadata.get("rejected_sources", [])]
        assert "https://www.pennco.tech" in rejected_urls
