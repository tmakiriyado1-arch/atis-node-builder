"""
API route dependencies
"""
from app.services.entity_resolution.registry import EntityRegistry
from app.services.entity_resolution.resolver import EntityResolver
from app.services.backlink import BacklinkGenerator
from app.services.queue_manager import EntityQueue
from app.services.node_store import NodeStore
from app.services.node_builder import NodeBuilder
from app.processor import NORAProcessor

# Global instances (TODO: move to proper DI container)
_registry = None
_resolver = None
_backlink_generator = None
_queue = None
_node_store = None
_node_builder = None
_processor = None


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


def get_node_store() -> NodeStore:
    """Get the process-local node store."""
    global _node_store
    if _node_store is None:
        _node_store = NodeStore(get_registry())
    return _node_store


def get_node_builder() -> NodeBuilder:
    """Get a node builder using the shared entity resolver."""
    global _node_builder
    if _node_builder is None:
        _node_builder = NodeBuilder(get_resolver())
    return _node_builder


def get_processor() -> NORAProcessor:
    """Get the shared NORA processing pipeline."""
    global _processor
    if _processor is None:
        _processor = NORAProcessor(
            registry=get_registry(),
            resolver=get_resolver(),
            queue=get_queue(),
            store=get_node_store(),
        )
    return _processor
