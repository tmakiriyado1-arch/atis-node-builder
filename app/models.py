"""
Pydantic models for API requests/responses
"""
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class EntityResolveRequest(BaseModel):
    """Request to resolve entity name."""
    text: str = Field(..., min_length=1, description="Text to resolve")
    entity_type: Optional[str] = Field(None, description="Optional entity type hint")
    context: Optional[str] = Field(None, description="Optional context")


class EntityResolveResponse(BaseModel):
    """Response from entity resolution."""
    state: str = Field(..., description="Resolution state")
    entity_id: Optional[str] = Field(None, description="Resolved entity ID")
    canonical_name: Optional[str] = Field(None, description="Canonical name")
    confidence: float = Field(..., description="Confidence (0-1)")
    reasoning: str = Field(..., description="Explanation")


class EntityCreateRequest(BaseModel):
    """Request to create entity."""
    canonical_name: str = Field(..., min_length=1, description="Authoritative name")
    entity_type: Optional[str] = Field(None, description="Entity type")
    acronyms: Optional[List[str]] = Field(None, description="Known acronyms")
    notes: Optional[str] = Field(None, description="Additional notes")


class EntityCreateResponse(BaseModel):
    """Response from entity creation."""
    entity_id: str
    canonical_name: str
    entity_type: Optional[str]
    acronyms: List[str]


class BuildJobRequest(BaseModel):
    """Request to build a node."""
    entity_name: str = Field(..., description="Entity to build")
    entity_type: Optional[str] = Field(None, description="Entity type")
    rita_id: Optional[str] = Field(None, description="RITA entity ID")


class BuildJobResponse(BaseModel):
    """Response with job ID."""
    job_id: str
    status: str = "QUEUED"
    entity_name: str


class SourceProvenance(BaseModel):
    """Traceability reference for a value or knowledge object."""

    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(..., min_length=1)
    source_type: Optional[str] = Field(None, min_length=1)
    source_uri: Optional[str] = Field(None, min_length=1)
    excerpt: Optional[str] = None
    collected_at: Optional[datetime] = None


class ValidationResult(BaseModel):
    """Deterministic validation report."""

    valid: bool
    errors: List[str] = Field(default_factory=list)


class ATISNode(BaseModel):
    """Validated generic node until the canonical ATIS field schema is supplied."""

    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(..., min_length=1)
    entity_id: str = Field(..., min_length=1)
    canonical_name: str = Field(..., min_length=1)
    entity_type: Optional[str] = Field(None, min_length=1)
    fields: Dict[str, Any] = Field(default_factory=dict)
    provenance: List[SourceProvenance] = Field(..., min_length=1)
    validation_status: str = "VALIDATED"

    @field_validator("fields")
    @classmethod
    def validate_field_names(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        if any(not isinstance(name, str) or not name.strip() for name in value):
            raise ValueError("field names must be non-empty strings")
        return value


class NodeRelationship(BaseModel):
    """An explicitly asserted, provenance-backed relationship."""

    model_config = ConfigDict(extra="forbid")

    relationship_id: Optional[str] = None
    source_node_id: str = Field(..., min_length=1)
    target_entity_id: str = Field(..., min_length=1)
    relationship_type: str = Field(..., min_length=1)
    provenance: List[SourceProvenance] = Field(..., min_length=1)


class NodeCreateRequest(BaseModel):
    """Request to build and store a validated node."""

    node_id: str = Field(..., min_length=1)
    entity_name: str = Field(..., min_length=1)
    fields: Dict[str, Any] = Field(default_factory=dict)
    source_id: str = Field(..., min_length=1)
    source_type: Optional[str] = Field(None, min_length=1)
    source_uri: Optional[str] = Field(None, min_length=1)
    excerpt: Optional[str] = None


class RelationshipCreateRequest(BaseModel):
    """Request to store an explicitly asserted relationship."""

    target_entity_id: str = Field(..., min_length=1)
    relationship_type: str = Field(..., min_length=1)
    provenance: List[SourceProvenance] = Field(..., min_length=1)
