"""Tests for canonical Mistral response normalization.

These tests cover the normalization of Mistral API responses across all LLM consumers.
"""
import pytest
from unittest.mock import MagicMock, patch

from app.services.research.mistral_response import (
    normalize_mistral_content,
    extract_mistral_message_content,
)


# =============================================================================
# Test 1: Normal string content
# =============================================================================
def test_normalize_string_content():
    """Test that normal string content is returned as-is."""
    content = "This is a normal string response"
    result = normalize_mistral_content(content, context="TEST")
    assert result == content


# =============================================================================
# Test 2: List of text blocks
# =============================================================================
def test_normalize_list_of_strings():
    """Test that a list of strings is concatenated with newlines."""
    content = ["First block", "Second block", "Third block"]
    result = normalize_mistral_content(content, context="TEST")
    assert result == "First block\nSecond block\nThird block"


# =============================================================================
# Test 3: Empty list
# =============================================================================
def test_normalize_empty_list():
    """Test that an empty list returns None."""
    content = []
    result = normalize_mistral_content(content, context="TEST")
    assert result is None


# =============================================================================
# Test 4: None content
# =============================================================================
def test_normalize_none_content():
    """Test that None returns None."""
    result = normalize_mistral_content(None, context="TEST")
    assert result is None


# =============================================================================
# Test 5: List of content blocks with 'text' field
# =============================================================================
def test_normalize_list_of_text_blocks():
    """Test that a list of dicts with 'text' fields is normalized."""
    content = [
        {"type": "text", "text": "First part"},
        {"type": "text", "text": "Second part"},
    ]
    result = normalize_mistral_content(content, context="TEST")
    assert result == "First part\nSecond part"


# =============================================================================
# Test 6: List of content blocks with 'content' field
# =============================================================================
def test_normalize_list_of_content_blocks():
    """Test that a list of dicts with 'content' fields is normalized."""
    content = [
        {"type": "output", "content": "First part"},
        {"type": "output", "content": "Second part"},
    ]
    result = normalize_mistral_content(content, context="TEST")
    assert result == "First part\nSecond part"


# =============================================================================
# Test 7: Dict with 'content' field
# =============================================================================
def test_normalize_dict_with_content_field():
    """Test that a dict with 'content' field is normalized."""
    content = {"content": "The actual content"}
    result = normalize_mistral_content(content, context="TEST")
    assert result == "The actual content"


# =============================================================================
# Test 8: Dict with 'text' field
# =============================================================================
def test_normalize_dict_with_text_field():
    """Test that a dict with 'text' field is normalized."""
    content = {"text": "The text content"}
    result = normalize_mistral_content(content, context="TEST")
    assert result == "The text content"


# =============================================================================
# Test 9: Dict with nested content
# =============================================================================
def test_normalize_dict_with_nested_content():
    """Test that a dict with nested content is recursively normalized."""
    content = {"message": {"content": "Nested content"}}
    result = normalize_mistral_content(content, context="TEST")
    assert result == "Nested content"


# =============================================================================
# Test 10: Malformed structured content
# =============================================================================
def test_normalize_malformed_structured_content():
    """Test that malformed structured content returns None."""
    content = [{"type": "unknown", "data": 123}, {"type": "text"}]
    result = normalize_mistral_content(content, context="TEST")
    assert result is None


# =============================================================================
# Test 11: extract_mistral_message_content with standard response
# =============================================================================
def test_extract_standard_response():
    """Test extraction from a standard Mistral API response."""
    response_data = {
        "choices": [
            {
                "message": {
                    "content": '{"result": "success"}'
                }
            }
        ]
    }
    result = extract_mistral_message_content(response_data, context="TEST")
    assert result == '{"result": "success"}'


# =============================================================================
# Test 12: extract_mistral_message_content with list content
# =============================================================================
def test_extract_list_content():
    """Test extraction when content is a list."""
    response_data = {
        "choices": [
            {
                "message": {
                    "content": ["First", "Second"]
                }
            }
        ]
    }
    result = extract_mistral_message_content(response_data, context="TEST")
    assert result == "First\nSecond"


# =============================================================================
# Test 13: extract_mistral_message_content with empty choices
# =============================================================================
def test_extract_empty_choices():
    """Test extraction when choices is empty."""
    response_data = {"choices": []}
    result = extract_mistral_message_content(response_data, context="TEST")
    assert result is None


# =============================================================================
# Test 14: extract_mistral_message_content with no choices
# =============================================================================
def test_extract_no_choices():
    """Test extraction when there's no choices field."""
    response_data = {}
    result = extract_mistral_message_content(response_data, context="TEST")
    assert result is None


# =============================================================================
# Test 15: extract_mistral_message_content with non-dict choice
# =============================================================================
def test_extract_non_dict_choice():
    """Test extraction when choice is not a dict."""
    response_data = {
        "choices": ["not a dict"]
    }
    result = extract_mistral_message_content(response_data, context="TEST")
    assert result is None


# =============================================================================
# Test 16: extract_mistral_message_content with non-dict message
# =============================================================================
def test_extract_non_dict_message():
    """Test extraction when message is not a dict."""
    response_data = {
        "choices": [
            {"message": "not a dict"}
        ]
    }
    result = extract_mistral_message_content(response_data, context="TEST")
    assert result is None


# =============================================================================
# Test 17: Mixed content types in list
# =============================================================================
def test_normalize_mixed_content_list():
    """Test normalization of list with mixed content types."""
    content = [
        "Plain text",
        {"text": "Text block"},
        {"content": "Content block"},
    ]
    result = normalize_mistral_content(content, context="TEST")
    assert result == "Plain text\nText block\nContent block"


# =============================================================================
# Test 18: List with empty strings
# =============================================================================
def test_normalize_list_with_empty_strings():
    """Test normalization of list with empty strings."""
    content = ["First", "", "Second"]
    result = normalize_mistral_content(content, context="TEST")
    # Empty strings are preserved
    assert result == "First\n\nSecond"


# =============================================================================
# Test 19: Dict with unknown fields
# =============================================================================
def test_normalize_dict_with_unknown_fields():
    """Test that dict with unknown fields tries to find any string value."""
    content = {"unknown_field": "value", "other": 123}
    result = normalize_mistral_content(content, context="TEST")
    assert result == "value"


# =============================================================================
# Test 20: Dict with no string values
# =============================================================================
def test_normalize_dict_with_no_string_values():
    """Test that dict with no string values returns None."""
    content = {"number": 123, "list": [1, 2, 3]}
    result = normalize_mistral_content(content, context="TEST")
    assert result is None


# =============================================================================
# Test: Logging verification (capsys fixture)
# =============================================================================
@pytest.mark.parametrize("content,expected_log", [
    ("string", "LLM_CONTENT_TYPE=str"),
    (["list"], "LLM_CONTENT_TYPE=list"),
    (None, "LLM_CONTENT_TYPE=None"),
    ({"key": "value"}, "LLM_CONTENT_TYPE=dict"),
])
def test_logging_on_normalization(content, expected_log, caplog):
    """Test that normalization logs the content type."""
    import logging
    with caplog.at_level(logging.INFO):
        normalize_mistral_content(content, context="TEST")
        assert expected_log in caplog.text
