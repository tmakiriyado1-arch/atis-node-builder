"""
Application logging setup with diagnostic support.

This module provides the base logging configuration for NORA, including:
- Standard logging setup
- Diagnostic logging configuration via environment variables
- Integration with the diagnostic_logging module

Environment Variables:
    NORA_DIAGNOSTICS_ENABLED: Enable/disable diagnostic logging (default: true)
    NORA_DIAGNOSTICS_VERBOSE: Enable verbose diagnostic output (default: false)
    NORA_DIAGNOSTICS_PREVIEW_CHARS: Max characters for content previews (default: 500)
    NORA_DIAGNOSTICS_JSON: Enable JSON structured logging (default: false)
    NORA_DIAGNOSTICS_LOG_LEVEL: Log level for diagnostics (default: INFO)
"""
import logging
import os
import sys


# =============================================================================
# Standard Logger
# =============================================================================

logger = logging.getLogger("atis_node_builder")


# =============================================================================
# Diagnostic Logger
# =============================================================================

def get_diagnostic_logger(run_id: str = None, name: str = None):
    """Get a diagnostic logger with optional run ID correlation.
    
    This function provides a convenient way to get a logger that includes
    diagnostic context. For full diagnostic logging capabilities, use
    the diagnostic_logging module directly.
    
    Args:
        run_id: Optional run ID for correlation
        name: Optional logger name
        
    Returns:
        A logger instance
    """
    # Import here to avoid circular dependencies
    from app.services.diagnostic_logging import get_diagnostic_logger as get_diag_logger
    
    if run_id:
        return get_diag_logger(run_id=run_id, name=name)
    return get_diag_logger(name=name)


def setup_logging():
    """Configure application-wide logging.
    
    This function sets up the base logging configuration for the application.
    It respects the diagnostic configuration environment variables for
    enhanced logging when enabled.
    
    Returns:
        The main application logger
    """
    # Check if diagnostics are enabled
    diagnostics_enabled = os.environ.get("NORA_DIAGNOSTICS_ENABLED", "true").lower() in ("true", "1", "yes")
    json_logging = os.environ.get("NORA_DIAGNOSTICS_JSON", "false").lower() in ("true", "1", "yes")
    log_level = os.environ.get("NORA_DIAGNOSTICS_LOG_LEVEL", "INFO").upper()
    
    # Determine log level
    level = getattr(logging, log_level, logging.INFO)
    
    # Configure format based on JSON preference
    if json_logging:
        # JSON format for structured logging
        import json
        import threading
        
        class JSONFormatter(logging.Formatter):
            """Custom formatter for JSON output."""
            
            def format(self, record):
                # Get thread-local run ID if available
                from app.services.diagnostic_logging import get_current_run_id
                run_id = get_current_run_id()
                
                log_data = {
                    "timestamp": self.formatTime(record),
                    "level": record.levelname,
                    "logger": record.name,
                    "message": record.getMessage(),
                    "thread": threading.current_thread().name,
                }
                
                # Add run_id if available
                if run_id:
                    log_data["run_id"] = run_id
                
                # Add extra fields
                extra_fields = {}
                for key, value in record.__dict__.items():
                    if key not in (
                        'name', 'msg', 'args', 'created', 'filename', 'funcName',
                        'levelname', 'levelno', 'lineno', 'module', 'msecs',
                        'pathname', 'process', 'processName', 'relativeCreated',
                        'stack_info', 'exc_info', 'exc_text', 'thread', 'threadName',
                        'message', 'asctime'
                    ):
                        try:
                            # Make sure the value is JSON serializable
                            json.dumps(value)
                            extra_fields[key] = value
                        except (TypeError, ValueError):
                            extra_fields[key] = str(value)
                
                if extra_fields:
                    log_data["extra"] = extra_fields
                
                # Handle exceptions
                if record.exc_info:
                    log_data["exception"] = {
                        "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                        "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                    }
                
                return json.dumps(log_data, default=str)
        
        # Create handler with JSON formatter
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JSONFormatter())
        handler.setLevel(level)
        
        # Configure root logger
        root_logger = logging.getLogger()
        root_logger.handlers.clear()
        root_logger.addHandler(handler)
        root_logger.setLevel(level)
    else:
        # Standard text format
        if diagnostics_enabled:
            # Enhanced format with run ID support
            format_str = '%(asctime)s - %(name)s - %(levelname)s - [%(run_id)s] %(message)s'
        else:
            # Standard format
            format_str = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        
        logging.basicConfig(
            level=level,
            format=format_str
        )
    
    # Suppress verbose third-party loggers
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("anyio").setLevel(logging.WARNING)
    
    # Set up diagnostic logging module
    setup_diagnostic_logging()
    
    return logger


def setup_diagnostic_logging():
    """Set up the diagnostic logging module.
    
    This function initializes the diagnostic logging configuration
    and ensures it's properly integrated with the application logging.
    """
    try:
        # Import diagnostic logging module to ensure it's initialized
        from app.services import diagnostic_logging
        
        # Re-read configuration in case environment changed
        diagnostic_logging.diagnostic_config = diagnostic_logging.DiagnosticConfig()
        
        # Set up the diagnostic logger
        diag_logger = logging.getLogger("atis_node_builder.diagnostics")
        
        # If we have handlers on the root logger, share them
        root_logger = logging.getLogger()
        if root_logger.handlers:
            for handler in root_logger.handlers:
                diag_logger.addHandler(handler)
        
        # Set level from diagnostic config
        level = getattr(logging, diagnostic_logging.diagnostic_config.log_level, logging.INFO)
        diag_logger.setLevel(level)
        
    except ImportError:
        # Diagnostic logging module not available, continue without it
        pass


# Initialize diagnostic logging on import
setup_diagnostic_logging()
