"""Tests for text extraction functionality."""

import pytest
from unittest.mock import patch
from bs4 import BeautifulSoup

from app.services.text.extractor import (
    extract_text,
    detect_content_type,
    is_html_content_type,
    TextExtractionError,
)


class TestContentTypeDetection:
    """Tests for content type detection logic."""

    def test_is_html_content_type(self):
        assert is_html_content_type("text/html") == True
        assert is_html_content_type("text/html; charset=utf-8") == True
        assert is_html_content_type("application/xhtml+xml") == True
        assert is_html_content_type("text/plain") == False
        assert is_html_content_type("application/json") == False
        assert is_html_content_type(None) == False

    def test_detect_content_type_html_declared(self):
        assert detect_content_type("<p>test</p>", "text/html") == "text/html"

    def test_detect_content_type_html_sniffed(self):
        # Mislabeled HTML should be detected
        html = "<html><body>test</body></html>"
        assert detect_content_type(html, "application/octet-stream") == "text/html"

    def test_detect_content_type_non_html(self):
        # Plain text with < should NOT be detected as HTML
        text = "GDP < 5% in 2025"
        assert detect_content_type(text, "text/plain") == "text/plain"

        # Technical text with < should NOT be detected as HTML
        text = "The expression <company> represents the company"
        assert detect_content_type(text, "text/plain") == "text/plain"

        # Only actual HTML tags trigger detection
        text = "Some text <div>content</div> more"
        assert detect_content_type(text, "text/plain") == "text/html"

    def test_detect_content_type_fallback(self):
        assert detect_content_type("plain text", None) == "unknown"
        assert detect_content_type("plain text", "application/json") == "application/json"


class TestExtraction:
    """Tests for HTML extraction functionality."""

    def test_simple_html(self):
        html = "<html><body><p>Hello World</p></body></html>"
        assert extract_text(html, "text/html") == "Hello World"

    def test_nested_elements(self):
        html = "<div><p>Para 1</p><p>Para 2</p></div>"
        result = extract_text(html, "text/html")
        assert "Para 1" in result
        assert "Para 2" in result

    def test_script_removal(self):
        html = "<script>var x = '<div>'; if (a < b) { console.log('>'); }</script><p>Text</p>"
        assert extract_text(html, "text/html") == "Text"

    def test_style_removal(self):
        html = "<style>body { color: red; }</style><p>Text</p>"
        assert extract_text(html, "text/html") == "Text"

    def test_noscript_removal(self):
        html = "<noscript>No JS</noscript><p>With JS</p>"
        result = extract_text(html, "text/html")
        assert "With JS" in result
        assert "No JS" not in result

    def test_html_comments(self):
        html = "<!-- comment --><p>Text</p><!-- another -->"
        assert extract_text(html, "text/html") == "Text"

    def test_attributes_with_special_chars(self):
        html = '<div title="a > b" data-x="c < d">Content</div>'
        assert extract_text(html, "text/html") == "Content"

    def test_non_html_passthrough(self):
        text = "Plain text with < and > characters"
        assert extract_text(text, "text/plain") == text

    def test_empty_input(self):
        assert extract_text("", "text/html") == ""

    def test_production_failure_regression(self):
        """Reproduce the exact production failure that triggered this fix."""
        html = """<html>
        <head>
        <script>window.onload = function() {}</script>
        </head>
        <body>Theotechnic College to equip leaders...</body>
        </html>"""
        result = extract_text(html, "text/html")
        assert "<" not in result
        assert "Theotechnic College" in result
        assert "to equip leaders" in result


class TestExtractionFailure:
    """Tests for extraction failure handling."""

    def test_extraction_failure_raises_error(self):
        """Regression: extraction failure must NOT return raw HTML."""
        # Mock BeautifulSoup to fail
        with patch('app.services.text.extractor.BeautifulSoup') as mock_bs:
            mock_bs.side_effect = Exception("Parse error")

            with pytest.raises(TextExtractionError) as exc_info:
                extract_text("<html><body>Broken</body></html>", "text/html")

            assert "Failed to extract text" in str(exc_info.value)
            assert "Parse error" in str(exc_info.value.__cause__)

    def test_extraction_failure_never_returns_html(self):
        """Ensure no code path returns raw HTML on failure."""
        # Even with malformed HTML that might cause issues
        bad_html = "<html><body><div"  # Unclosed tag

        # This should either succeed or raise, never return HTML
        try:
            result = extract_text(bad_html, "text/html")
            # If it succeeded, verify it's not raw HTML
            assert "<" not in result
        except TextExtractionError:
            # Expected - extraction failed
            pass


class TestIntegration:
    """Integration tests for the complete evidence pipeline."""

    def test_evidence_creation_with_html(self):
        """HTML crawl should produce normalized evidence."""
        from app.services.research.evidence import EvidenceRecord

        html = "<html><body><p>Test content</p></body></html>"

        evidence = EvidenceRecord.from_crawl(
            url="https://example.com",
            title="Test",
            raw_content=html,
            declared_content_type="text/html",
        )

        assert "<" not in evidence.normalized_text
        assert "Test content" in evidence.normalized_text
        assert evidence.content_type == "text/html"

    def test_evidence_creation_with_mislabeled_html(self):
        """Mislabeled HTML should be detected and extracted."""
        from app.services.research.evidence import EvidenceRecord

        html = "<html><body><p>Test content</p></body></html>"

        evidence = EvidenceRecord.from_crawl(
            url="https://example.com",
            title="Test",
            raw_content=html,
            declared_content_type="application/octet-stream",  # Wrong!
        )

        # Should detect as HTML despite wrong content type
        assert evidence.content_type == "text/html"
        assert "<" not in evidence.normalized_text
        assert "Test content" in evidence.normalized_text

    def test_evidence_creation_with_plain_text(self):
        """Plain text should pass through unchanged."""
        from app.services.research.evidence import EvidenceRecord

        text = "Plain text with < and > characters"

        evidence = EvidenceRecord.from_crawl(
            url="https://example.com",
            title="Test",
            raw_content=text,
            declared_content_type="text/plain",
        )

        assert evidence.normalized_text == text
        assert evidence.content_type == "text/plain"

    def test_evidence_creation_failure_propagates(self):
        """Extraction failure should propagate, not return contaminated evidence."""
        from app.services.research.evidence import EvidenceRecord

        # Mock extract_text to fail
        with patch('app.services.text.extractor.extract_text') as mock_extract:
            mock_extract.side_effect = TextExtractionError("Failed")

            with pytest.raises(TextExtractionError):
                EvidenceRecord.from_crawl(
                    url="https://example.com",
                    title="Test",
                    raw_content="<html>bad</html>",
                    declared_content_type="text/html",
                )
