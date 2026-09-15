"""
API route dependencies
"""
from app.services.entity_resolution.registry import EntityRegistry
from app.services.entity_resolution.resolver import EntityResolver
from app.services.backlink import BacklinkGenerator
from app.services.queue_manager import EntityQueue

# Global instances (TODO: move to proper DI container)
_registry = None
_resolver = None
_backlink_generator = None
_queue = None


def get_registry() -> EntityRegistry:
    """Get or create registry."""
    global _registry
    if _registry is None:
        _registry = EntityRegistry()
    return _registry


def get_resolver() -> EntityResolver:
    """Get or create resolver."""
    global _resolver
    if _resolver is None:
        _resolver = EntityResolver(get_registry())
    return _resolver


def get_backlink_generator() -> BacklinkGenerator:
    """Get or create backlink generator."""
    global _backlink_generator
    if _backlink_generator is None:
        _backlink_generator = BacklinkGenerator(get_resolver())
    return _backlink_generator


def get_queue() -> EntityQueue:
    """Get or create entity queue."""
    global _queue
    if _queue is None:
        _queue = EntityQueue()
    return _queue
