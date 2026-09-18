"""
Backlink Engine - Entity mention extraction from prose
"""
import re
from typing import List, Set, Tuple
from app.services.entity_resolution.normalizer import Normalizer
from app.services.queue_manager import EntityQueue


class EntityMentionExtractor:
    """Extract potential entity mentions from text."""

    def __init__(self):
        """Initialize extractor with patterns."""
        self.normalizer = Normalizer()
        # Pattern for wikilinks
        self.wikilink_pattern = re.compile(r"\[\[([^\]]+)\]\]")
        # Pattern for capitalized phrases (potential entities)
        self.capitalized_pattern = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b")
        # Pattern for acronyms
        self.acronym_pattern = re.compile(r"\b[A-Z]{2,}\b")

    def extract_mentions(
        self,
        text: str,
        entity_type_hint: str = None,
    ) -> List[Tuple[str, str, int, int]]:
        """Extract entity mentions from text.
        
        Args:
            text: Source text
            entity_type_hint: Optional entity type hint
            
        Returns:
            List of (mention_text, normalized, start_pos, end_pos)
        """
        if not text:
            return []

        mentions = []

        # Extract existing wikilinks
        for match in self.wikilink_pattern.finditer(text):
            mention = match.group(1).strip()
            normalized = self.normalizer.normalize(mention)
            mentions.append((mention, normalized, match.start(), match.end()))

        # Extract capitalized phrases (potential entity mentions)
        for match in self.capitalized_pattern.finditer(text):
            mention = match.group(1)
            # Skip common non-entity words
            if self._is_entity_candidate(mention):
                normalized = self.normalizer.normalize(mention)
                mentions.append((mention, normalized, match.start(), match.end()))

        # Extract acronyms
        for match in self.acronym_pattern.finditer(text):
            acronym = match.group(0)
            if len(acronym) >= 2:
                mentions.append((acronym, acronym.lower(), match.start(), match.end()))

        # Remove duplicates, keeping first occurrence
        seen = set()
        unique = []
        for mention in mentions:
            key = mention[1]  # normalized form
            if key not in seen:
                seen.add(key)
                unique.append(mention)

        return unique

    def _is_entity_candidate(self, text: str) -> bool:
        """Check if text is likely an entity mention.
        
        Filters out common non-entity words.
        """
        skip_words = {
            "The", "A", "An", "And", "Or", "But", "In", "On", "At",
            "By", "For", "Of", "To", "With", "Is", "Are", "Was", "Were",
            "Been", "Be", "Have", "Has", "Had", "Do", "Does", "Did",
        }
        return text not in skip_words and len(text) > 2

    def extract_and_backlink(
        self,
        text: str,
        resolver,  # EntityResolver instance
    ) -> Tuple[str, List[Tuple[str, str, float]]]:
        """Extract mentions and generate backlinks.
        
        Args:
            text: Source text
            resolver: EntityResolver to resolve mentions
            
        Returns:
            (backlinked_text, resolved_entities)
        """
        mentions = self.extract_mentions(text)
        resolved = []
        backlinked = text
        offset = 0

        for mention_text, normalized, start, end in mentions:
            # Skip if already a wikilink
            if backlinked[start + offset:end + offset].startswith("[["):
                continue

            # Resolve mention
            result = resolver.resolve(mention_text)

            if result.state.value == "RESOLVED":
                # Create backlink
                backlink = f"[[{result.canonical_name}]]"
                old_text = backlinked[start + offset:end + offset]
                backlinked = backlinked[:start + offset] + backlink + backlinked[end + offset:]
                offset += len(backlink) - len(old_text)
                resolved.append((
                    mention_text,
                    result.canonical_name,
                    result.confidence,
                ))

        return backlinked, resolved


class BacklinkGenerator:
    """Generate backlinks for entity-bearing fields and prose."""

    def __init__(self, resolver, queue: EntityQueue = None):
        """Initialize with resolver.
        
        Args:
            resolver: EntityResolver instance
        """
        self.resolver = resolver
        self.queue = queue
        self.extractor = EntityMentionExtractor()
        self.normalizer = Normalizer()

    def backlink_field(
        self,
        value,  # str or List[str]
        field_name: str = None,
        source_node: str = None,
        source_context: str = None,
    ) -> str:
        """Generate backlinks for a field value.
        
        Args:
            value: Field value (string or list)
            field_name: Optional field name for context
            
        Returns:
            Backlinked value
        """
        if isinstance(value, list):
            return self._backlink_list(value, field_name, source_node, source_context)
        elif isinstance(value, str):
            return self._backlink_string(value, field_name, source_node, source_context)
        else:
            return str(value)

    def _backlink_string(self, text: str, field_name=None, source_node=None, source_context=None) -> str:
        """Generate backlinks for a string.
        
        Args:
            text: Text to backlink
            
        Returns:
            Text with backlinks
        """
        if not text:
            return text

        # Split by semicolon or comma (entity separators)
        entities = re.split(r"[;,]", text)
        backlinked = []

        for entity_text in entities:
            entity_text = entity_text.strip()
            if not entity_text:
                continue

            # Resolve entity
            result = self.resolver.resolve(entity_text)

            if result.state.value == "RESOLVED":
                backlinked.append(f"[[{result.canonical_name}]]")
            else:
                # Keep original if unresolved
                self._queue_unresolved(entity_text, source_node, field_name, source_context)
                backlinked.append(entity_text)

        return " ".join(backlinked)

    def _backlink_list(self, items: List[str], field_name=None, source_node=None, source_context=None) -> str:
        """Generate backlinks for a list of entities.
        
        Args:
            items: List of entity names
            
        Returns:
            Comma-separated backlinked entities
        """
        backlinked = []
        seen = set()

        for item in items:
            item = item.strip()
            if not item:
                continue

            # Resolve
            result = self.resolver.resolve(item)

            # Deduplicate on canonical name
            if result.state.value == "RESOLVED":
                canonical = result.canonical_name
                if canonical not in seen:
                    backlinked.append(f"[[{canonical}]]")
                    seen.add(canonical)
            else:
                # Keep unresolved, deduplicate on normalized
                normalized = self.normalizer.normalize(item)
                if normalized not in seen:
                    self._queue_unresolved(item, source_node, field_name, source_context)
                    backlinked.append(item)
                    seen.add(normalized)

        return ", ".join(backlinked)

    def backlink_summary(
        self,
        summary: str,
        source_node: str = None,
        source_field: str = None,
    ) -> Tuple[str, List[Tuple[str, str, float]]]:
        """Generate backlinks for summary text.
        
        Args:
            summary: Summary text with entity mentions
            
        Returns:
            (backlinked_summary, resolved_entities)
        """
        result = self.extractor.extract_and_backlink(summary, self.resolver)
        if self.queue is not None:
            for mention_text, _, start, end in self.extractor.extract_mentions(summary):
                resolution = self.resolver.resolve(mention_text)
                if resolution.state.value == "NEW_ENTITY":
                    self._queue_unresolved(
                        mention_text,
                        source_node,
                        source_field,
                        summary[max(0, start - 80):min(len(summary), end + 80)],
                    )
        return result

    def _queue_unresolved(self, name, source_node, source_field, source_context):
        if self.queue is not None:
            self.queue.enqueue(
                canonical_name=name,
                source_node=source_node,
                source_field=source_field,
                source_context=source_context,
            )
