"""
Tests for entity registry operations
"""
import pytest
from app.services.entity_resolution.registry import EntityRegistry, ResolutionState


class TestEntityCreation:
    """Test entity creation and registration"""

    def test_create_entity(self, registry):
        """Test creating a new entity"""
        entity = registry.create_entity(
            canonical_name="Test Organization",
            entity_type="organization",
            acronyms=["TO"],
            notes="Test entity",
        )
        
        assert entity.entity_id == "ENTITY-000001"
        assert entity.canonical_name == "Test Organization"
        assert entity.entity_type == "organization"
        assert "TO" in entity.acronyms
        assert entity.notes == "Test entity"

    def test_entity_ids_are_sequential(self, registry):
        """Test that entity IDs are assigned sequentially"""
        entity1 = registry.create_entity("Entity 1")
        entity2 = registry.create_entity("Entity 2")
        entity3 = registry.create_entity("Entity 3")
        
        assert entity1.entity_id == "ENTITY-000001"
        assert entity2.entity_id == "ENTITY-000002"
        assert entity3.entity_id == "ENTITY-000003"

    def test_entity_ids_are_stable(self, registry):
        """Test that entity IDs don't change"""
        entity = registry.create_entity("Test")
        original_id = entity.entity_id
        
        # Retrieve and verify ID unchanged
        retrieved = registry.get_entity(entity.entity_id)
        assert retrieved.entity_id == original_id


class TestEntityRetrieval:
    """Test entity lookup operations"""

    def test_get_entity_by_id(self, registry):
        """Test retrieving entity by ID"""
        entity = registry.create_entity("Test Entity")
        retrieved = registry.get_entity(entity.entity_id)
        
        assert retrieved is not None
        assert retrieved.canonical_name == "Test Entity"

    def test_get_nonexistent_entity(self, registry):
        """Test retrieving nonexistent entity returns None"""
        result = registry.get_entity("ENTITY-999999")
        assert result is None

    def test_find_by_normalized_name(self, registry):
        """Test finding entity by normalized name"""
        entity = registry.create_entity("Zimbabwe Energy Regulatory Authority")
        
        entity_id = registry.find_by_normalized("zimbabwe energy regulatory authority")
        assert entity_id == entity.entity_id

    def test_find_by_acronym(self, registry):
        """Test finding entity by acronym"""
        entity = registry.create_entity(
            "Zimbabwe Energy Regulatory Authority",
            acronyms=["ZERA"],
        )
        
        entity_ids = registry.find_by_acronym("ZERA")
        assert entity_ids is not None
        assert entity.entity_id in entity_ids


class TestAliasManagement:
    """Test alias registration and lookup"""

    def test_add_alias_to_entity(self, registry):
        """Test adding alias to existing entity"""
        entity = registry.create_entity("Test Entity")
        
        success = registry.add_alias_to_entity(
            entity.entity_id,
            "Alternative Name",
            "alternative name",
            "test_source",
            confidence=0.95,
        )
        
        assert success is True
        assert len(entity.aliases) == 1
        assert entity.aliases[0].text == "Alternative Name"

    def test_find_by_alias(self, registry):
        """Test finding entity by alias"""
        entity = registry.create_entity("Primary Name")
        
        registry.add_alias_to_entity(
            entity.entity_id,
            "Secondary Name",
            "secondary name",
            "source",
        )
        
        found_id = registry.find_by_normalized("secondary name")
        assert found_id == entity.entity_id

    def test_add_alias_to_nonexistent_entity(self, registry):
        """Test adding alias to nonexistent entity returns False"""
        success = registry.add_alias_to_entity(
            "ENTITY-999999",
            "Alias",
            "alias",
            "source",
        )
        assert success is False


class TestAcronymManagement:
    """Test acronym registration and lookup"""

    def test_add_acronym_to_entity(self, registry):
        """Test adding acronym to entity"""
        entity = registry.create_entity(
            "Zimbabwe Energy Regulatory Authority",
            acronyms=[],
        )
        
        success = registry.add_acronym_to_entity(entity.entity_id, "ZERA")
        assert success is True
        assert "ZERA" in entity.acronyms

    def test_find_by_acronym_multiple_entities(self, registry):
        """Test finding multiple entities by same acronym"""
        entity1 = registry.create_entity(
            "International Development Association",
            acronyms=["IDA"],
        )
        entity2 = registry.create_entity(
            "Integrated Data Authority",
            acronyms=["IDA"],
        )
        
        entities = registry.find_by_acronym("IDA")
        assert len(entities) == 2
        assert entity1.entity_id in entities
        assert entity2.entity_id in entities

    def test_add_duplicate_acronym_not_repeated(self, registry):
        """Test that duplicate acronyms are not repeated"""
        entity = registry.create_entity(
            "Test Entity",
            acronyms=["TE"],
        )
        
        registry.add_acronym_to_entity(entity.entity_id, "TE")
        
        # Should still have only 1 acronym
        assert len(entity.acronyms) == 1


class TestRegistryStats:
    """Test registry statistics and listing"""

    def test_count_entities(self, registry):
        """Test entity count"""
        assert registry.count() == 0
        
        registry.create_entity("Entity 1")
        assert registry.count() == 1
        
        registry.create_entity("Entity 2")
        assert registry.count() == 2

    def test_list_all_entities(self, registry):
        """Test listing all entities"""
        entity1 = registry.create_entity("Entity 1")
        entity2 = registry.create_entity("Entity 2")
        
        all_entities = registry.list_all()
        assert len(all_entities) == 2
        assert entity1 in all_entities
        assert entity2 in all_entities
