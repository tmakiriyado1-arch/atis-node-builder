"""Canonical Mistral API response normalization.

This module provides a single, canonical function for normalizing Mistral API responses
across all LLM consumers (LLMRanker, RelevanceFilter, MistralSemanticExtractor).

The Mistral API can return content in different formats:
- Normal string content
- List of content blocks (when using certain response formats)
- Empty list
- None
- Structured blocks with text fields

This normalization ensures all consumers receive a consistent string representation
suitable for JSON parsing or downstream processing.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Union

from app.logging import logger


def normalize_mistral_content(
    raw_content: Any,
    context: str = "unknown",
) -> Optional[str]:
    """Normalize Mistral API response content to a clean string.
    
    This function handles all known Mistral response content formats and
    extracts textual content suitable for JSON parsing or downstream use.
    
    Args:
        raw_content: The raw content from Mistral API (can be str, list, dict, or None)
        context: Context string for logging (e.g., "LLM_RANKER", "RELEVANCE_FILTER")
        
    Returns:
        Normalized string content, or None if no textual content can be extracted
        
    Behavior:
        1. Accept normal string content -> return as-is
        2. Accept list of text blocks -> concatenate with newlines
        3. Accept list of content blocks with 'text' or 'content' fields -> extract text
        4. Accept empty list -> return None
        5. Accept None -> return None
        6. Accept dict -> try to extract text from known fields
        7. Log the actual response shape when normalization fails
        8. Never fabricate content
    """
    # Log the raw content type and shape for diagnostics
    content_type = type(raw_content).__name__
    
    logger.info(f"[MISTRAL_RESPONSE {context}] LLM_CONTENT_TYPE={content_type}")
    
    if raw_content is None:
        logger.info(f"[MISTRAL_RESPONSE {context}] LLM_CONTENT_SHAPE=None")
        return None
    
    if isinstance(raw_content, str):
        # Normal string content - this is the expected case
        logger.info(f"[MISTRAL_RESPONSE {context}] LLM_CONTENT_SHAPE=str length={len(raw_content)}")
        return raw_content
    
    if isinstance(raw_content, list):
        # List content - can be:
        # - List of strings (text blocks)
        # - List of dicts with 'text' or 'content' fields (structured blocks)
        # - Empty list
        logger.info(f"[MISTRAL_RESPONSE {context}] LLM_CONTENT_SHAPE=list length={len(raw_content)}")
        
        if len(raw_content) == 0:
            # Empty list - no content
            logger.info(f"[MISTRAL_RESPONSE {context}] LLM_CONTENT_SHAPE=empty_list")
            return None
        
        # Analyze list item types
        item_types = [type(item).__name__ for item in raw_content]
        logger.info(f"[MISTRAL_RESPONSE {context}] item_types={item_types}")
        
        # Try to extract text from each item
        text_parts = []
        for idx, item in enumerate(raw_content):
            if isinstance(item, str):
                # String item - use directly
                text_parts.append(item)
            elif isinstance(item, dict):
                # Dict item - try to extract text from known fields
                # Mistral can return blocks like: {"type": "text", "text": "..."}
                if 'text' in item:
                    text_parts.append(item['text'])
                elif 'content' in item:
                    text_parts.append(item['content'])
                else:
                    # Log available keys for diagnostics
                    keys = list(item.keys())
                    logger.warning(
                        f"[MISTRAL_RESPONSE {context}] LLM_BLOCK_UNKNOWN_FIELDS item_index={idx} "
                        f"keys={keys}"
                    )
                    # Try to find any string value in the dict
                    for key, value in item.items():
                        if isinstance(value, str):
                            text_parts.append(value)
                            break
            else:
                # Unknown item type
                logger.warning(
                    f"[MISTRAL_RESPONSE {context}] LLM_BLOCK_UNKNOWN_TYPE item_index={idx} "
                    f"type={type(item).__name__}"
                )
        
        if text_parts:
            # Concatenate text parts with newlines to preserve ordering
            result = '\n'.join(text_parts)
            logger.info(f"[MISTRAL_RESPONSE {context}] LLM_NORMALIZED_TEXT_LENGTH={len(result)}")
            return result
        else:
            # No text could be extracted from list items
            logger.warning(f"[MISTRAL_RESPONSE {context}] LLM_NORMALIZATION_FAILED no_text_extracted")
            return None
    
    if isinstance(raw_content, dict):
        # Dict content - try to extract from known fields
        logger.info(f"[MISTRAL_RESPONSE {context}] LLM_CONTENT_SHAPE=dict")
        
        # Try common field names
        for field in ['content', 'text', 'message', 'response']:
            if field in raw_content:
                value = raw_content[field]
                logger.info(f"[MISTRAL_RESPONSE {context}] Found field={field} type={type(value).__name__}")
                # Recursively normalize the value
                return normalize_mistral_content(value, context=f"{context}.{field}")
        
        # No known fields - log available keys
        keys = list(raw_content.keys())
        logger.warning(f"[MISTRAL_RESPONSE {context}] LLM_DICT_UNKNOWN_FIELDS keys={keys}")
        
        # Try to find any string value
        for key, value in raw_content.items():
            if isinstance(value, str):
                return value
        
        return None
    
    # Unknown type - log and return None
    logger.warning(
        f"[MISTRAL_RESPONSE {context}] LLM_CONTENT_UNKNOWN_TYPE type={content_type} "
        f"repr={repr(raw_content)[:200]}"
    )
    return None


def extract_mistral_message_content(
    response_data: Dict[str, Any],
    context: str = "unknown",
) -> Optional[str]:
    """Extract and normalize content from a Mistral API response dict.
    
    This is a convenience function that extracts the message content from
    the standard Mistral API response structure and normalizes it.
    
    Args:
        response_data: The full JSON response from Mistral API
        context: Context string for logging
        
    Returns:
        Normalized string content, or None
    """
    # Extract choices from response
    choices = response_data.get("choices", [])
    
    if not isinstance(choices, list) or not choices:
        logger.warning(f"[MISTRAL_RESPONSE {context}] No choices in response")
        return None
    
    # Get first choice
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        logger.warning(
            f"[MISTRAL_RESPONSE {context}] First choice is not a dict: {type(first_choice).__name__}"
        )
        return None
    
    # Extract message
    message = first_choice.get("message", {})
    if not isinstance(message, dict):
        logger.warning(
            f"[MISTRAL_RESPONSE {context}] Message is not a dict: {type(message).__name__}"
        )
        return None
    
    # Extract content
    raw_content = message.get("content")
    
    # Normalize the content
    return normalize_mistral_content(raw_content, context=context)


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    "normalize_mistral_content",
    "extract_mistral_message_content",
]
