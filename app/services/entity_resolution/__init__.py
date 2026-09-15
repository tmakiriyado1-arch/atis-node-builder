"""
Entity Resolution subsystem
"""
from app.services.entity_resolution.normalizer import Normalizer
from app.services.entity_resolution.resolver import EntityResolver
from app.services.entity_resolution.registry import EntityRegistry

__all__ = ["Normalizer", "EntityResolver", "EntityRegistry"]
