"""Leanstral 1.5 Research Agent with Tool-Driven Research Loop.

This module implements a research agent using Leanstral 1.5 as the reasoning engine
with custom tool calls for web discovery and URL retrieval.

Architecture:
    RITA Entity
        -> Leanstral 1.5 (reasoning agent)
            -> search_web tool (Apps Script bridge)
            -> open_url tool (PageCrawler)
        -> Structured research result
        -> Existing NORA evidence/claims pipeline

Key Principle:
    Leanstral ONLY emits tool calls. NORA executes them.
    Leanstral does NOT directly browse the internet.
    NORA provides the tools: search_web and open_url.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple

import httpx

from app import config
from app.logging import logger
from app.services.research.apps_script_provider import AppsScriptSearchProvider
from app.services.research.evidence import EvidenceRecord, EvidenceStatus, ExtractionQuality, RetrievalStatus
from app.services.research.page_crawler import CrawlResult, PageCrawler


# =============================================================================
# Research Status
# =============================================================================

class ResearchStatus(str, Enum):
    """Status of the research execution."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    INCOMPLETE = "incomplete"  # Hit tool limits
    INSUFFICIENT = "insufficient"  # Not enough evidence found


# =============================================================================
# Tool Definitions
# =============================================================================

@dataclass
class ToolDefinition:
    """Definition of a custom tool for Leanstral."""
    name: str
    description: str
    parameters: Dict[str, Any]


# Custom tools for Leanstral
SEARCH_WEB_TOOL = ToolDefinition(
    name="search_web",
    description=(
        "Search the web for relevant sources. Returns candidate URLs only. "
        "Use this when you need to discover sources for an entity or research question. "
        "Search results are discovery candidates, not verified evidence."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The web search query."
            }
        },
        "required": ["query"]
    }
)

OPEN_URL_TOOL = ToolDefinition(
    name="open_url",
    description=(
        "Retrieve readable content from a webpage at the supplied URL. "
        "Use this to inspect a source and obtain factual evidence. "
        "Returns the extracted text content, not raw HTML."
    ),
    parameters={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The complete URL to retrieve."
            }
        },
        "required": ["url"]
    }
)


# =============================================================================
# Tool Call Models
# =============================================================================

@dataclass
class ToolCall:
    """Represents a tool call from Leanstral."""
    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class ToolResult:
    """Result of executing a tool call."""
    tool_call_id: str
    content: str
    ok: bool = True
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Message:
    """A message in the conversation."""
    role: str  # "user", "assistant", "tool"
    content: Optional[str] = None
    tool_calls: List[ToolCall] = field(default_factory=list)
    tool_call_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        result = {"role": self.role}
        if self.content:
            result["content"] = self.content
        if self.tool_calls:
            result["tool_calls"] = [
                {"id": tc.id, "type": "function", "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}
                for tc in self.tool_calls
            ]
        if self.tool_call_id:
            result["tool_call_id"] = self.tool_call_id
        return result


# =============================================================================
# Retrieval Result
# =============================================================================

@dataclass
class RetrievalResult:
    """Result of retrieving a URL."""
    url: str
    final_url: str
    http_status: int
    content_type: str
    content: str
    title: str
    success: bool
    error: Optional[str] = None
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def to_tool_result(self, tool_call_id: str) -> ToolResult:
        """Convert to tool result format for Leanstral."""
        if self.success:
            return ToolResult(
                tool_call_id=tool_call_id,
                content=json.dumps({
                    "url": self.url,
                    "final_url": self.final_url,
                    "http_status": self.http_status,
                    "content_type": self.content_type,
                    "title": self.title,
                    "content": self.content,
                    "success": True,
                }),
                ok=True,
                metadata={
                    "url": self.url,
                    "final_url": self.final_url,
                    "http_status": self.http_status,
                    "content_length": len(self.content),
                }
            )
        else:
            return ToolResult(
                tool_call_id=tool_call_id,
                content=json.dumps({
                    "url": self.url,
                    "error": self.error or "Retrieval failed",
                    "http_status": self.http_status,
                    "success": False,
                }),
                ok=False,
                error=self.error,
                metadata={"url": self.url, "error": self.error}
            )


# =============================================================================
# Research Result
# =============================================================================

@dataclass
class LeanstralResearchResult:
    """Complete result from Leanstral research."""
    entity_name: str
    entity_type: Optional[str] = None
    status: ResearchStatus = ResearchStatus.PENDING
    messages: List[Message] = field(default_factory=list)
    tool_calls_executed: List[ToolCall] = field(default_factory=list)
    tool_results: List[ToolResult] = field(default_factory=list)
    urls_discovered: List[str] = field(default_factory=list)
    urls_retrieved: List[str] = field(default_factory=list)
    urls_failed: List[str] = field(default_factory=list)
    total_retrieved_chars: int = 0
    tool_rounds: int = 0
    search_calls: int = 0
    open_url_calls: int = 0
    successful_searches: int = 0
    failed_searches: int = 0
    successful_url_opens: int = 0
    failed_url_opens: int = 0
    error_message: Optional[str] = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    
    # Research output
    claims: List[Dict[str, Any]] = field(default_factory=list)
    sources: List[Dict[str, Any]] = field(default_factory=list)
    evidence: List[EvidenceRecord] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_evidence_records(self) -> List[EvidenceRecord]:
        """Convert retrieved sources to EvidenceRecords."""
        records = []
        for source in self.sources:
            record = EvidenceRecord(
                url=source.get("url", ""),
                title=source.get("title", ""),
                snippet=source.get("content", "")[:500],
                content=source.get("content", ""),
                normalized_text=source.get("content", ""),
                source="leanstral_web_research",
                query=self.entity_name,
                entity_name=self.entity_name,
                entity_id=None,
                http_status=source.get("http_status", 0),
                content_type=source.get("content_type", "text/html"),
                retrieval_status=RetrievalStatus.SUCCESS if source.get("success", False) else RetrievalStatus.FAILED,
                extraction_quality=ExtractionQuality.SUBSTANTIVE,
                evidence_status=EvidenceStatus.USABLE,
                metadata={
                    "research_method": "leanstral_tool_driven",
                    "retrieved_at": source.get("retrieved_at", ""),
                }
            )
            records.append(record)
        return records


# =============================================================================
# Leanstral Research Agent
# =============================================================================

class LeanstralResearchAgent:
    """Research agent using Leanstral 1.5 with custom tool calls.
    
    This agent implements a tool-driven research loop where:
    1. Leanstral decides it needs web information
    2. Leanstral emits search_web or open_url tool calls
    3. NORA executes those tool calls
    4. NORA returns tool results to Leanstral
    5. Leanstral reasons over the returned evidence
    6. Leanstral may request additional searches/pages
    7. Final structured research result
    
    The LLM is NOT given the illusion that it can directly browse the internet.
    Leanstral ONLY emits tool calls. NORA executes them.
    """
    
    # Tool definitions
    TOOLS = [SEARCH_WEB_TOOL, OPEN_URL_TOOL]
    
    # Default limits
    DEFAULT_MAX_TOOL_ROUNDS = 8
    DEFAULT_MAX_SEARCH_CALLS = 3
    DEFAULT_MAX_OPEN_URL_CALLS = 6
    DEFAULT_MAX_TOTAL_RETRIEVED_CHARS = 120000
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_search_url: Optional[str] = None,
        max_tool_rounds: int = DEFAULT_MAX_TOOL_ROUNDS,
        max_search_calls: int = DEFAULT_MAX_SEARCH_CALLS,
        max_open_url_calls: int = DEFAULT_MAX_OPEN_URL_CALLS,
        max_total_retrieved_chars: int = DEFAULT_MAX_TOTAL_RETRIEVED_CHARS,
        timeout: float = 60.0,
        page_crawler: Optional[PageCrawler] = None,
        search_provider: Optional[AppsScriptSearchProvider] = None,
    ):
        """Initialize the Leanstral research agent.
        
        Args:
            api_key: Mistral API key (defaults to config.MISTRAL_API_KEY)
            model: Model to use (defaults to config.MISTRAL_MODEL or 'labs-leanstral-1-5')
            base_search_url: Base URL for Apps Script search bridge
            max_tool_rounds: Maximum number of tool call rounds
            max_search_calls: Maximum number of search_web calls
            max_open_url_calls: Maximum number of open_url calls
            max_total_retrieved_chars: Maximum total characters retrieved
            timeout: Timeout for API calls
            page_crawler: Optional custom PageCrawler instance
            search_provider: Optional custom search provider
        """
        self.api_key = api_key or (getattr(config, 'MISTRAL_API_KEY', None) or "").strip()
        self.model = model or (getattr(config, 'MISTRAL_MODEL', None) or 'labs-leanstral-1-5')
        self.base_search_url = base_search_url or getattr(config, 'APPS_SCRIPT_SEARCH_URL', None)
        
        # Limits
        self.max_tool_rounds = max_tool_rounds
        self.max_search_calls = max_search_calls
        self.max_open_url_calls = max_open_url_calls
        self.max_total_retrieved_chars = max_total_retrieved_chars
        
        logger.info(f"[LEANSTRAL_AGENT] Limits: max_tool_rounds={self.max_tool_rounds}, "
                   f"max_search_calls={self.max_search_calls}, "
                   f"max_open_url_calls={self.max_open_url_calls}")
        
        self.timeout = timeout
        
        # Initialize providers
        self.page_crawler = page_crawler or PageCrawler(
            timeout=15.0,
            max_content_length=100000,
        )
        self.search_provider = search_provider or AppsScriptSearchProvider(
            base_url=self.base_search_url,
            timeout=15.0,
        )
        
        logger.info(f"[LEANSTRAL_AGENT] Initialized: model={self.model}, max_tool_rounds={self.max_tool_rounds}")
        logger.info(f"[LEANSTRAL_AGENT] Search provider: {self.search_provider.__class__.__name__}")
        logger.info(f"[LEANSTRAL_AGENT] Page crawler: {self.page_crawler.__class__.__name__}")
    
    async def research(
        self,
        entity_name: str,
        entity_type: Optional[str] = None,
        research_task: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> LeanstralResearchResult:
        """Perform research using Leanstral 1.5 with tool-driven loop.
        
        Args:
            entity_name: The entity to research
            entity_type: Optional entity type for context
            research_task: Optional specific research task/question
            context: Optional additional context
            
        Returns:
            LeanstralResearchResult with structured research output
        """
        result = LeanstralResearchResult(
            entity_name=entity_name,
            entity_type=entity_type,
            status=ResearchStatus.IN_PROGRESS,
        )
        
        if not self.api_key:
            result.status = ResearchStatus.FAILED
            result.error_message = "No Mistral API key configured"
            result.completed_at = datetime.now(timezone.utc)
            return result
        
        # Build the initial system prompt
        system_prompt = self._build_system_prompt(entity_name, entity_type, research_task)
        
        # Build the initial user message
        user_message = self._build_user_message(entity_name, entity_type, research_task, context)
        
        # Initialize conversation
        messages = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=user_message),
        ]
        
        # Tool loop
        tool_round = 0
        while tool_round < self.max_tool_rounds:
            result.tool_rounds = tool_round + 1
            
            # Check limits before next Leanstral call
            if result.search_calls >= self.max_search_calls:
                result.status = ResearchStatus.INCOMPLETE
                result.error_message = f"Max search calls reached: {result.search_calls}/{self.max_search_calls}"
                break
            
            if result.open_url_calls >= self.max_open_url_calls:
                result.status = ResearchStatus.INCOMPLETE
                result.error_message = f"Max open_url calls reached: {result.open_url_calls}/{self.max_open_url_calls}"
                break
            
            if result.total_retrieved_chars >= self.max_total_retrieved_chars:
                result.status = ResearchStatus.INCOMPLETE
                result.error_message = (
                    f"Retrieved character limit reached: "
                    f"{result.total_retrieved_chars}/{self.max_total_retrieved_chars}"
                )
                break
            
            # Call Leanstral
            response = await self._call_leanstral(messages)
            
            if response is None:
                result.status = ResearchStatus.FAILED
                result.error_message = "Leanstral API call failed"
                break
            
            # Parse response
            finish_reason = response.get("finish_reason", "")
            assistant_message = response.get("message", {})
            
            # Store the assistant message
            assistant_content = assistant_message.get("content", "")
            assistant_tool_calls = []
            
            if "tool_calls" in assistant_message:
                for tc in assistant_message["tool_calls"]:
                    if isinstance(tc, dict):
                        tool_call_id = tc.get("id", str(uuid.uuid4()))
                        function_name = tc.get("function", {}).get("name", "")
                        function_args = tc.get("function", {}).get("arguments", "{}")
                        
                        # Parse arguments
                        try:
                            args = json.loads(function_args) if isinstance(function_args, str) else function_args
                        except (TypeError, ValueError):
                            args = {}
                        
                        assistant_tool_calls.append(ToolCall(
                            id=tool_call_id,
                            name=function_name,
                            arguments=args,
                        ))
            
            # Add assistant message to conversation
            messages.append(Message(
                role="assistant",
                content=assistant_content,
                tool_calls=assistant_tool_calls,
            ))
            
            result.tool_calls_executed.extend(assistant_tool_calls)
            
            # Check if we need to execute tools
            if finish_reason == "tool_calls" and assistant_tool_calls:
                # Execute each tool call
                for tool_call in assistant_tool_calls:
                    # Check limits before each tool execution
                    if result.search_calls >= self.max_search_calls and tool_call.name == "search_web":
                        result.status = ResearchStatus.INCOMPLETE
                        result.error_message = f"Max search calls reached: {result.search_calls}/{self.max_search_calls}"
                        break
                    if result.open_url_calls >= self.max_open_url_calls and tool_call.name == "open_url":
                        result.status = ResearchStatus.INCOMPLETE
                        result.error_message = f"Max open_url calls reached: {result.open_url_calls}/{self.max_open_url_calls}"
                        break
                    if result.total_retrieved_chars >= self.max_total_retrieved_chars:
                        result.status = ResearchStatus.INCOMPLETE
                        result.error_message = (
                            f"Retrieved character limit reached: "
                            f"{result.total_retrieved_chars}/{self.max_total_retrieved_chars}"
                        )
                        break
                    
                    tool_result = await self._execute_tool(tool_call)
                    
                    if tool_result:
                        result.tool_results.append(tool_result)
                        
                        # Update counters based on tool type
                        if tool_call.name == "search_web":
                            result.search_calls += 1
                            if tool_result.ok:
                                result.successful_searches += 1
                            else:
                                result.failed_searches += 1
                        elif tool_call.name == "open_url":
                            result.open_url_calls += 1
                            if tool_result.ok:
                                result.successful_url_opens += 1
                            else:
                                result.failed_url_opens += 1
                        
                        # Update character count
                        if tool_result.ok and "content_length" in tool_result.metadata:
                            content_len = tool_result.metadata.get("content_length", 0)
                            result.total_retrieved_chars += content_len
                        
                        # Log tool result diagnostic before sending to Leanstral
                        chars_count = tool_result.metadata.get("content_length", 0) if tool_result.ok else 0
                        logger.info(f"[LEANSTRAL_AGENT] Tool result:\n"
                                   f"  tool={tool_call.name}\n"
                                   f"  tool_call_id={tool_call.id}\n"
                                   f"  ok={tool_result.ok}\n"
                                   f"  chars={chars_count}")
                        
                        # DIAGNOSTIC: Log TOOL_MESSAGE construction (Boundary C)
                        # tool_result.content is a JSON string - we need to check the actual content inside
                        tool_content_str = tool_result.content
                        tool_content_chars = len(tool_content_str)
                        tool_content_preview = tool_content_str[:500]
                        logger.info(f"[LEANSTRAL_AGENT] TOOL_MESSAGE\n"
                                   f"tool_call_id={tool_call.id}\n"
                                   f"content_chars={tool_content_chars}\n"
                                   f"content_preview={tool_content_preview}")
                        
                        # Add tool result message to conversation
                        messages.append(Message(
                            role="tool",
                            content=tool_result.content,
                            tool_call_id=tool_call.id,
                        ))
                        
                        # DIAGNOSTIC: Log FINAL_MESSAGES after adding tool message (Boundary D)
                        last_msg = messages[-1]
                        last_content = last_msg.content if last_msg.content else ""
                        last_content_chars = len(last_content)
                        last_content_preview = last_content[:500]
                        logger.info(f"[LEANSTRAL_AGENT] FINAL_MESSAGES\n"
                                   f"message_count={len(messages)}\n"
                                   f"last_role={last_msg.role}\n"
                                   f"last_tool_call_id={last_msg.tool_call_id}\n"
                                   f"last_content_chars={last_content_chars}\n"
                                   f"last_content_preview={last_content_preview}")
                        
                        # EXPLICIT ASSERTIONS: Verify tool message integrity before next Mistral call
                        if tool_call.name == "open_url":
                            try:
                                # tool_result.content is now plain text (readable content)
                                # Check the actual tool message that was added to the conversation
                                assert last_msg.role == "tool", f"Tool message role is {last_msg.role}, expected 'tool'"
                                assert last_msg.tool_call_id == tool_call.id, f"Tool call ID mismatch: {last_msg.tool_call_id} != {tool_call.id}"
                                assert last_msg.content is not None, f"Tool message content is None! tool_call_id={tool_call.id}"
                                assert len(last_msg.content.strip()) > 0, f"Tool message content is empty! tool_call_id={tool_call.id}, content='{last_msg.content}'"
                                logger.info(f"[LEANSTRAL_AGENT] ASSERTION_PASSED: tool message validated for {tool_call.id}")
                            except AssertionError as e:
                                logger.error(f"[LEANSTRAL_AGENT] ASSERTION_FAILED: {e}")
                                raise
                    else:
                        # Tool execution failed - add error message
                        logger.info(f"[LEANSTRAL_AGENT] Tool result:\n"
                                   f"  tool={tool_call.name}\n"
                                   f"  tool_call_id={tool_call.id}\n"
                                   f"  ok=false\n"
                                   f"  chars=0")
                        messages.append(Message(
                            role="tool",
                            content=f"Error: Tool execution failed for {tool_call.name}",
                            tool_call_id=tool_call.id,
                        ))
                
                # Check if we hit a limit during tool execution
                if result.status == ResearchStatus.INCOMPLETE:
                    break
                
                tool_round += 1
                continue
            
            # Check if we have a final answer
            if finish_reason == "stop":
                # Parse the final response
                await self._parse_final_response(result, assistant_content)
                result.status = ResearchStatus.COMPLETED
                break
            
            # Other finish reasons
            if finish_reason in ["length", "content_filter"]:
                result.status = ResearchStatus.INCOMPLETE
                result.error_message = f"Leanstral stopped: {finish_reason}"
                break
            
            # Unknown finish reason
            result.status = ResearchStatus.FAILED
            result.error_message = f"Unknown finish reason: {finish_reason}"
            break
        else:
            # Max tool rounds exceeded
            result.status = ResearchStatus.INCOMPLETE
            result.error_message = f"Max tool rounds ({self.max_tool_rounds}) exceeded"
        
        result.completed_at = datetime.now(timezone.utc)
        result.messages = messages
        
        logger.info(f"[LEANSTRAL_AGENT] Research completed: status={result.status.value}, "
                   f"rounds={result.tool_rounds}, "
                   f"searches={result.search_calls}(+{result.successful_searches}/-{result.failed_searches}), "
                   f"url_opens={result.open_url_calls}(+{result.successful_url_opens}/-{result.failed_url_opens}), "
                   f"chars={result.total_retrieved_chars}")
        
        return result
    
    def _build_system_prompt(
        self,
        entity_name: str,
        entity_type: Optional[str] = None,
        research_task: Optional[str] = None,
    ) -> str:
        """Build the system prompt for Leanstral."""
        return f"""You are a factual research agent for NORA (Node-Oriented Research Architecture).

## ROLE
Your job is to investigate entities and return ONLY grounded, verifiable evidence.
You must use the provided tools to discover and inspect sources.

## RULES
1. Never invent facts.
2. Never treat a search result URL itself as evidence.
3. Use search_web when source discovery is required.
4. Use open_url to inspect actual source content.
5. Prefer official sources for organizational facts.
6. Cross-check important claims when appropriate.
7. Distinguish source facts from inference.
8. Do not claim that a page was inspected unless open_url actually succeeded.
9. Do not fabricate URLs.
10. Do not fabricate source content.
11. Preserve source URLs with claims.
12. If evidence is insufficient, explicitly say so.
13. Prefer fewer high-quality sources over many weak sources.

## SOURCE PRIORITIZATION
- Prefer official organization domains (e.g., organization.org, organization.com)
- Prefer exact-entity matches in URLs
- Prefer source URLs whose domain matches the entity's known website
- If a likely official domain appears, inspect it before broadening search
- Do not repeatedly search when high-quality candidate URLs are already available
- For an organization, the official site should normally be the first source inspected

## SEARCH BEHAVIOR
- Never trust search result relevance - treat search as discovery only
- Search results are NOT authoritative ranking
- You must evaluate candidate URLs using open_url
- Never treat a URL returned from search as evidence until open_url successfully retrieves it
- If the entity metadata already contains a known official URL, use open_url directly

## TOOLS
You have access to two tools:

### search_web(query: str)
- Use to discover candidate URLs
- Returns URL discovery results only
- Search results are DISCOVERY, not evidence
- Limit: {self.max_search_calls} calls maximum

### open_url(url: str)
- Use to retrieve readable content from a specific URL
- Returns extracted text content (not raw HTML)
- Use this to obtain factual evidence
- Limit: {self.max_open_url_calls} calls maximum

## OUTPUT REQUIREMENTS
When you have completed your research, return a JSON object with this structure:

{{
  "entity": {{
    "name": "{entity_name}",
    "type": "{entity_type or 'unknown'}"
  }},
  "status": "SUFFICIENT|INSUFFICIENT|AMBIGUOUS",
  "sources": [
    {{
      "url": "https://example.org",
      "title": "...",
      "content_preview": "...",
      "evidence": [
        {{
          "claim": "...",
          "passage": "EXACT VERBATIM TEXT FROM SOURCE",
          "evidence_type": "FACT|ATTRIBUTE|RELATIONSHIP|ASSOCIATION|SUMMARY"
        }}
      ]
    }}
  ],
  "claims": [
    {{
      "claim": "...",
      "source_urls": ["https://example.org"],
      "evidence_type": "FACT|ATTRIBUTE|RELATIONSHIP|ASSOCIATION|SUMMARY"
    }}
  ],
  "uncertainties": [],
  "rejected_sources": []
}}

## IMPORTANT
- Every factual claim must have supporting evidence from an inspected source
- Every passage must be an EXACT quote from the source
- Do NOT paraphrase or synthesize passages
- Use the tools to verify information, not to guess
- If you cannot find evidence, state that explicitly
"""
    
    def _build_user_message(
        self,
        entity_name: str,
        entity_type: Optional[str] = None,
        research_task: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Build the user message for the research task."""
        task_description = research_task or (
            f"Research the entity '{entity_name}' and determine: "
            f"1) What the organization is, 2) Its key relationships, "
            f"3) Its stated purpose/focus, 4) Its current status, "
            f"5) Official contact information. "
            f"Use web discovery and inspect primary sources. "
            f"Every factual claim must have a source."
        )
        
        if entity_type:
            task_description += f"\n\nEntity type hint: {entity_type}"
        
        if context:
            task_description += f"\n\nAdditional context: {json.dumps(context, ensure_ascii=False)}"
        
        # Add known official URL if available in context
        known_url = None
        if context and isinstance(context, dict):
            known_url = context.get("known_url") or context.get("official_url") or context.get("website")
        
        if known_url:
            task_description += f"\n\nKnown candidate source:\n{known_url}"
        
        return task_description
    
    async def _call_leanstral(
        self,
        messages: List[Message],
    ) -> Optional[Dict[str, Any]]:
        """Call Leanstral API with the current conversation.
        
        Args:
            messages: List of messages in the conversation
            
        Returns:
            Parsed JSON response or None on failure
        """
        import httpx
        
        # Build tool definitions for the API
        tools = [
            {
                "type": "function",
                "function": {
                    "name": SEARCH_WEB_TOOL.name,
                    "description": SEARCH_WEB_TOOL.description,
                    "parameters": SEARCH_WEB_TOOL.parameters,
                }
            },
            {
                "type": "function",
                "function": {
                    "name": OPEN_URL_TOOL.name,
                    "description": OPEN_URL_TOOL.description,
                    "parameters": OPEN_URL_TOOL.parameters,
                }
            }
        ]
        
        # DIAGNOSTIC: Log FINAL_MESSAGES before Mistral API call
        message_count = len(messages)
        if messages:
            last_msg = messages[-1]
            last_content = last_msg.content if last_msg.content else ""
            last_content_chars = len(last_content)
            last_content_preview = last_content[:500] if last_content else ""
            last_tool_call_id = last_msg.tool_call_id if hasattr(last_msg, 'tool_call_id') else None
            logger.info(f"[LEANSTRAL_AGENT] FINAL_MESSAGES_BEFORE_API\n"
                       f"message_count={message_count}\n"
                       f"last_role={last_msg.role}\n"
                       f"last_tool_call_id={last_tool_call_id}\n"
                       f"last_content_chars={last_content_chars}\n"
                       f"last_content_preview={last_content_preview}")
        
        # DIAGNOSTIC: Serialize full messages array (truncated)
        try:
            import copy
            messages_for_log = []
            for m in messages:
                msg_dict = m.to_dict()
                if msg_dict.get("content"):
                    content = msg_dict["content"]
                    if isinstance(content, str) and len(content) > 500:
                        msg_dict = copy.deepcopy(msg_dict)
                        msg_dict["content"] = content[:500] + "...[TRUNCATED]"
                messages_for_log.append(msg_dict)
            logger.info(f"[LEANSTRAL_AGENT] MISTRAL_REQUEST_MESSAGES\n{json.dumps(messages_for_log, indent=2)}")
        except Exception as e:
            logger.warning(f"[LEANSTRAL_AGENT] Failed to serialize messages for diagnostic: {e}")
        
        payload = {
            "model": self.model,
            "messages": [m.to_dict() for m in messages],
            "tools": tools,
            "temperature": 0.0,
            "top_p": 1.0,
        }
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        try:
            async with httpx.AsyncClient(headers=headers, timeout=self.timeout) as client:
                response = await client.post(
                    "https://api.mistral.ai/v1/chat/completions",
                    json=payload,
                )
                response.raise_for_status()
                json_response = response.json()
                
                # Extract the first choice
                choices = json_response.get("choices") or []
                if not choices:
                    return None
                
                return choices[0]
        
        except Exception as e:
            logger.error(f"[LEANSTRAL_AGENT] API call failed: {type(e).__name__}: {e}")
            return None
    
    async def _execute_tool(
        self,
        tool_call: ToolCall,
    ) -> Optional[ToolResult]:
        """Execute a tool call and return the result.
        
        Args:
            tool_call: The tool call to execute
            
        Returns:
            ToolResult or None on failure
        """
        logger.info(f"[LEANSTRAL_AGENT] Executing tool: {tool_call.name} with args={tool_call.arguments}")
        
        try:
            if tool_call.name == "search_web":
                return await self._execute_search_web(tool_call)
            elif tool_call.name == "open_url":
                return await self._execute_open_url(tool_call)
            else:
                logger.error(f"[LEANSTRAL_AGENT] Unknown tool: {tool_call.name}")
                return ToolResult(
                    tool_call_id=tool_call.id,
                    content=f"Error: Unknown tool: {tool_call.name}",
                    ok=False,
                    error=f"Unknown tool: {tool_call.name}",
                )
        except Exception as e:
            logger.error(f"[LEANSTRAL_AGENT] Tool execution failed: {type(e).__name__}: {e}")
            return ToolResult(
                tool_call_id=tool_call.id,
                content=f"Error: {str(e)}",
                ok=False,
                error=str(e),
            )
    
    async def _execute_search_web(
        self,
        tool_call: ToolCall,
    ) -> ToolResult:
        """Execute the search_web tool.
        
        Args:
            tool_call: Tool call with query parameter
            
        Returns:
            ToolResult with search results
        """
        query = tool_call.arguments.get("query", "")
        
        if not query:
            return ToolResult(
                tool_call_id=tool_call.id,
                content=json.dumps({"ok": False, "error": "Query is required"}),
                ok=False,
                error="Query is required",
            )
        
        logger.info(f"[LEANSTRAL_AGENT] Searching web for: {query[:100]}")
        
        # Execute search using Apps Script provider
        try:
            results = await self.search_provider.search(
                query=query,
                max_results=10,
            )
            
            # Extract URLs from results
            urls = []
            for result in results:
                if isinstance(result, dict) and result.get("url"):
                    urls.append(result["url"])
                    logger.info(f"[LEANSTRAL_AGENT] Found URL: {result['url']}")
            
            # Store discovered URLs
            # Note: We'll update the result object later
            
            # Return readable search results
            readable_results = f"Search query: {query}\nFound {len(urls)} results:\n\n" + "\n".join(urls)
            
            return ToolResult(
                tool_call_id=tool_call.id,
                content=readable_results,
                ok=True,
                metadata={"query": query, "urls_found": len(urls)},
            )
        
        except Exception as e:
            logger.error(f"[LEANSTRAL_AGENT] Search failed: {type(e).__name__}: {e}")
            error_type = "search_timeout" if "timeout" in str(e).lower() or "gateway" in str(e).lower() else "search_error"
            readable_error = f"Search query: {query}\nError: {str(e)}"
            return ToolResult(
                tool_call_id=tool_call.id,
                content=readable_error,
                ok=False,
                error=str(e),
            )
    
    async def _execute_open_url(
        self,
        tool_call: ToolCall,
    ) -> ToolResult:
        """Execute the open_url tool.
        
        Args:
            tool_call: Tool call with url parameter
            
        Returns:
            ToolResult with retrieved content
        """
        url = tool_call.arguments.get("url", "")
        
        if not url:
            return ToolResult(
                tool_call_id=tool_call.id,
                content="Error: URL is required",
                ok=False,
                error="URL is required",
            )
        
        # DIAGNOSTIC: Log OPEN_URL_CALL
        logger.info(f"[LEANSTRAL_AGENT] OPEN_URL_CALL\n"
                   f"id={tool_call.id}\n"
                   f"name=open_url\n"
                   f"arguments={json.dumps(tool_call.arguments)}")
        
        logger.info(f"[LEANSTRAL_AGENT] Opening URL: {url}")
        
        # Execute retrieval using PageCrawler
        try:
            crawl_result = await self.page_crawler.crawl_url(url)
            
            # DIAGNOSTIC: Log PageCrawler result (Boundary A)
            crawler_content = crawl_result.content if crawl_result.content else ""
            crawler_chars = len(crawler_content)
            crawler_preview = crawler_content[:500] if crawler_content else ""
            logger.info(f"[LEANSTRAL_AGENT] PAGE_CRAWLER_RESULT\n"
                       f"  url={url}\n"
                       f"  final_url={crawl_result.final_url}\n"
                       f"  status_code={crawl_result.status_code}\n"
                       f"  success={crawl_result.success}\n"
                       f"  content_chars={crawler_chars}\n"
                       f"  content_preview={crawler_preview}")
            
            # Log detailed retrieval information
            raw_bytes = len(crawl_result.content) if crawl_result.content else 0
            extracted_chars = len(crawl_result.content) if crawl_result.content else 0
            logger.info(f"[LEANSTRAL_AGENT] open_url result:\n"
                       f"  requested_url={url}\n"
                       f"  final_url={crawl_result.final_url}\n"
                       f"  status_code={crawl_result.status_code}\n"
                       f"  content_type={crawl_result.content_type}\n"
                       f"  raw_bytes={raw_bytes}\n"
                       f"  extracted_chars={extracted_chars}")
            
            if crawl_result.success and crawl_result.content:
                # Return readable content
                content_length = len(crawl_result.content)
                logger.info(f"[LEANSTRAL_AGENT] Tool result:\n"
                           f"  tool=open_url\n"
                           f"  tool_call_id={tool_call.id}\n"
                           f"  ok=true\n"
                           f"  chars={content_length}")
                
                # Ensure all fields are JSON-serializable
                final_url = crawl_result.final_url if isinstance(crawl_result.final_url, str) else str(crawl_result.final_url)
                content_type = crawl_result.content_type if isinstance(crawl_result.content_type, str) else str(crawl_result.content_type)
                
                # DIAGNOSTIC: Log OPEN_URL_RETURN (Boundary B)
                # The content we return should be the readable text, not JSON
                logger.info(f"[LEANSTRAL_AGENT] OPEN_URL_RETURN\n"
                           f"id={tool_call.id}\n"
                           f"return_type=str\n"
                           f"content_chars={content_length}\n"
                           f"content_preview={crawl_result.content[:500]}")
                
                # CRITICAL FIX: Return the actual readable content text directly,
                # NOT wrapped in JSON. The Mistral API expects the tool message
                # content to be the actual text, matching the known-good protocol.
                # Format: "URL: <url>\nPage title: <title>\n\n<content>"
                readable_content = f"URL: {url}\nPage title: {crawl_result.title}\n\n{crawl_result.content}"
                
                return ToolResult(
                    tool_call_id=tool_call.id,
                    content=readable_content,
                    ok=True,
                    metadata={
                        "url": url,
                        "final_url": final_url,
                        "http_status": crawl_result.status_code,
                        "content_type": content_type,
                        "title": crawl_result.title,
                        "content_length": content_length,
                    },
                )
            else:
                # Extraction failed - return structured error
                error_type = "extraction_error" if crawl_result.success and not crawl_result.content else \
                           "http_error" if crawl_result.status_code >= 400 else \
                           "connection_error"
                error_msg = crawl_result.error or "Retrieval failed"
                if crawl_result.success and not crawl_result.content:
                    error_msg = "Extraction returned empty content"
                
                logger.warning(f"[LEANSTRAL_AGENT] open_url failed:\n"
                             f"  requested_url={url}\n"
                             f"  final_url={crawl_result.final_url}\n"
                             f"  status_code={crawl_result.status_code}\n"
                             f"  error_type={error_type}\n"
                             f"  error={error_msg}")
                
                # DIAGNOSTIC: Log OPEN_URL_RETURN for error case
                logger.info(f"[LEANSTRAL_AGENT] OPEN_URL_RETURN\n"
                           f"id={tool_call.id}\n"
                           f"return_type=str\n"
                           f"content_chars=0\n"
                           f"content_preview=Error: {error_msg}")
                
                logger.info(f"[LEANSTRAL_AGENT] Tool result:\n"
                           f"  tool=open_url\n"
                           f"  tool_call_id={tool_call.id}\n"
                           f"  ok=false\n"
                           f"  chars=0")
                
                # Ensure all fields are JSON-serializable
                final_url = crawl_result.final_url if isinstance(crawl_result.final_url, str) else str(crawl_result.final_url)
                content_type = crawl_result.content_type if isinstance(crawl_result.content_type, str) else str(crawl_result.content_type)
                
                # Return readable error message
                readable_error = f"URL: {url}\nError: {error_msg}"
                
                return ToolResult(
                    tool_call_id=tool_call.id,
                    content=readable_error,
                    ok=False,
                    error=error_msg,
                    metadata={
                        "url": url,
                        "final_url": final_url,
                        "http_status": crawl_result.status_code,
                        "content_type": content_type,
                        "error": error_msg,
                        "error_type": error_type,
                        "content_length": 0,
                    },
                )
        
        except Exception as e:
            logger.error(f"[LEANSTRAL_AGENT] URL retrieval failed: {type(e).__name__}: {e}")
            
            # DIAGNOSTIC: Log OPEN_URL_RETURN for exception case
            logger.info(f"[LEANSTRAL_AGENT] OPEN_URL_RETURN\n"
                       f"id={tool_call.id}\n"
                       f"return_type=str\n"
                       f"content_chars=0\n"
                       f"content_preview=Error: {str(e)}")
            
            logger.info(f"[LEANSTRAL_AGENT] Tool result:\n"
                       f"  tool=open_url\n"
                       f"  tool_call_id={tool_call.id}\n"
                       f"  ok=false\n"
                       f"  chars=0")
            
            # Return readable error message
            readable_error = f"URL: {url}\nError: {str(e)}"
            
            return ToolResult(
                tool_call_id=tool_call.id,
                content=readable_error,
                ok=False,
                error=str(e),
                metadata={
                    "url": url,
                    "error": str(e),
                    "error_type": "retrieval_error",
                    "content_length": 0,
                },
            )
    
    async def _parse_final_response(
        self,
        result: LeanstralResearchResult,
        assistant_content: str,
    ) -> None:
        """Parse the final response from Leanstral.
        
        Args:
            result: The research result to update
            assistant_content: The final content from Leanstral
        """
        try:
            # Try to parse as JSON
            parsed = json.loads(assistant_content)
            
            if isinstance(parsed, dict):
                # Extract entity info
                entity_info = parsed.get("entity", {})
                result.entity_name = entity_info.get("name", result.entity_name)
                result.entity_type = entity_info.get("type", result.entity_type)
                
                # Extract status
                status_str = parsed.get("status", "INSUFFICIENT").upper()
                if status_str == "SUFFICIENT":
                    result.status = ResearchStatus.COMPLETED
                elif status_str == "INSUFFICIENT":
                    result.status = ResearchStatus.INSUFFICIENT
                elif status_str == "AMBIGUOUS":
                    result.status = ResearchStatus.INSUFFICIENT
                
                # Extract sources
                sources = parsed.get("sources") or []
                for source in sources:
                    if isinstance(source, dict):
                        result.sources.append(source)
                        if source.get("url"):
                            result.urls_retrieved.append(source["url"])
                
                # Extract claims
                claims = parsed.get("claims") or []
                for claim in claims:
                    if isinstance(claim, dict):
                        result.claims.append(claim)
                
                # Extract uncertainties
                uncertainties = parsed.get("uncertainties") or []
                if uncertainties:
                    result.metadata["uncertainties"] = uncertainties
                
                # Extract rejected sources
                rejected = parsed.get("rejected_sources") or []
                if rejected:
                    result.metadata["rejected_sources"] = rejected
                
                # Extract evidence from sources
                for source in sources:
                    if isinstance(source, dict):
                        evidence_list = source.get("evidence") or []
                        for evidence in evidence_list:
                            if isinstance(evidence, dict):
                                passage = evidence.get("passage", "")
                                if passage:
                                    record = EvidenceRecord(
                                        url=source.get("url", ""),
                                        title=source.get("title", ""),
                                        snippet=passage[:500],
                                        content=passage,
                                        normalized_text=passage,
                                        source="leanstral_web_research",
                                        query=result.entity_name,
                                        entity_name=result.entity_name,
                                        entity_id=None,
                                        evidence_status=EvidenceStatus.USABLE,
                                        extraction_quality=ExtractionQuality.SUBSTANTIVE,
                                        retrieval_status=RetrievalStatus.SUCCESS,
                                        metadata={
                                            "research_method": "leanstral_tool_driven",
                                            "evidence_type": evidence.get("evidence_type", "FACT"),
                                        }
                                    )
                                    result.evidence.append(record)
            
        except (TypeError, ValueError) as e:
            logger.warning(f"[LEANSTRAL_AGENT] Failed to parse final response as JSON: {e}")
            # Store raw content as a fallback
            if not hasattr(result, 'metadata'):
                result.metadata = {}
            result.metadata["raw_response"] = assistant_content
