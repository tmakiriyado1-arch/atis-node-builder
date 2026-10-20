"""Comprehensive diagnostic logging for NORA pipeline observability.

This module provides structured, stage-by-stage diagnostic logging with:
- Correlation ID generation and propagation
- Stage-level input/output accounting
- Stable identifiers for URLs, pages, chunks, evidence items, and claims
- Diagnostic configuration via environment variables
- Safe secret redaction

Usage:
    from app.services.diagnostic_logging import (
        get_diagnostic_logger,
        generate_run_id,
        DiagnosticContext,
        diagnostic_config,
    )

    # Get logger with correlation ID
    logger = get_diagnostic_logger(run_id="abc123")
    logger.info("Stage A: API request received", extra={"stage": "A", "status": "started"})

    # Or use context manager
    with DiagnosticContext(run_id="abc123", entity_name="ZERA") as ctx:
        ctx.log_stage_start("A", "API request and run initialization")
        # ... do work ...
        ctx.log_stage_end("A", "API request and run initialization", success=True)
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple, Union


# =============================================================================
# Configuration
# =============================================================================

class DiagnosticConfig:
    """Configuration for diagnostic logging."""
    
    def __init__(self):
        # Enable/disable diagnostics (default: enabled via env var)
        self.enabled = os.environ.get("NORA_DIAGNOSTICS_ENABLED", "true").lower() in ("true", "1", "yes")
        
        # Enable verbose mode (logs full content previews, more detail)
        self.verbose = os.environ.get("NORA_DIAGNOSTICS_VERBOSE", "false").lower() in ("true", "1", "yes")
        
        # Maximum characters for content previews in logs
        self.preview_chars = int(os.environ.get("NORA_DIAGNOSTICS_PREVIEW_CHARS", "500"))
        
        # Enable JSON structured logging
        self.json_logging = os.environ.get("NORA_DIAGNOSTICS_JSON", "false").lower() in ("true", "1", "yes")
        
        # Log level override (default: INFO)
        self.log_level = os.environ.get("NORA_DIAGNOSTICS_LOG_LEVEL", "INFO").upper()
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize configuration to dictionary."""
        return {
            "enabled": self.enabled,
            "verbose": self.verbose,
            "preview_chars": self.preview_chars,
            "json_logging": self.json_logging,
            "log_level": self.log_level,
        }


# Global configuration instance
diagnostic_config = DiagnosticConfig()


# =============================================================================
# Stage Enumeration
# =============================================================================

class PipelineStage(str, Enum):
    """Pipeline stages for diagnostic logging."""
    A = "A"  # API request and run initialization
    B = "B"  # Search execution
    C = "C"  # Raw URL collection
    D = "D"  # URL quality filtering
    E = "E"  # Page fetching and HTTP retrieval
    F = "F"  # Text extraction and content preparation
    G = "G"  # LLM request preparation
    H = "H"  # LLM request and response
    I = "I"  # LLM response parsing and normalization
    J = "J"  # Evidence creation and persistence
    K = "K"  # Semantic extraction and claim generation
    L = "L"  # Run completion and final summary


# Stage names for logging
STAGE_NAMES = {
    PipelineStage.A: "API request and run initialization",
    PipelineStage.B: "Search execution",
    PipelineStage.C: "Raw URL collection",
    PipelineStage.D: "URL quality filtering",
    PipelineStage.E: "Page fetching and HTTP retrieval",
    PipelineStage.F: "Text extraction and content preparation",
    PipelineStage.G: "LLM request preparation",
    PipelineStage.H: "LLM request and response",
    PipelineStage.I: "LLM response parsing and normalization",
    PipelineStage.J: "Evidence creation and persistence",
    PipelineStage.K: "Semantic extraction and claim generation",
    PipelineStage.L: "Run completion and final summary",
}


# =============================================================================
# Status Types
# =============================================================================

class StageStatus(str, Enum):
    """Status types for pipeline stages."""
    STARTED = "started"
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    SKIPPED = "skipped"
    FAILED = "failed"


class FailureCategory(str, Enum):
    """Categories for failure classification."""
    # Network/HTTP failures
    CONNECTION_ERROR = "connection_error"
    TIMEOUT = "timeout"
    HTTP_ERROR = "http_error"
    DNS_ERROR = "dns_error"
    SSL_ERROR = "ssl_error"
    
    # Provider failures
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_TIMEOUT = "provider_timeout"
    PROVIDER_ERROR = "provider_error"
    RATE_LIMITED = "rate_limited"
    AUTHENTICATION_ERROR = "authentication_error"
    
    # Content failures
    EMPTY_CONTENT = "empty_content"
    BLOCK_PAGE = "block_page"
    CAPTCHA = "captcha"
    LOGIN_REQUIRED = "login_required"
    ERROR_PAGE = "error_page"
    IRRELEVANT_CONTENT = "irrelevant_content"
    
    # Processing failures
    PARSING_ERROR = "parsing_error"
    NORMALIZATION_ERROR = "normalization_error"
    VALIDATION_ERROR = "validation_error"
    SCHEMA_MISMATCH = "schema_mismatch"
    
    # LLM-specific failures
    LLM_TIMEOUT = "llm_timeout"
    LLM_RATE_LIMIT = "llm_rate_limit"
    LLM_NORMALIZATION_FAILED = "llm_normalization_failed"
    LLM_EMPTY_RESPONSE = "llm_empty_response"
    LLM_MALFORMED_RESPONSE = "llm_malformed_response"
    LLM_REFUSAL = "llm_refusal"
    
    # Pipeline failures
    NO_INPUT = "no_input"
    NO_EVIDENCE = "no_evidence"
    NO_CLAIMS = "no_claims"
    DEDUPLICATION_ERROR = "deduplication_error"
    UNKNOWN_ERROR = "unknown_error"


# =============================================================================
# Redaction Utilities
# =============================================================================

def _redact_secrets(value: str) -> str:
    """Redact secrets from a string value.
    
    This function redacts API keys, tokens, passwords, and other sensitive
    values that might appear in logs.
    
    Args:
        value: The string to redact
        
    Returns:
        The string with secrets redacted
    """
    if not isinstance(value, str):
        return str(value)
    
    # Patterns for sensitive data
    secret_patterns = [
        # API keys (Bearer tokens, etc.)
        (r'(?i)(bearer\s+)[a-zA-Z0-9\-_]+', r'\1[REDACTED]'),
        (r'(?i)(authorization:\s*)[a-zA-Z0-9\-_.]+', r'\1[REDACTED]'),
        (r'(?i)(api[_-]?key\s*[:=]\s*)[a-zA-Z0-9\-_]+', r'\1[REDACTED]'),
        (r'(?i)(token\s*[:=]\s*)[a-zA-Z0-9\-_.]+', r'\1[REDACTED]'),
        (r'(?i)(password\s*[:=]\s*)[^\s\n]+', r'\1[REDACTED]'),
        (r'(?i)(secret\s*[:=]\s*)[^\s\n]+', r'\1[REDACTED]'),
        (r'(?i)(private[_-]?key\s*[:=]\s*)[^\s\n]+', r'\1[REDACTED]'),
        # Mistral API key pattern (sk- prefix) - any length
        (r'(sk-[a-zA-Z0-9\-_]+)', '[REDACTED]'),
        # Generic long alphanumeric strings that look like secrets
        (r'([A-Za-z0-9+/=]{40,})', '[REDACTED_LONG]'),
    ]
    
    result = value
    for pattern, replacement in secret_patterns:
        result = re.sub(pattern, replacement, result)
    
    return result


def redact_dict(data: Dict[str, Any], max_depth: int = 3) -> Dict[str, Any]:
    """Recursively redact secrets from a dictionary.
    
    Args:
        data: The dictionary to redact
        max_depth: Maximum recursion depth
        
    Returns:
        A new dictionary with secrets redacted
    """
    if max_depth <= 0:
        return data
    
    result = {}
    for key, value in data.items():
        # Redact known secret keys
        key_lower = key.lower()
        if any(secret in key_lower for secret in ['api_key', 'token', 'password', 'secret', 'authorization', 'credential']):
            result[key] = '[REDACTED]'
        elif isinstance(value, dict):
            result[key] = redact_dict(value, max_depth - 1)
        elif isinstance(value, list):
            result[key] = [_redact_secrets(v) if isinstance(v, str) else v for v in value]
        elif isinstance(value, str):
            # Also check if the string value looks like a secret
            if 'secret' in value.lower() or 'key_' in value.lower() or 'token_' in value.lower():
                result[key] = '[REDACTED]'
            else:
                result[key] = _redact_secrets(value)
        else:
            result[key] = value
    
    return result


def redact_url(url: str) -> str:
    """Redact sensitive parts from a URL.
    
    Args:
        url: The URL to redact
        
    Returns:
        The URL with query parameters and fragments that might contain
        secrets redacted
    """
    if not isinstance(url, str):
        return str(url)
    
    from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
    
    try:
        parsed = urlparse(url)
        
        # Redact query parameters that might contain secrets
        if parsed.query:
            query_params = parse_qs(parsed.query, keep_blank_values=True)
            redacted_params = {}
            secret_keys = {'api_key', 'token', 'password', 'secret', 'key', 'access_token'}
            
            for key, values in query_params.items():
                if key.lower() in secret_keys:
                    redacted_params[key] = ['[REDACTED]']
                else:
                    redacted_params[key] = [_redact_secrets(v) for v in values]
            
            parsed = parsed._replace(query=urlencode(redacted_params, doseq=True))
        
        # Redact fragment if it contains secrets
        if parsed.fragment:
            parsed = parsed._replace(fragment='[REDACTED_FRAGMENT]')
        
        return urlunparse(parsed)
    except Exception:
        # If URL parsing fails, just redact the whole thing if it looks sensitive
        return _redact_secrets(url)


# =============================================================================
# Correlation ID and Context Management
# =============================================================================

# Thread-local storage for current diagnostic context
_thread_local = threading.local()


def generate_run_id() -> str:
    """Generate a unique run ID for pipeline execution.
    
    Returns:
        A unique identifier string
    """
    return str(uuid.uuid4())


def get_current_run_id() -> Optional[str]:
    """Get the current run ID from thread-local storage.
    
    Returns:
        The current run ID, or None if not set
    """
    return getattr(_thread_local, 'run_id', None)


def set_current_run_id(run_id: str) -> None:
    """Set the current run ID in thread-local storage.
    
    Args:
        run_id: The run ID to set
    """
    _thread_local.run_id = run_id


@dataclass
class DiagnosticContext:
    """Context for diagnostic logging within a pipeline execution.
    
    This class manages the diagnostic context for a single pipeline run,
    including correlation ID, entity information, and stage accounting.
    
    Attributes:
        run_id: Unique identifier for this pipeline execution
        entity_name: Name of the entity being researched
        parent_run_id: Parent run ID if this is a nested execution
        start_time: When the pipeline started
        stages: Map of stage IDs to their accounting data
        counters: Global counters for the pipeline
        warnings: List of warning messages
        errors: List of error messages
    """
    
    run_id: str
    entity_name: str = ""
    parent_run_id: Optional[str] = None
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Stage accounting
    stages: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    
    # Global counters
    counters: Dict[str, int] = field(default_factory=dict)
    
    # Warning and error tracking
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    
    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Initialize stage accounting for all pipeline stages."""
        for stage in PipelineStage:
            self.stages[stage.value] = {
                "name": STAGE_NAMES.get(stage, stage.value),
                "start_time": None,
                "end_time": None,
                "status": None,
                "input_count": 0,
                "output_count": 0,
                "errors": [],
                "warnings": [],
                "duration_ms": 0,
            }
        
        # Initialize common counters
        self.counters["search_results_received"] = 0
        self.counters["urls_extracted"] = 0
        self.counters["urls_unique"] = 0
        self.counters["urls_accepted"] = 0
        self.counters["urls_rejected"] = 0
        self.counters["pages_fetch_succeeded"] = 0
        self.counters["pages_fetch_failed"] = 0
        self.counters["pages_usable_text"] = 0
        self.counters["llm_calls_attempted"] = 0
        self.counters["llm_calls_succeeded"] = 0
        self.counters["llm_calls_failed"] = 0
        self.counters["evidence_items_generated"] = 0
        self.counters["evidence_items_validated"] = 0
        self.counters["evidence_items_persisted"] = 0
        self.counters["claims_candidates"] = 0
        self.counters["claims_rejected"] = 0
        self.counters["claims_persisted"] = 0
    
    def log_stage_start(self, stage: Union[PipelineStage, str], stage_name: Optional[str] = None) -> None:
        """Log the start of a pipeline stage.
        
        Args:
            stage: The pipeline stage
            stage_name: Optional custom name for the stage
        """
        stage_id = stage.value if isinstance(stage, PipelineStage) else stage
        
        if stage_id not in self.stages:
            self.stages[stage_id] = {
                "name": stage_name or stage_id,
                "start_time": None,
                "end_time": None,
                "status": None,
                "input_count": 0,
                "output_count": 0,
                "errors": [],
                "warnings": [],
                "duration_ms": 0,
            }
        
        self.stages[stage_id]["start_time"] = datetime.now(timezone.utc)
        self.stages[stage_id]["status"] = StageStatus.STARTED.value
        
        logger = get_diagnostic_logger(self.run_id)
        logger.info(
            f"[{self.run_id}] STAGE {stage_id} STARTED: {stage_name or STAGE_NAMES.get(PipelineStage(stage_id), stage_id)}"
        )
    
    def log_stage_end(
        self,
        stage: Union[PipelineStage, str],
        stage_name: Optional[str] = None,
        status: StageStatus = StageStatus.SUCCESS,
        input_count: int = 0,
        output_count: int = 0,
        error: Optional[str] = None,
        warning: Optional[str] = None,
    ) -> None:
        """Log the end of a pipeline stage.
        
        Args:
            stage: The pipeline stage
            stage_name: Optional custom name for the stage
            status: The completion status
            input_count: Number of items input to this stage
            output_count: Number of items output from this stage
            error: Optional error message
            warning: Optional warning message
        """
        stage_id = stage.value if isinstance(stage, PipelineStage) else stage
        
        if stage_id not in self.stages:
            self.stages[stage_id] = {
                "name": stage_name or stage_id,
                "start_time": None,
                "end_time": None,
                "status": None,
                "input_count": 0,
                "output_count": 0,
                "errors": [],
                "warnings": [],
                "duration_ms": 0,
            }
        
        end_time = datetime.now(timezone.utc)
        start_time = self.stages[stage_id]["start_time"]
        
        if start_time:
            duration = (end_time - start_time).total_seconds() * 1000
            self.stages[stage_id]["duration_ms"] = duration
        
        self.stages[stage_id]["end_time"] = end_time
        self.stages[stage_id]["status"] = status.value
        self.stages[stage_id]["input_count"] = input_count
        self.stages[stage_id]["output_count"] = output_count
        
        if error:
            self.stages[stage_id]["errors"].append(error)
            self.errors.append(f"[{stage_id}] {error}")
        
        if warning:
            self.stages[stage_id]["warnings"].append(warning)
            self.warnings.append(f"[{stage_id}] {warning}")
        
        # Log accounting info
        if input_count > 0 or output_count > 0:
            reduction = input_count - output_count
            if reduction > 0:
                logger = get_diagnostic_logger(self.run_id)
                logger.info(
                    f"[{self.run_id}] STAGE {stage_id} ACCOUNTING: input={input_count} output={output_count} reduction={reduction}"
                )
        
        logger = get_diagnostic_logger(self.run_id)
        logger.info(
            f"[{self.run_id}] STAGE {stage_id} ENDED: status={status.value} duration_ms={self.stages[stage_id]['duration_ms']:.1f}"
        )
    
    def increment_counter(self, counter_name: str, amount: int = 1) -> None:
        """Increment a counter.
        
        Args:
            counter_name: Name of the counter
            amount: Amount to increment (default: 1)
        """
        self.counters[counter_name] = self.counters.get(counter_name, 0) + amount
    
    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of the diagnostic context.
        
        Returns:
            Dictionary containing the complete diagnostic summary
        """
        end_time = datetime.now(timezone.utc)
        duration = (end_time - self.start_time).total_seconds() * 1000
        
        # Calculate stage durations
        stage_summaries = {}
        for stage_id, stage_data in self.stages.items():
            stage_summaries[stage_id] = {
                "name": stage_data["name"],
                "status": stage_data["status"],
                "input_count": stage_data["input_count"],
                "output_count": stage_data["output_count"],
                "duration_ms": stage_data["duration_ms"],
                "errors": stage_data["errors"],
                "warnings": stage_data["warnings"],
            }
        
        # Identify first failing stage
        first_failing_stage = None
        for stage_id, stage_data in self.stages.items():
            if stage_data["status"] == StageStatus.FAILED.value:
                first_failing_stage = stage_id
                break
        
        # Identify failure stage from counters
        failure_stage = None
        primary_failure_reason = None
        
        # Check for zero evidence scenarios
        if self.counters.get("evidence_items_generated", 0) == 0:
            if self.counters.get("llm_calls_succeeded", 0) > 0:
                failure_stage = "K"
                primary_failure_reason = "LLM succeeded but extracted zero atomic evidence"
            elif self.counters.get("llm_calls_failed", 0) > 0:
                failure_stage = "H"
                primary_failure_reason = "LLM calls failed"
            elif self.counters.get("llm_calls_attempted", 0) == 0:
                failure_stage = "G"
                primary_failure_reason = "LLM not called"
            elif self.counters.get("pages_usable_text", 0) == 0:
                failure_stage = "F"
                primary_failure_reason = "No usable text extracted from pages"
            elif self.counters.get("pages_fetch_succeeded", 0) == 0:
                failure_stage = "E"
                primary_failure_reason = "No pages fetched successfully"
            elif self.counters.get("urls_accepted", 0) == 0:
                failure_stage = "D"
                primary_failure_reason = "No URLs accepted after filtering"
            elif self.counters.get("urls_unique", 0) == 0:
                failure_stage = "C"
                primary_failure_reason = "No unique URLs after deduplication"
            elif self.counters.get("urls_extracted", 0) == 0:
                failure_stage = "B"
                primary_failure_reason = "No URLs extracted from search results"
            elif self.counters.get("search_results_received", 0) == 0:
                failure_stage = "B"
                primary_failure_reason = "No search results received"
        
        # Check for zero claims
        if self.counters.get("claims_persisted", 0) == 0 and self.counters.get("claims_candidates", 0) == 0:
            if self.counters.get("evidence_items_generated", 0) == 0:
                # Already handled above
                pass
            elif self.counters.get("evidence_items_validated", 0) == 0:
                failure_stage = "J"
                primary_failure_reason = "Evidence validation failed"
            else:
                failure_stage = "K"
                primary_failure_reason = "No claims generated from evidence"
        
        return {
            "run_id": self.run_id,
            "entity_name": self.entity_name,
            "parent_run_id": self.parent_run_id,
            "start_time": self.start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "duration_ms": duration,
            "stages": stage_summaries,
            "counters": self.counters,
            "warnings": self.warnings,
            "errors": self.errors,
            "first_failing_stage": first_failing_stage,
            "failure_stage": failure_stage,
            "primary_failure_reason": primary_failure_reason,
            "metadata": self.metadata,
        }
    
    def add_warning(self, message: str) -> None:
        """Add a warning message.
        
        Args:
            message: The warning message
        """
        self.warnings.append(message)
    
    def add_error(self, message: str) -> None:
        """Add an error message.
        
        Args:
            message: The error message
        """
        self.errors.append(message)


@contextmanager
def diagnostic_context(
    run_id: Optional[str] = None,
    entity_name: str = "",
    parent_run_id: Optional[str] = None,
):
    """Context manager for diagnostic context.
    
    Args:
        run_id: Unique run ID (generated if not provided)
        entity_name: Name of the entity being researched
        parent_run_id: Parent run ID if nested
        
    Yields:
        DiagnosticContext instance
    """
    actual_run_id = run_id or generate_run_id()
    ctx = DiagnosticContext(
        run_id=actual_run_id,
        entity_name=entity_name,
        parent_run_id=parent_run_id,
    )
    
    # Set thread-local run ID
    old_run_id = get_current_run_id()
    set_current_run_id(actual_run_id)
    
    try:
        yield ctx
    finally:
        # Restore previous run ID
        if old_run_id:
            set_current_run_id(old_run_id)
        else:
            _thread_local.run_id = None


# =============================================================================
# Logger Factory
# =============================================================================

# Module-level logger
_logger = logging.getLogger("atis_node_builder.diagnostics")


def get_diagnostic_logger(
    run_id: Optional[str] = None,
    name: Optional[str] = None,
) -> logging.Logger:
    """Get a diagnostic logger with correlation ID support.
    
    Args:
        run_id: Run ID to include in log records
        name: Optional logger name (defaults to module logger)
        
    Returns:
        A logger instance configured for diagnostic logging
    """
    logger_name = name or "atis_node_builder.diagnostics"
    logger = logging.getLogger(logger_name)
    
    # Add run_id to logger if provided
    if run_id:
        # Create a wrapper that adds run_id to all log messages
        class RunIdLogger:
            def __init__(self, logger: logging.Logger, run_id: str):
                self._logger = logger
                self._run_id = run_id
            
            def debug(self, msg: str, *args, **kwargs):
                self._logger.debug(f"[{self._run_id}] {msg}", *args, **kwargs)
            
            def info(self, msg: str, *args, **kwargs):
                self._logger.info(f"[{self._run_id}] {msg}", *args, **kwargs)
            
            def warning(self, msg: str, *args, **kwargs):
                self._logger.warning(f"[{self._run_id}] {msg}", *args, **kwargs)
            
            def error(self, msg: str, *args, **kwargs):
                self._logger.error(f"[{self._run_id}] {msg}", *args, **kwargs)
            
            def critical(self, msg: str, *args, **kwargs):
                self._logger.critical(f"[{self._run_id}] {msg}", *args, **kwargs)
            
            def exception(self, msg: str, *args, **kwargs):
                self._logger.exception(f"[{self._run_id}] {msg}", *args, **kwargs)
            
            def log(self, level: int, msg: str, *args, **kwargs):
                self._logger.log(level, f"[{self._run_id}] {msg}", *args, **kwargs)
            
            @property
            def name(self):
                return self._logger.name
            
            @property
            def level(self):
                return self._logger.level
            
            @level.setter
            def level(self, value):
                self._logger.level = value
            
            def addHandler(self, hdlr):
                self._logger.addHandler(hdlr)
            
            def removeHandler(self, hdlr):
                self._logger.removeHandler(hdlr)
            
            def hasHandlers(self):
                return self._logger.hasHandlers()
            
            def setLevel(self, level):
                self._logger.setLevel(level)
        
        return RunIdLogger(logger, run_id)
    
    return logger


def log_with_redaction(
    logger: logging.Logger,
    level: int,
    msg: str,
    data: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> None:
    """Log a message with automatic secret redaction.
    
    Args:
        logger: The logger to use
        level: Log level
        msg: The message to log
        data: Optional dictionary data to include (will be redacted)
        **kwargs: Additional keyword arguments
    """
    if data:
        # Redact secrets from data
        redacted_data = redact_dict(data)
        msg = f"{msg} {json.dumps(redacted_data, default=str)}"
    
    logger.log(level, msg, **kwargs)


# =============================================================================
# Stage-Specific Logging Helpers
# =============================================================================

def log_stage_a(
    run_id: str,
    endpoint: str,
    operation: str,
    query: Optional[str] = None,
    status: StageStatus = StageStatus.STARTED,
    error: Optional[str] = None,
    **kwargs,
) -> None:
    """Log Stage A: API request and run initialization."""
    logger = get_diagnostic_logger(run_id)
    safe_query = _redact_secrets(query or "")
    
    if status == StageStatus.STARTED:
        logger.info(f"[STAGE A] {operation}: endpoint={endpoint} query={safe_query[:100]}")
    elif status == StageStatus.SUCCESS:
        logger.info(f"[STAGE A] {operation}: SUCCESS - run initialized")
    else:
        logger.error(f"[STAGE A] {operation}: FAILED - {error}")


def log_stage_b(
    run_id: str,
    provider: str,
    query: str,
    status: StageStatus = StageStatus.STARTED,
    result_count: int = 0,
    error: Optional[str] = None,
    retry_count: int = 0,
    **kwargs,
) -> None:
    """Log Stage B: Search execution."""
    logger = get_diagnostic_logger(run_id)
    safe_query = _redact_secrets(query)
    
    if status == StageStatus.STARTED:
        logger.info(f"[STAGE B] Search: provider={provider} query={safe_query[:100]}")
    elif status == StageStatus.SUCCESS:
        logger.info(f"[STAGE B] Search: provider={provider} results={result_count} retries={retry_count}")
    else:
        logger.error(f"[STAGE B] Search: provider={provider} FAILED - {error}")


def log_stage_c(
    run_id: str,
    raw_count: int,
    unique_count: int,
    duplicate_count: int,
    **kwargs,
) -> None:
    """Log Stage C: Raw URL collection and deduplication."""
    logger = get_diagnostic_logger(run_id)
    reduction = raw_count - unique_count
    logger.info(
        f"[STAGE C] URL Collection: raw={raw_count} unique={unique_count} "
        f"duplicates={duplicate_count} reduction={reduction}"
    )


def log_stage_d(
    run_id: str,
    filter_name: str,
    accepted: int,
    rejected: int,
    input_count: int,
    reason: Optional[str] = None,
    **kwargs,
) -> None:
    """Log Stage D: URL quality filtering."""
    logger = get_diagnostic_logger(run_id)
    
    if reason:
        logger.info(
            f"[STAGE D] Filter: {filter_name} input={input_count} "
            f"accepted={accepted} rejected={rejected} reason={reason}"
        )
    else:
        logger.info(
            f"[STAGE D] Filter: {filter_name} input={input_count} "
            f"accepted={accepted} rejected={rejected}"
        )


def log_stage_e(
    run_id: str,
    url: str,
    status: StageStatus = StageStatus.STARTED,
    http_status: Optional[int] = None,
    content_type: Optional[str] = None,
    size: int = 0,
    error: Optional[str] = None,
    **kwargs,
) -> None:
    """Log Stage E: Page fetching and HTTP retrieval."""
    logger = get_diagnostic_logger(run_id)
    safe_url = redact_url(url)
    
    if status == StageStatus.STARTED:
        logger.info(f"[STAGE E] Fetch: url={safe_url[:80]}")
    elif status == StageStatus.SUCCESS:
        logger.info(
            f"[STAGE E] Fetch: url={safe_url[:80]} status={http_status} "
            f"content_type={content_type} size={size}"
        )
    else:
        logger.error(f"[STAGE E] Fetch: url={safe_url[:80]} FAILED - {error}")


def log_stage_f(
    run_id: str,
    url: str,
    status: StageStatus = StageStatus.STARTED,
    text_length: int = 0,
    is_empty: bool = False,
    error: Optional[str] = None,
    **kwargs,
) -> None:
    """Log Stage F: Text extraction and content preparation."""
    logger = get_diagnostic_logger(run_id)
    safe_url = redact_url(url)
    
    if status == StageStatus.STARTED:
        logger.info(f"[STAGE F] Extraction: url={safe_url[:80]}")
    elif status == StageStatus.SUCCESS:
        logger.info(
            f"[STAGE F] Extraction: url={safe_url[:80]} "
            f"text_length={text_length} empty={is_empty}"
        )
    else:
        logger.error(f"[STAGE F] Extraction: url={safe_url[:80]} FAILED - {error}")


def log_stage_g(
    run_id: str,
    status: StageStatus = StageStatus.STARTED,
    model: Optional[str] = None,
    prompt_length: int = 0,
    evidence_count: int = 0,
    error: Optional[str] = None,
    **kwargs,
) -> None:
    """Log Stage G: LLM request preparation."""
    logger = get_diagnostic_logger(run_id)
    
    if status == StageStatus.STARTED:
        logger.info(f"[STAGE G] LLM Prep: model={model} evidence_count={evidence_count}")
    elif status == StageStatus.SUCCESS:
        logger.info(
            f"[STAGE G] LLM Prep: model={model} prompt_length={prompt_length} "
            f"evidence_count={evidence_count}"
        )
    else:
        logger.error(f"[STAGE G] LLM Prep: FAILED - {error}")


def log_stage_h(
    run_id: str,
    status: StageStatus = StageStatus.STARTED,
    model: Optional[str] = None,
    duration: float = 0,
    http_status: Optional[int] = None,
    tokens_input: int = 0,
    tokens_output: int = 0,
    error: Optional[str] = None,
    retry_count: int = 0,
    **kwargs,
) -> None:
    """Log Stage H: LLM request and response."""
    logger = get_diagnostic_logger(run_id)
    
    if status == StageStatus.STARTED:
        logger.info(f"[STAGE H] LLM Call: model={model}")
    elif status == StageStatus.SUCCESS:
        logger.info(
            f"[STAGE H] LLM Call: model={model} duration_ms={duration:.1f} "
            f"http_status={http_status} tokens_in={tokens_input} tokens_out={tokens_output} "
            f"retries={retry_count}"
        )
    else:
        logger.error(f"[STAGE H] LLM Call: model={model} FAILED - {error}")


def log_stage_i(
    run_id: str,
    status: StageStatus = StageStatus.STARTED,
    parsed_items: int = 0,
    invalid_items: int = 0,
    error: Optional[str] = None,
    **kwargs,
) -> None:
    """Log Stage I: LLM response parsing and normalization."""
    logger = get_diagnostic_logger(run_id)
    
    if status == StageStatus.STARTED:
        logger.info(f"[STAGE I] Parsing: started")
    elif status == StageStatus.SUCCESS:
        logger.info(
            f"[STAGE I] Parsing: parsed={parsed_items} invalid={invalid_items}"
        )
    else:
        logger.error(f"[STAGE I] Parsing: FAILED - {error}")


def log_stage_j(
    run_id: str,
    status: StageStatus = StageStatus.STARTED,
    generated: int = 0,
    validated: int = 0,
    persisted: int = 0,
    error: Optional[str] = None,
    **kwargs,
) -> None:
    """Log Stage J: Evidence creation and persistence."""
    logger = get_diagnostic_logger(run_id)
    
    if status == StageStatus.STARTED:
        logger.info(f"[STAGE J] Evidence: started")
    elif status == StageStatus.SUCCESS:
        logger.info(
            f"[STAGE J] Evidence: generated={generated} validated={validated} "
            f"persisted={persisted}"
        )
    else:
        logger.error(f"[STAGE J] Evidence: FAILED - {error}")


def log_stage_k(
    run_id: str,
    status: StageStatus = StageStatus.STARTED,
    evidence_count: int = 0,
    claim_count: int = 0,
    rejected_count: int = 0,
    error: Optional[str] = None,
    **kwargs,
) -> None:
    """Log Stage K: Semantic extraction and claim generation."""
    logger = get_diagnostic_logger(run_id)
    
    if status == StageStatus.STARTED:
        logger.info(f"[STAGE K] Extraction: started with {evidence_count} evidence items")
    elif status == StageStatus.SUCCESS:
        logger.info(
            f"[STAGE K] Extraction: evidence={evidence_count} "
            f"claims={claim_count} rejected={rejected_count}"
        )
    else:
        logger.error(f"[STAGE K] Extraction: FAILED - {error}")


def log_stage_l(
    run_id: str,
    summary: Dict[str, Any],
) -> None:
    """Log Stage L: Run completion and final summary."""
    logger = get_diagnostic_logger(run_id)
    
    # Format summary for logging
    summary_str = json.dumps(summary, default=str, indent=2)
    
    # Split into chunks to avoid extremely long log lines
    max_chunk_size = 1000
    for i in range(0, len(summary_str), max_chunk_size):
        chunk = summary_str[i:i + max_chunk_size]
        if i == 0:
            logger.info(f"[STAGE L] RUN SUMMARY: {chunk}")
        else:
            logger.info(f"[STAGE L] RUN SUMMARY (cont): {chunk}")


# =============================================================================
# Accounting Utilities
# =============================================================================

class StageAccounting:
    """Utility for tracking input/output counts through pipeline stages."""
    
    def __init__(self):
        self.stages = {}
    
    def record(self, stage: str, input_count: int, output_count: int) -> None:
        """Record counts for a stage.
        
        Args:
            stage: Stage identifier
            input_count: Number of items input
            output_count: Number of items output
        """
        self.stages[stage] = {
            "input": input_count,
            "output": output_count,
            "reduction": input_count - output_count,
        }
    
    def get_reductions(self) -> Dict[str, int]:
        """Get a map of stage to reduction count.
        
        Returns:
            Dictionary mapping stage names to their reduction counts
        """
        return {stage: data["reduction"] for stage, data in self.stages.items()}
    
    def get_first_reduction(self) -> Optional[Tuple[str, int]]:
        """Get the first stage that reduced the count.
        
        Returns:
            Tuple of (stage_name, reduction_count) or None
        """
        for stage, data in self.stages.items():
            if data["reduction"] > 0:
                return (stage, data["reduction"])
        return None
    
    def get_summary(self) -> str:
        """Get a formatted summary of all stage accounting.
        
        Returns:
            Formatted string summary
        """
        lines = []
        for stage, data in self.stages.items():
            reduction = data["reduction"]
            reduction_str = f"-{reduction}" if reduction > 0 else (f"+{-reduction}" if reduction < 0 else "0")
            lines.append(f"{stage}: {data['input']} -> {data['output']} ({reduction_str})")
        return " | ".join(lines)


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Configuration
    "DiagnosticConfig",
    "diagnostic_config",
    # Enums
    "PipelineStage",
    "StageStatus",
    "FailureCategory",
    "STAGE_NAMES",
    # Correlation ID
    "generate_run_id",
    "get_current_run_id",
    "set_current_run_id",
    # Context
    "DiagnosticContext",
    "diagnostic_context",
    # Logging helpers
    "get_diagnostic_logger",
    "log_with_redaction",
    # Stage logging
    "log_stage_a",
    "log_stage_b",
    "log_stage_c",
    "log_stage_d",
    "log_stage_e",
    "log_stage_f",
    "log_stage_g",
    "log_stage_h",
    "log_stage_i",
    "log_stage_j",
    "log_stage_k",
    "log_stage_l",
    # Redaction
    "redact_dict",
    "redact_url",
    "_redact_secrets",
    # Accounting
    "StageAccounting",
]
