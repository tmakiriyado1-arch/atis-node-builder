"""API routes for validated nodes and explicit relationships."""
from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_node_builder, get_node_store
from app.models import (
    ATISNode,
    NodeCreateRequest,
    NodeRelationship,
    RelationshipCreateRequest,
    ValidationResult,
)
from app.services.node_builder import NodeBuildError, NodeBuilder
from app.services.node_store import NodeStore, NodeStoreError

router = APIRouter(prefix="/nodes", tags=["nodes"])


@router.get("", response_model=list[ATISNode])
async def list_nodes(store: NodeStore = Depends(get_node_store)) -> list[ATISNode]:
    return list(store.nodes.values())


@router.post("", response_model=ATISNode, status_code=status.HTTP_201_CREATED)
async def create_node(
    request: NodeCreateRequest,
    builder: NodeBuilder = Depends(get_node_builder),
    store: NodeStore = Depends(get_node_store),
) -> ATISNode:
    try:
        node = builder.build(
            node_id=request.node_id,
            entity_text=request.entity_name,
            fields=request.fields,
            source_id=request.source_id,
            source_type=request.source_type,
            source_uri=request.source_uri,
            excerpt=request.excerpt,
        )
        return store.save(node)
    except NodeBuildError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error))
    except NodeStoreError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))


@router.get("/{node_id}", response_model=ATISNode)
async def get_node(node_id: str, store: NodeStore = Depends(get_node_store)) -> ATISNode:
    node = store.get(node_id)
    if node is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="node not found")
    return node


@router.get("/{node_id}/relationships", response_model=list[NodeRelationship])
async def get_relationships(
    node_id: str,
    store: NodeStore = Depends(get_node_store),
) -> list[NodeRelationship]:
    if store.get(node_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="node not found")
    return store.list_relationships(node_id)


@router.post("/{node_id}/relationships", response_model=NodeRelationship)
async def create_relationship(
    node_id: str,
    request: RelationshipCreateRequest,
    store: NodeStore = Depends(get_node_store),
) -> NodeRelationship:
    source = store.get(node_id)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="node not found")
    if source.entity_id == request.target_entity_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="self-relationships are not valid")
    try:
        return store.add_relationship(
            NodeRelationship(
                source_node_id=node_id,
                target_entity_id=request.target_entity_id,
                relationship_type=request.relationship_type,
                provenance=request.provenance,
            )
        )
    except NodeStoreError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))


@router.post("/{node_id}/validate", response_model=ValidationResult)
async def validate_node(node_id: str, store: NodeStore = Depends(get_node_store)) -> ValidationResult:
    node = store.get(node_id)
    if node is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="node not found")
    return ValidationResult(valid=True)