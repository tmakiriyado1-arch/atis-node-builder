# NORA Diagnostic Logging Guide

This document describes the comprehensive diagnostic logging system implemented for NORA (Node & Ontology Retrieval Assistant) to provide end-to-end pipeline observability.

## Overview

The diagnostic logging system provides:
- **Correlation IDs**: Unique run identifiers propagated through all pipeline stages
- **Stage-by-stage logging**: Structured logging for each pipeline stage (A-L)
- **Loss accounting**: Tracking input/output counts at each stage boundary
- **Failure categorization**: Explicit classification of failure types
- **Secret redaction**: Automatic redaction of API keys, tokens, and credentials from logs
- **Configuration**: Environment variable-based control of diagnostic verbosity

## Quick Start

### Enable Diagnostic Logging

By default, diagnostic logging is enabled. Use these environment variables:

```bash
# Enable/disable diagnostics (default: true)
export NORA_DIAGNOSTICS_ENABLED=true

# Enable verbose output with content previews (default: false)
export NORA_DIAGNOSTICS_VERBOSE=false

# Maximum characters for content previews (default: 500)
export NORA_DIAGNOSTICS_PREVIEW_CHARS=500

# Enable JSON structured logging (default: false)
export NORA_DIAGNOSTICS_JSON=false

# Log level for diagnostics (default: INFO)
export NORA_DIAGNOSTICS_LOG_LEVEL=INFO
```

### In Code

```python
from app.services.diagnostic_logging import (
    DiagnosticContext,
    diagnostic_context,
    PipelineStage,
    StageStatus,
    get_diagnostic_logger,
    generate_run_id,
)

# Method 1: Using context manager
with diagnostic_context(run_id="abc123", entity_name="ZERA") as ctx:
    ctx.log_stage_start(PipelineStage.A, "API request and run initialization")
    # ... do work ...
    ctx.log_stage_end(
        PipelineStage.A,
        status=StageStatus.SUCCESS,
        input_count=1,
        output_count=1,
    )
    
    # Get final summary
    summary = ctx.get_summary()

# Method 2: Direct logger usage
logger = get_diagnostic_logger(run_id="abc123")
logger.info("Custom diagnostic message")

# Method 3: Generate run ID
run_id = generate_run_id()  # Returns UUID4 string
```

## Pipeline Stage Map

The NORA pipeline is divided into 12 stages, each with specific logging:

### Stage A: API Request and Run Initialization
- **Purpose**: Handle incoming API request and initialize research run
- **Log Events**: Request validation, run creation, configuration
- **Key Metrics**: Request fields, query length, run ID assignment

### Stage B: Search Execution
- **Purpose**: Execute search across configured providers
- **Log Events**: Provider queries, results, retries, failures
- **Key Metrics**: Results per provider, retry counts, provider errors
- **Counters**: `search_results_received`, `providers_attempted`, `providers_succeeded`, `providers_failed`

### Stage C: Raw URL Collection
- **Purpose**: Extract, normalize, and deduplicate URLs from search results
- **Log Events**: URL extraction, normalization, deduplication
- **Key Metrics**: Raw URLs, normalized URLs, duplicates removed
- **Counters**: `urls_extracted`, `urls_unique`, duplicate count

### Stage D: URL Quality Filtering
- **Purpose**: Apply filters to reject irrelevant, blocked, or low-quality URLs
- **Log Events**: Filter decisions with reasons
- **Key Metrics**: Accepted/rejected counts per filter
- **Counters**: `urls_accepted`, `urls_rejected`
- **Rejection Reasons**:
  - `invalid_url`
  - `unsupported_scheme`
  - `duplicate`
  - `blocked_domain`
  - `unwanted_file_extension`
  - `irrelevant_domain`
  - `search_result_lacks_destination`
  - `filter_exception`

### Stage E: Page Fetching and HTTP Retrieval
- **Purpose**: Fetch page content from accepted URLs
- **Log Events**: HTTP requests, status codes, redirects, errors
- **Key Metrics**: Fetch duration, HTTP status, content type, response size
- **Counters**: `pages_fetch_succeeded`, `pages_fetch_failed`

### Stage F: Text Extraction and Content Preparation
- **Purpose**: Extract and normalize text from fetched pages
- **Log Events**: Extraction method, text length, content quality
- **Key Metrics**: Text length, empty content detection
- **Counters**: `pages_usable_text`

### Stage G: LLM Request Preparation
- **Purpose**: Prepare prompts and inputs for LLM calls
- **Log Events**: Prompt construction, token counts, input validation
- **Key Metrics**: Prompt length, evidence count, token estimates
- **Counters**: (implied by LLM call counts)

### Stage H: LLM Request and Response
- **Purpose**: Execute LLM calls and capture responses
- **Log Events**: Request duration, HTTP status, retries, token usage
- **Key Metrics**: Duration, tokens (input/output), retry count
- **Counters**: `llm_calls_attempted`, `llm_calls_succeeded`, `llm_calls_failed`
- **Transport vs Semantic**: Distinguishes HTTP success from extraction success

### Stage I: LLM Response Parsing and Normalization
- **Purpose**: Parse and normalize LLM responses
- **Log Events**: Parsing success/failure, schema validation
- **Key Metrics**: Parsed items, invalid items, validation errors
- **Failure Types**:
  - `LLM_NORMALIZATION_FAILED`
  - `JSON_PARSE_FAILED`
  - `SCHEMA_MISMATCH`

### Stage J: Evidence Creation and Persistence
- **Purpose**: Create evidence records and persist to database
- **Log Events**: Evidence generation, validation, database operations
- **Key Metrics**: Generated/validated/persisted counts
- **Counters**: `evidence_items_generated`, `evidence_items_validated`, `evidence_items_persisted`

### Stage K: Semantic Extraction and Claim Generation
- **Purpose**: Extract atomic evidence and generate claims
- **Log Events**: Extraction results, claim validation
- **Key Metrics**: Evidence count, claim count, rejection reasons
- **Counters**: `claims_candidates`, `claims_rejected`, `claims_persisted`

### Stage L: Run Completion and Final Summary
- **Purpose**: Generate final diagnostic summary
- **Log Events**: Complete run summary with all metrics
- **Key Metrics**: All stage counts, failure analysis, duration

## Log Event Names and Fields

### Common Fields
All diagnostic log events include:
- `run_id`: Unique correlation ID
- `stage`: Pipeline stage identifier (A-L)
- `status`: Stage status (started, success, partial_success, skipped, failed)
- `timestamp`: ISO 8601 timestamp
- `duration_ms`: Stage duration in milliseconds (when ended)

### Stage-Specific Fields

#### Stage A
```json
{
  "stage": "A",
  "operation": "POST",
  "endpoint": "/api/research",
  "query": "ZERA",
  "status": "success"
}
```

#### Stage B
```json
{
  "stage": "B",
  "provider": "AppsScript",
  "query": "ZERA",
  "results": 10,
  "retries": 2,
  "status": "success"
}
```

#### Stage C
```json
{
  "stage": "C",
  "raw": 15,
  "unique": 10,
  "duplicates": 5,
  "reduction": 5
}
```

#### Stage D
```json
{
  "stage": "D",
  "filter": "DomainFilter",
  "input": 10,
  "accepted": 8,
  "rejected": 2,
  "reason": "blocked_domain"
}
```

#### Stage E
```json
{
  "stage": "E",
  "url": "https://example.com",
  "status": 200,
  "content_type": "text/html",
  "size": 1024,
  "status": "success"
}
```

#### Stage F
```json
{
  "stage": "F",
  "url": "https://example.com",
  "text_length": 500,
  "empty": false,
  "status": "success"
}
```

#### Stage G
```json
{
  "stage": "G",
  "model": "mistral-large",
  "prompt_length": 1000,
  "evidence_count": 3,
  "status": "success"
}
```

#### Stage H
```json
{
  "stage": "H",
  "model": "mistral-large",
  "duration_ms": 5000.5,
  "http_status": 200,
  "tokens_in": 1000,
  "tokens_out": 500,
  "retries": 1,
  "status": "success"
}
```

#### Stage I
```json
{
  "stage": "I",
  "parsed": 5,
  "invalid": 2,
  "status": "success"
}
```

#### Stage J
```json
{
  "stage": "J",
  "generated": 10,
  "validated": 8,
  "persisted": 8,
  "status": "success"
}
```

#### Stage K
```json
{
  "stage": "K",
  "evidence": 5,
  "claims": 10,
  "rejected": 2,
  "status": "success"
}
```

#### Stage L (Summary)
```json
{
  "run_id": "abc123",
  "entity_name": "ZERA",
  "start_time": "2024-01-01T00:00:00Z",
  "end_time": "2024-01-01T00:05:00Z",
  "duration_ms": 300000,
  "stages": {
    "A": {"status": "success", "duration_ms": 100, ...},
    "B": {"status": "success", "duration_ms": 5000, ...},
    ...
  },
  "counters": {
    "search_results_received": 15,
    "urls_extracted": 12,
    "urls_unique": 10,
    "urls_accepted": 8,
    "urls_rejected": 2,
    "pages_fetch_succeeded": 8,
    "pages_fetch_failed": 0,
    "pages_usable_text": 6,
    "llm_calls_attempted": 3,
    "llm_calls_succeeded": 3,
    "llm_calls_failed": 0,
    "evidence_items_generated": 15,
    "evidence_items_validated": 12,
    "evidence_items_persisted": 12,
    "claims_candidates": 20,
    "claims_rejected": 5,
    "claims_persisted": 15
  },
  "failure_stage": null,
  "primary_failure_reason": null,
  "warnings": [],
  "errors": []
}
```

## Failure Identification

The system automatically identifies the first failing stage based on counter analysis:

### Zero Evidence Scenarios

| Symptoms | Failure Stage | Primary Reason |
|----------|---------------|----------------|
| `llm_calls_succeeded > 0`, `evidence_items_generated == 0` | K | LLM succeeded but extracted zero atomic evidence |
| `llm_calls_failed > 0`, `evidence_items_generated == 0` | H | LLM calls failed |
| `llm_calls_attempted == 0`, `evidence_items_generated == 0` | G | LLM not called |
| `pages_usable_text == 0`, `evidence_items_generated == 0` | F | No usable text extracted from pages |
| `pages_fetch_succeeded == 0`, `evidence_items_generated == 0` | E | No pages fetched successfully |
| `urls_accepted == 0`, `evidence_items_generated == 0` | D | No URLs accepted after filtering |
| `urls_unique == 0`, `evidence_items_generated == 0` | C | No unique URLs after deduplication |
| `urls_extracted == 0` or `search_results_received == 0` | B | No URLs extracted / No search results |

### Zero Claims Scenarios

| Symptoms | Failure Stage | Primary Reason |
|----------|---------------|----------------|
| `evidence_items_generated == 0` | (see above) | Evidence failure |
| `evidence_items_validated == 0`, `evidence_items_generated > 0` | J | Evidence validation failed |
| `claims_candidates == 0`, `evidence_items_validated > 0` | K | No claims generated from evidence |

## Filtering Logs by Run ID in Render

In Render's log viewer:

1. Navigate to the service logs
2. Use the search/filter function
3. Search for your run ID (e.g., `950b96ed-3609-4bf3-b5a3-9a966111518a`)
4. All logs for that run will be displayed with the `[run_id]` prefix

### Example Log Pattern
```
[2024-01-01 00:00:00] [atis_node_builder.diagnostics] [950b96ed-3609-4bf3-b5a3-9a966111518a] STAGE B STARTED: Search execution
[2024-01-01 00:00:01] [atis_node_builder.diagnostics] [950b96ed-3609-4bf3-b5a3-9a966111518a] STAGE B: provider=AppsScript results=10
[2024-01-01 00:00:02] [atis_node_builder.diagnostics] [950b96ed-3609-4bf3-b5a3-9a966111518a] STAGE C: raw=15 unique=10 duplicates=5
[2024-01-01 00:00:03] [atis_node_builder.diagnostics] [950b96ed-3609-4bf3-b5a3-9a966111518a] STAGE D: filter=DomainFilter accepted=8 rejected=2
```

## Secret Redaction

The system automatically redacts:
- API keys (sk-*, Bearer tokens)
- Authorization headers
- Passwords and secrets
- Query parameters containing credentials
- URL fragments that may contain tokens

### Redaction Patterns

```python
# Bearer tokens
"Bearer eyJ..." -> "Bearer [REDACTED]"

# API keys
"api_key=abc123" -> "api_key=[REDACTED]"
"sk-abc123def456" -> "[REDACTED]"

# URLs
"https://api.example.com?token=abc123" -> "https://api.example.com?token=%5BREDACTED%5D"
```

## Configuration Reference

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `NORA_DIAGNOSTICS_ENABLED` | `true` | Master switch for diagnostic logging |
| `NORA_DIAGNOSTICS_VERBOSE` | `false` | Enable verbose output with content previews |
| `NORA_DIAGNOSTICS_PREVIEW_CHARS` | `500` | Max characters for content previews |
| `NORA_DIAGNOSTICS_JSON` | `false` | Enable JSON structured logging |
| `NORA_DIAGNOSTICS_LOG_LEVEL` | `INFO` | Log level (DEBUG, INFO, WARNING, ERROR) |

### Python API

```python
from app.services.diagnostic_logging import (
    # Configuration
    diagnostic_config,
    DiagnosticConfig,
    
    # Correlation IDs
    generate_run_id,
    get_current_run_id,
    set_current_run_id,
    
    # Context
    DiagnosticContext,
    diagnostic_context,
    
    # Logging
    get_diagnostic_logger,
    log_with_redaction,
    
    # Stage logging
    log_stage_a, log_stage_b, log_stage_c, log_stage_d,
    log_stage_e, log_stage_f, log_stage_g, log_stage_h,
    log_stage_i, log_stage_j, log_stage_k, log_stage_l,
    
    # Utilities
    redact_dict, redact_url, _redact_secrets,
    StageAccounting, StageAccounting,
    
    # Enums
    PipelineStage, StageStatus, FailureCategory, STAGE_NAMES,
)
```

## Testing

Run the diagnostic logging tests:

```bash
# Run all diagnostic tests
python3 -m pytest tests/unit/test_diagnostic_logging.py -v

# Run with coverage
python3 -m pytest tests/unit/test_diagnostic_logging.py --cov=app.services.diagnostic_logging
```

## Troubleshooting

### No Logs Appearing
1. Check `NORA_DIAGNOSTICS_ENABLED` is set to `true`
2. Verify log level is not too high (use `DEBUG` for maximum output)
3. Check that the run ID is being propagated through the pipeline

### Logs Too Verbose
1. Set `NORA_DIAGNOSTICS_VERBOSE=false`
2. Reduce `NORA_DIAGNOSTICS_PREVIEW_CHARS`
3. Use `INFO` or `WARNING` log level instead of `DEBUG`

### Secrets in Logs
1. Verify `_redact_secrets()` is being called on all user content
2. Check that `redact_dict()` is used for dictionary data
3. Use `redact_url()` for URL logging
4. Add new patterns to the redaction list if needed

## Architecture

### Module Structure

```
app/services/diagnostic_logging.py    # Main diagnostic logging module
app/logging_config.py                # Application logging configuration
app/services/research/search_orchestrator.py  # Stage B logging integrated
```

### Data Flow

```
Request -> generate_run_id() -> DiagnosticContext -> Stage Logging -> Summary
                              -> get_diagnostic_logger() -> Log Events
```

### Thread Safety

- Run IDs are stored in thread-local storage
- Each thread can have its own current run ID
- Context managers properly restore previous run IDs
- Safe for concurrent pipeline executions

## Examples

### Example 1: Full Pipeline with Diagnostics

```python
from app.services.diagnostic_logging import diagnostic_context, PipelineStage, StageStatus

async def run_research(entity_name: str):
    with diagnostic_context(run_id=generate_run_id(), entity_name=entity_name) as ctx:
        # Stage A
        ctx.log_stage_start(PipelineStage.A)
        # ... validate request ...
        ctx.log_stage_end(PipelineStage.A, status=StageStatus.SUCCESS)
        
        # Stage B
        ctx.log_stage_start(PipelineStage.B)
        results = await search_provider.search(entity_name)
        ctx.increment_counter("search_results_received", len(results))
        ctx.log_stage_end(
            PipelineStage.B,
            status=StageStatus.SUCCESS,
            input_count=1,
            output_count=len(results),
        )
        
        # ... continue through stages ...
        
        # Get final summary
        summary = ctx.get_summary()
        logger.info(f"Research completed: {json.dumps(summary, indent=2)}")
```

### Example 2: Quick Debugging

```python
from app.services.diagnostic_logging import get_diagnostic_logger

logger = get_diagnostic_logger(run_id="debug_123")
logger.info("Starting debug session")
logger.warning("Found potential issue")
logger.error("Critical error occurred")
```

### Example 3: Manual Stage Accounting

```python
from app.services.diagnostic_logging import StageAccounting

accounting = StageAccounting()
accounting.record("search", input_count=100, output_count=80)
accounting.record("filter", input_count=80, output_count=50)
accounting.record("fetch", input_count=50, output_count=40)

print(accounting.get_summary())
# Output: search: 100 -> 80 (-20) | filter: 80 -> 50 (-30) | fetch: 50 -> 40 (-10)

first_reduction = accounting.get_first_reduction()
# Returns: ("search", 20)
```

## Performance Considerations

- Diagnostic logging adds minimal overhead (~1-2ms per log event)
- String redaction is O(n) on content length
- JSON serialization only occurs when `NORA_DIAGNOSTICS_JSON=true`
- Stage accounting uses simple integer operations
- Thread-local storage has negligible overhead

## Future Enhancements

- Metrics export to external monitoring systems
- Log aggregation and analysis dashboards
- Anomaly detection based on historical patterns
- Automated failure classification
- Integration with error tracking services
