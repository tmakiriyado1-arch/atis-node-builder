"""
API routes for entities
"""
from fastapi import APIRouter, Depends, HTTPException
from app.api.dependencies import get_registry, get_resolver
from app.models import EntityResolveRequest, EntityResolveResponse, EntityCreateRequest, EntityCreateResponse
from app.services.entity_resolution.registry import EntityRegistry
from app.services.entity_resolution.resolver import EntityResolver
from app.logging import logger

router = APIRouter(prefix="/entities", tags=["entities"])

@router.post("/resolve", response_model=EntityResolveResponse)
async def resolve_entity(
    request: EntityResolveRequest,
    resolver: EntityResolver = Depends(get_resolver),
) -> EntityResolveResponse:
    """Resolve entity name to canonical entity."""
    try:
        result = resolver.resolve(
            text=request.text,
            entity_type=request.entity_type,
            context=request.context,
        )
        return EntityResolveResponse(
            state=result.state.value,
            entity_id=result.entity_id,
            canonical_name=result.canonical_name,
            confidence=result.confidence,
            reasoning=result.reasoning,
        )
    except Exception as e:
        logger.error(f"Error resolving entity: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/create", response_model=EntityCreateResponse)
async def create_entity(
    request: EntityCreateRequest,
    registry: EntityRegistry = Depends(get_registry),
) -> EntityCreateResponse:
    """Create new canonical entity."""
    try:
        entity = registry.create_entity(
            canonical_name=request.canonical_name,
            entity_type=request.entity_type,
            acronyms=request.acronyms,
            notes=request.notes or "",
        )
        return EntityCreateResponse(
            entity_id=entity.entity_id,
            canonical_name=entity.canonical_name,
            entity_type=entity.entity_type,
            acronyms=entity.acronyms,
        )
    except Exception as e:
        logger.error(f"Error creating entity: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def entity_status(registry: EntityRegistry = Depends(get_registry)):
    """Get registry status."""
    return {
        "total_entities": registry.count(),
        "status": "ok",
    }
