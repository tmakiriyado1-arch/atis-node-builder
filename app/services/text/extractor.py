"""Content extraction from raw crawler output.

Contract:
- HTML input is parsed and non-content elements are removed
- Returned text is suitable for downstream NLP processing
- This function MUST NOT return raw HTML for HTML input
- Non-HTML content is passed through unchanged (current scope: HTML only)
- Effective content type is determined and returned
"""

from typing import Optional
from bs4 import BeautifulSoup, Comment
import logging
import re

logger = logging.getLogger(__name__)


class TextExtractionError(Exception):
    """Raised when text extraction fails and cannot produce semantic text."""
    pass


# Conservative HTML sniffing: look for actual HTML tags, not just '<'
_HTML_HINT_RE = re.compile(
    r"<\s*/?\s*(?:html|head|body|script|style|div|p|article|section|main|table|span|a|img|br|hr|ul|ol|li|h[1-6]|blockquote|pre|code)\b",
    re.IGNORECASE,
)


def is_html_content_type(content_type: Optional[str]) -> bool:
    """Check if declared content type indicates HTML."""
    if not content_type:
        return False
    ct = content_type.lower()
    return "html" in ct or "xhtml" in ct


def detect_content_type(raw: str, declared: Optional[str] = None) -> str:
    """
    Determine effective content type from declared type and content.

    Returns the effective type used for extraction.
    """
    if declared and is_html_content_type(declared):
        return "text/html"

    # Check if content looks like HTML even if declared otherwise
    if _HTML_HINT_RE.search(raw[:4096]):
        return "text/html"

    # Default to declared type, or unknown
    return declared or "unknown"


def extract_text(raw: str, content_type: Optional[str] = None) -> str:
    """
    Convert an HTML source document into semantic textual content.

    Contract:
    - HTML input is parsed.
    - Non-content elements (script, style, etc.) are removed.
    - Returned text is suitable for downstream NLP processing.
    - This function MUST NOT return raw HTML for HTML input.
    - Non-HTML content is passed through unchanged (current scope: HTML only).

    Raises:
        TextExtractionError: If extraction fails. Caller must handle or propagate.
    """
    if not raw:
        return ""

    # Determine effective content type
    effective_ct = detect_content_type(raw, content_type)

    # If not HTML, return as-is
    if effective_ct != "text/html":
        return raw

    try:
        soup = BeautifulSoup(raw, "html.parser")

        # Remove non-content elements
        for tag in ["script", "style", "noscript", "template", "head", "iframe", "svg"]:
            for element in soup.find_all(tag):
                element.decompose()

        # Remove comments
        for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
            comment.extract()

        # Extract text with spacing between blocks
        return " ".join(soup.stripped_strings)

    except Exception as exc:
        # Log once at the extraction level
        logger.exception(
            "TEXT_EXTRACTION_FAILED",
            extra={"content_length": len(raw)},
        )
        raise TextExtractionError(
            f"Failed to extract text from content (length={len(raw)}, type={effective_ct})"
        ) from exc
