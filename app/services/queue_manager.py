"""
Queue management for discovered entities
"""
from typing import List, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from app.services.entity_resolution.normalizer import Normalizer


class QueueStatus(str, Enum):
    """Status of queued entity"""
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"
    ERROR = "ERROR"


@dataclass
class QueuedEntity:
    """Entity discovered during processing, queued for future work."""
    canonical_name: str
    entity_type: Optional[str] = None
    aliases: List[str] = field(default_factory=list)
    source_node: Optional[str] = None  # Entity that discovered this
    source_field: Optional[str] = None
    source_context: Optional[str] = None
    confidence: float = 1.0
    status: QueueStatus = QueueStatus.PENDING
    discovered_at: datetime = field(default_factory=datetime.now)
    processing_started_at: Optional[datetime] = None
    processing_completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    notes: str = ""

    def start_processing(self):
        """Mark entity as processing."""
        self.status = QueueStatus.PROCESSING
        self.processing_started_at = datetime.now()

    def mark_completed(self):
        """Mark entity as completed."""
        self.status = QueueStatus.COMPLETED
        self.processing_completed_at = datetime.now()

    def mark_error(self, error: str):
        """Mark entity with error."""
        self.status = QueueStatus.ERROR
        self.error_message = error
        self.processing_completed_at = datetime.now()

    def mark_skipped(self):
        """Mark entity as skipped."""
        self.status = QueueStatus.SKIPPED
        self.processing_completed_at = datetime.now()


class EntityQueue:
    """Queue of discovered entities for recursive processing."""

    def __init__(self):
        """Initialize queue."""
        self.items: List[QueuedEntity] = []
        self.canonical_index: Set[str] = set()  # Deduplication
        self.normalizer = Normalizer()

    def enqueue(
        self,
        canonical_name: str,
        entity_type: Optional[str] = None,
        aliases: Optional[List[str]] = None,
        source_node: Optional[str] = None,
        source_field: Optional[str] = None,
        source_context: Optional[str] = None,
        confidence: float = 1.0,
        notes: str = "",
    ) -> bool:
        """Add entity to queue if not duplicate.
        
        Args:
            canonical_name: Canonical entity name
            entity_type: Entity type hint
            aliases: Known aliases
            source_node: Entity that discovered this
            source_field: Field where discovered
            source_context: Context snippet
            confidence: Confidence level (0-1)
            notes: Additional notes
            
        Returns:
            True if added, False if duplicate
        """
        # Normalize for dedup check
        normalized = self.normalizer.normalize(canonical_name)
        
        if normalized in self.canonical_index:
            return False
        
        item = QueuedEntity(
            canonical_name=canonical_name,
            entity_type=entity_type,
            aliases=aliases or [],
            source_node=source_node,
            source_field=source_field,
            source_context=source_context,
            confidence=confidence,
            notes=notes,
        )
        
        self.items.append(item)
        self.canonical_index.add(normalized)
        return True

    def dequeue(self) -> Optional[QueuedEntity]:
        """Get next entity to process.
        
        Returns:
            Next pending entity or None
        """
        for item in self.items:
            if item.status == QueueStatus.PENDING:
                item.start_processing()
                return item
        return None

    def peek(self) -> Optional[QueuedEntity]:
        """Peek at next entity without dequeuing.
        
        Returns:
            Next pending entity or None
        """
        for item in self.items:
            if item.status == QueueStatus.PENDING:
                return item
        return None

    def list_pending(self) -> List[QueuedEntity]:
        """List all pending entities.
        
        Returns:
            List of pending QueuedEntity objects
        """
        return [item for item in self.items if item.status == QueueStatus.PENDING]

    def list_all(self) -> List[QueuedEntity]:
        """List all entities in queue.
        
        Returns:
            All QueuedEntity objects
        """
        return list(self.items)

    def count(self, status: Optional[QueueStatus] = None) -> int:
        """Count entities in queue.
        
        Args:
            status: Optional status filter
            
        Returns:
            Count of entities
        """
        if status is None:
            return len(self.items)
        return sum(1 for item in self.items if item.status == status)

    def clear(self):
        """Clear all items from queue."""
        self.items.clear()
        self.canonical_index.clear()
