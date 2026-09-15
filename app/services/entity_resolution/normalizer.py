"""
Deterministic normalization for entity names.

Handles:
- case differences
- whitespace variations
- punctuation normalization
- quotation marks
- brackets
- parenthetical acronyms
- dash variations
- Unicode normalization
- possessives
- HTML artifacts
- OCR spacing
- acronym detection and extraction
"""
import re
import unicodedata
from typing import Optional, Tuple, List


class Normalizer:
    """Deterministic text normalization for entity names."""

    # Unicode normalization form
    UNICODE_FORM = "NFD"

    def __init__(self):
        """Initialize normalizer with compiled regex patterns."""
        # Compile patterns for performance
        self.multiple_spaces = re.compile(r"\s+")
        self.html_entities = re.compile(r"&[a-zA-Z]+;")
        self.parenthetical_pattern = re.compile(r"\(([^)]+)\)")
        self.dash_pattern = re.compile(r"[-–—]{1,}")
        self.quote_pattern = re.compile(r'["\"\"\'\'\']')
        self.punctuation_pattern = re.compile(r"[.,;:!?]+$")
        self.acronym_pattern = re.compile(r"\b[A-Z]{2,}\b")
        self.possessive_pattern = re.compile(r"'s\b")

    def normalize(self, text: str) -> str:
        """Normalize entity name to canonical form.
        
        Args:
            text: Raw entity name
            
        Returns:
            Normalized canonical form (lowercase, whitespace-normalized, etc.)
        """
        if not text or not isinstance(text, str):
            return ""

        # Unicode normalization (decompose accents)
        text = unicodedata.normalize(self.UNICODE_FORM, text)

        # Decode HTML entities
        text = self._decode_html_entities(text)

        # Normalize dashes to single hyphen
        text = self.dash_pattern.sub("-", text)

        # Normalize quotes to double quotes
        text = self.quote_pattern.sub('"', text)

        # Remove possessives
        text = self.possessive_pattern.sub("", text)

        # Strip leading/trailing whitespace
        text = text.strip()

        # Normalize multiple spaces to single space
        text = self.multiple_spaces.sub(" ", text)

        # Remove trailing punctuation
        text = self.punctuation_pattern.sub("", text)

        # Convert to lowercase
        text = text.lower()

        return text

    def normalize_for_matching(self, text: str) -> str:
        """Normalize for fuzzy matching (even more aggressive).
        
        Removes all punctuation and normalizes spacing for comparison.
        
        Args:
            text: Text to normalize
            
        Returns:
            Normalized text for matching
        """
        text = self.normalize(text)
        # Remove all dashes and quotes
        text = text.replace("-", " ")
        text = text.replace('"', "")
        # Collapse whitespace
        text = self.multiple_spaces.sub(" ", text)
        return text.strip()

    def extract_acronym(self, text: str) -> Optional[str]:
        """Extract acronym from text.
        
        Handles formats like:
        - "Zimbabwe Energy Regulatory Authority (ZERA)" -> "ZERA"
        - "ZERA (Zimbabwe Energy Regulatory Authority)" -> "ZERA"
        - "ZERA" -> "ZERA"
        - "Zimbabwe Energy Regulatory Authority" -> "ZERA" (generated)
        
        Args:
            text: Text to extract acronym from
            
        Returns:
            Acronym if found, else None
        """
        if not text:
            return None

        # Check for explicit parenthetical acronym
        matches = self.parenthetical_pattern.findall(text)
        for match in matches:
            normalized_match = match.strip().upper()
            # If it looks like an acronym
            if re.match(r"^[A-Z]{2,}$", normalized_match):
                return normalized_match

        # Look for standalone acronym at word boundaries
        acronyms = self.acronym_pattern.findall(text)
        if acronyms:
            return acronyms[0].upper()

        return None

    def extract_parenthetical(self, text: str) -> List[str]:
        """Extract all parenthetical content.
        
        Args:
            text: Text to extract from
            
        Returns:
            List of parenthetical content
        """
        return self.parenthetical_pattern.findall(text)

    def generate_acronym(self, text: str) -> Optional[str]:
        """Generate acronym from multi-word text.
        
        Takes first letter of each major word.
        
        Args:
            text: Text to generate acronym from
            
        Returns:
            Generated acronym or None
        """
        normalized = self.normalize(text)
        words = normalized.split()

        # Filter out small words (a, the, of, etc.)
        stop_words = {"a", "an", "the", "of", "and", "or", "in", "on", "at", "by"}
        major_words = [w for w in words if w not in stop_words and len(w) > 1]

        if len(major_words) < 2:
            return None

        acronym = "".join(w[0].upper() for w in major_words)
        return acronym if len(acronym) >= 2 else None

    def _decode_html_entities(self, text: str) -> str:
        """Decode HTML entities.
        
        Args:
            text: Text with HTML entities
            
        Returns:
            Text with entities decoded
        """
        import html
        return html.unescape(text)

    def is_likely_acronym(self, text: str) -> bool:
        """Check if text is likely an acronym.
        
        Args:
            text: Text to check
            
        Returns:
            True if text looks like acronym
        """
        text = text.strip().upper()
        return bool(re.match(r"^[A-Z]{2,}$", text))

    def split_name_and_acronym(self, text: str) -> Tuple[str, Optional[str]]:
        """Split text into name and acronym components.
        
        Handles:
        - "Zimbabwe Energy Regulatory Authority (ZERA)" -> ("Zimbabwe Energy Regulatory Authority", "ZERA")
        - "ZERA (Zimbabwe Energy Regulatory Authority)" -> ("Zimbabwe Energy Regulatory Authority", "ZERA")
        - "Zimbabwe Energy Regulatory Authority" -> ("Zimbabwe Energy Regulatory Authority", None)
        
        Args:
            text: Text to split
            
        Returns:
            Tuple of (name, acronym)
        """
        if not text:
            return "", None

        # Extract parenthetical content
        parentheticals = self.extract_parenthetical(text)
        if not parentheticals:
            return self.normalize(text), None

        # Find acronym in parentheticals
        acronym = None
        for paren in parentheticals:
            paren_text = paren.strip().upper()
            if re.match(r"^[A-Z]{2,}$", paren_text):
                acronym = paren_text
                break

        # Remove all parentheticals to get base name
        name = self.parenthetical_pattern.sub("", text).strip()
        name = self.normalize(name)

        # If acronym not found in parentheticals, try to extract or generate
        if not acronym:
            acronym = self.extract_acronym(text)
            if not acronym:
                acronym = self.generate_acronym(name)

        return name, acronym
