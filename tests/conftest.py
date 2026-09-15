"""
Test configuration and fixtures
"""
import pytest
from app.services.entity_resolution.normalizer import Normalizer
from app.services.entity_resolution.registry import EntityRegistry
from app.services.entity_resolution.resolver import EntityResolver


@pytest.fixture
def normalizer():
    """Provide a Normalizer instance"""
    return Normalizer()


@pytest.fixture
def registry():
    """Provide a fresh EntityRegistry instance"""
    return EntityRegistry()


@pytest.fixture
def resolver(registry):
    """Provide an EntityResolver with test registry"""
    return EntityResolver(registry, fuzzy_threshold=0.85)


@pytest.fixture
def zera_entity(registry):
    """Create canonical ZERA entity for testing"""
    entity = registry.create_entity(
        canonical_name="Zimbabwe Energy Regulatory Authority",
        entity_type="government_entity",
        acronyms=["ZERA"],
        notes="Energy regulator for Zimbabwe",
    )
    return entity
