"""
Pydantic models for API requests/responses
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from app.services.entity_resolution.registry import ResolutionState


class EntityResolveRequest(BaseModel):
    """Request to resolve entity name."""
    text: str = Field(..., description="Text to resolve")
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
    canonical_name: str = Field(..., description="Authoritative name")
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
