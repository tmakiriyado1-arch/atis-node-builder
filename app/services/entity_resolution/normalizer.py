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
        self.quote_pattern = re.compile(r'["“”]')
        self.apostrophe_pattern = re.compile(r"['’ʼ]")
        self.punctuation_pattern = re.compile(r"[.,;:!?]+$")
        self.acronym_pattern = re.compile(r"\b[A-Za-z]{2,5}\b")
        self.possessive_pattern = re.compile(r"(?:'|’|ʼ)s\b", re.IGNORECASE)

    def normalize(self, text: str) -> str:
        """Normalize entity name to canonical form.
        
        Args:
            text: Raw entity name
            
        Returns:
            Normalized canonical form (lowercase, whitespace-normalized, etc.)
        """
        if not text or not isinstance(text, str):
            return ""

        # Decode HTML entities before Unicode normalization so entity-decoded text
        # is normalized consistently with literal accented text.
        text = self._decode_html_entities(text)

        # Unicode normalization (decompose accents)
        text = unicodedata.normalize(self.UNICODE_FORM, text)

        # Normalize dashes to single hyphen
        text = self.dash_pattern.sub("-", text)

        # Remove outer quote wrappers without stripping the apostrophe from possessives.
        text = text.strip(" \"“”‘’'")
        text = self.quote_pattern.sub("", text)

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
        # Strip punctuation and bracketed acronyms so parenthetical forms compare
        # as their underlying names rather than as a different literal string.
        text = self.parenthetical_pattern.sub(" ", text)
        text = text.replace("-", " ")
        text = re.sub(r"[()\[\]{}<>/\\]+", " ", text)
        text = re.sub(r"[^a-z0-9\s]", " ", text)
        text = self.quote_pattern.sub("", text)
        text = self.apostrophe_pattern.sub("", text)
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
            normalized_match = match.strip()
            if re.fullmatch(r"[A-Z]{2,5}", normalized_match.upper()):
                return normalized_match.upper()

        # Look for standalone uppercase acronyms at word boundaries. Lowercase
        # inputs should be resolved against the registry as acronym candidates
        # rather than treated as arbitrary words.
        acronyms = self.acronym_pattern.findall(text)
        for acronym in acronyms:
            if acronym.isupper():
                return acronym.upper()

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
        if len(text) < 2 or len(text) > 5:
            return False
        return bool(re.fullmatch(r"[A-Z]{2,5}", text))

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
            acronym = self.extract_acronym(text)
            if acronym:
                remainder = self.normalize(text.replace(acronym, ""))
                return (remainder.strip(), acronym)
            normalized = self.normalize(text)
            generated = self.generate_acronym(normalized)
            return normalized, generated

        # Detect prefix acronym form like "ZERA (Full Name)" before evaluating
        # the parenthetical content itself.
        prefix_match = re.match(r"^\s*([A-Za-z]{2,5})\s*\((.+)\)\s*$", text, flags=re.IGNORECASE)
        if prefix_match:
            acronym = prefix_match.group(1).upper()
            name = self.normalize(prefix_match.group(2))
            return name, acronym

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

        # Prefix acronym form like "ZERA (Full Name)" leaves the acronym as the
        # remaining text after parenthetical removal, so use the parenthetical body
        # for the actual canonical name in that case.
        if acronym and name and name.lower() == acronym.lower():
            name = self.normalize(parentheticals[0])

        # If acronym not found in parentheticals, try to extract or generate
        if not acronym:
            acronym = self.extract_acronym(text)
            if not acronym:
                acronym = self.generate_acronym(name)

        return name, acronym
