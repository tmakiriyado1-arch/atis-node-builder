"""Frontend-oriented API adapter around the existing NORA pipeline."""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.services.pipeline import EntityPipelineService, PipelineResult
from app.services.rita_intake import RITAIntakeService

router = APIRouter(prefix="/api", tags=["frontend"])

RUN_STORE: dict[str, dict[str, Any]] = {}


class RunCreateRequest(BaseModel):
    entity_id: str = Field(..., min_length=1, description="Existing RITA entity identifier")


class RunDetailResponse(BaseModel):
    run_id: str
    entity_id: str
    status: str
    backend_status: Optional[str] = None
    created_at: str
    updated_at: str
    stage_status: dict[str, str] = Field(default_factory=dict)
    error: Optional[dict[str, Any]] = None
    entity: Optional[dict[str, Any]] = None


class RunResultResponse(BaseModel):
    run_id: str
    entity_id: str
    status: str
    backend_status: Optional[str] = None
    created_at: str
    updated_at: str
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    claims: list[dict[str, Any]] = Field(default_factory=list)
    resolution: Optional[dict[str, Any]] = None
    classifications: dict[str, list[str]] = Field(default_factory=dict)
    node_draft: Optional[dict[str, Any]] = None
    canonical_row: Optional[dict[str, Any]] = None
    import_bundle: Optional[dict[str, Any]] = None
    error: Optional[dict[str, Any]] = None
    stage_status: dict[str, str] = Field(default_factory=dict)


def _empty_stage_status() -> dict[str, str]:
    return {
        "research": "pending",
        "evidence": "pending",
        "enrichment": "pending",
        "entity_resolution": "pending",
        "claim_classification": "pending",
        "node_draft": "pending",
        "canonical_row": "pending",
        "import_bundle": "pending",
    }


def _build_error(code: str, message: str, stage: Optional[str] = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": code, "message": message}
    if stage:
        payload["stage"] = stage
    return {"error": payload}


def _public_status(backend_status: Optional[str]) -> str:
    if not backend_status:
        return "idle"
    normalized = str(backend_status).strip().lower()
    if normalized in {"completed", "complete"}:
        return "complete"
    if normalized == "running":
        return "running"
    if normalized in {"failed", "error", "insufficient"}:
        return "failed"
    if normalized in {"ambiguous", "needs_review", "pending"}:
        return "needs_review"
    return "idle"


def _entity_summary(entity: Any) -> dict[str, Any]:
    if entity is None:
        return {}
    return {
        "entity_id": getattr(entity, "entity_id", None),
        "name": getattr(entity, "name", None),
        "rita_type": getattr(entity, "rita_type", None),
        "aliases": list(getattr(entity, "aliases", []) or []),
        "metadata": dict(getattr(entity, "metadata", {}) or {}),
        "source_count": getattr(entity, "source_count", 0),
        "extracted_at": getattr(entity, "extracted_at", None),
        "extraction_run_id": getattr(entity, "extraction_run_id", None),
        "ingestion_status": getattr(entity, "ingestion_status", None),
    }


def _normalize_json(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "dict"):
        return value.dict()
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return {key: _normalize_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_json(item) for item in value]
    if isinstance(value, tuple):
        return [_normalize_json(item) for item in value]
    if isinstance(value, set):
        return [_normalize_json(item) for item in sorted(value)]
    return value


def _stage_status_from_result(result: Optional[PipelineResult]) -> dict[str, str]:
    if result is None:
        return _empty_stage_status()
    stage_status = _empty_stage_status()
    stage_status["research"] = "complete" if getattr(result, "evidence", None) else "pending"
    stage_status["evidence"] = "complete" if getattr(result, "evidence", None) else "pending"
    stage_status["enrichment"] = "complete" if getattr(result, "claims", None) else "pending"
    stage_status["entity_resolution"] = "complete" if getattr(result, "resolution", None) else "pending"
    stage_status["claim_classification"] = "complete" if getattr(result, "classifications", None) else "pending"
    stage_status["node_draft"] = "complete" if getattr(result, "node_draft", None) else "pending"
    stage_status["canonical_row"] = "complete" if getattr(result, "canonical_row", None) else "pending"
    stage_status["import_bundle"] = "complete" if getattr(result, "import_bundle", None) else "pending"

    if result.error_message:
        for key in ["research", "evidence", "enrichment", "entity_resolution", "claim_classification", "node_draft", "canonical_row", "import_bundle"]:
            if stage_status.get(key) == "complete":
                continue
            stage_status[key] = "failed"
    return stage_status


def _result_payload(result: Optional[PipelineResult]) -> dict[str, Any]:
    if result is None:
        return {}
    bundle = getattr(result, "import_bundle", None)
    payload: dict[str, Any] = {
        "entity": _normalize_json(getattr(result, "entity", None)),
        "evidence": _normalize_json(getattr(result, "evidence", []) or []),
        "claims": _normalize_json(getattr(result, "claims", []) or []),
        "resolution": _normalize_json(getattr(result, "resolution", None)),
        "classification": _normalize_json(getattr(result, "classifications", {}) or {}),
        "classifications": _normalize_json(getattr(result, "classifications", {}) or {}),
        "node_draft": _normalize_json(getattr(result, "node_draft", None)),
        "canonical_row": _normalize_json(getattr(result, "canonical_row", None)),
        "import_bundle": _normalize_json(bundle) if bundle is not None else None,
        "status": getattr(result, "status", None),
        "error": _normalize_json(getattr(result, "error_message", None)),
    }
    return payload


async def _execute_pipeline_run(run_id: str) -> None:
    record = RUN_STORE.get(run_id)
    if record is None:
        return

    try:
        entity = RITAIntakeService().get_entity_by_id(record["entity_id"])
    except Exception as exc:  # pragma: no cover - depends on configured intake source
        record["backend_status"] = "failed"
        record["status"] = "failed"
        record["error"] = _build_error("ENTITY_NOT_FOUND", str(exc), "entity_lookup")
        record["updated_at"] = datetime.utcnow().isoformat()
        return

    try:
        result = await EntityPipelineService().run(entity)
    except Exception as exc:
        record["backend_status"] = "failed"
        record["status"] = "failed"
        record["error"] = _build_error("PIPELINE_FAILED", str(exc), "pipeline")
        record["updated_at"] = datetime.utcnow().isoformat()
        return

    record["entity"] = _entity_summary(entity)
    record["result"] = _result_payload(result)
    record["backend_status"] = getattr(result, "status", "failed")
    record["status"] = _public_status(getattr(result, "status", "failed"))
    record["stage_status"] = _stage_status_from_result(result)
    record["error"] = _build_error("PIPELINE_FAILED", result.error_message, "pipeline") if result.error_message else None
    record["updated_at"] = datetime.utcnow().isoformat()


@router.get("/entities")
async def list_ruta_entities() -> dict[str, Any]:
    """Return the available RITA entities as supported by the repository intake layer."""
    try:
        entities = RITAIntakeService().get_entities()
    except Exception:
        entities = []

    serialized = [_entity_summary(entity) for entity in entities]
    return {"entities": serialized, "items": serialized, "count": len(serialized)}


@router.post("/runs", response_model=RunDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_run(request: RunCreateRequest) -> dict[str, Any]:
    """Start the existing NORA pipeline for a single RITA entity and return a polling handle."""
    try:
        entity = RITAIntakeService().get_entity_by_id(request.entity_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_build_error("ENTITY_NOT_FOUND", f"RITA entity '{request.entity_id}' was not found.", "entity_lookup"),
        ) from exc

    run_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    record = {
        "run_id": run_id,
        "entity_id": request.entity_id,
        "entity": _entity_summary(entity),
        "status": "running",
        "backend_status": "running",
        "created_at": now,
        "updated_at": now,
        "stage_status": _empty_stage_status(),
        "error": None,
        "result": None,
    }
    RUN_STORE[run_id] = record
    asyncio.create_task(_execute_pipeline_run(run_id))
    return record


@router.get("/runs/{run_id}", response_model=RunDetailResponse)
async def get_run(run_id: str) -> dict[str, Any]:
    record = RUN_STORE.get(run_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_build_error("RUN_NOT_FOUND", f"Run '{run_id}' was not found.", "run_lookup"),
        )
    return record


@router.get("/runs/{run_id}/result", response_model=RunResultResponse)
async def get_run_result(run_id: str) -> dict[str, Any]:
    record = RUN_STORE.get(run_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_build_error("RUN_NOT_FOUND", f"Run '{run_id}' was not found.", "run_lookup"),
        )
    if record.get("result") is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_build_error("RUN_NOT_COMPLETE", f"Run '{run_id}' has not finished processing yet.", "pipeline"),
        )

    payload = {
        "run_id": record["run_id"],
        "entity_id": record["entity_id"],
        "status": record["status"],
        "backend_status": record.get("backend_status"),
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
        "evidence": record["result"].get("evidence", []),
        "claims": record["result"].get("claims", []),
        "resolution": record["result"].get("resolution"),
        "classifications": record["result"].get("classifications", {}),
        "node_draft": record["result"].get("node_draft"),
        "canonical_row": record["result"].get("canonical_row"),
        "import_bundle": record["result"].get("import_bundle"),
        "error": record.get("error"),
        "stage_status": record.get("stage_status", _empty_stage_status()),
    }
    return payload


@router.get("/runs/{run_id}/evidence")
async def get_run_evidence(run_id: str) -> dict[str, Any]:
    record = RUN_STORE.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail=_build_error("RUN_NOT_FOUND", f"Run '{run_id}' was not found.", "run_lookup"))
    if record.get("result") is None:
        raise HTTPException(status_code=409, detail=_build_error("RUN_NOT_COMPLETE", f"Run '{run_id}' has not finished processing yet.", "pipeline"))
    return {"run_id": run_id, "evidence": record["result"].get("evidence", [])}


@router.get("/runs/{run_id}/claims")
async def get_run_claims(run_id: str) -> dict[str, Any]:
    record = RUN_STORE.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail=_build_error("RUN_NOT_FOUND", f"Run '{run_id}' was not found.", "run_lookup"))
    if record.get("result") is None:
        raise HTTPException(status_code=409, detail=_build_error("RUN_NOT_COMPLETE", f"Run '{run_id}' has not finished processing yet.", "pipeline"))
    return {"run_id": run_id, "claims": record["result"].get("claims", [])}


@router.get("/runs/{run_id}/classification")
async def get_run_classification(run_id: str) -> dict[str, Any]:
    record = RUN_STORE.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail=_build_error("RUN_NOT_FOUND", f"Run '{run_id}' was not found.", "run_lookup"))
    if record.get("result") is None:
        raise HTTPException(status_code=409, detail=_build_error("RUN_NOT_COMPLETE", f"Run '{run_id}' has not finished processing yet.", "pipeline"))
    return {"run_id": run_id, "classifications": record["result"].get("classifications", {})}


@router.get("/runs/{run_id}/bundle")
async def get_run_bundle(run_id: str) -> dict[str, Any]:
    record = RUN_STORE.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail=_build_error("RUN_NOT_FOUND", f"Run '{run_id}' was not found.", "run_lookup"))
    if record.get("result") is None:
        raise HTTPException(status_code=409, detail=_build_error("RUN_NOT_COMPLETE", f"Run '{run_id}' has not finished processing yet.", "pipeline"))
    return {"run_id": run_id, "import_bundle": record["result"].get("import_bundle")}
