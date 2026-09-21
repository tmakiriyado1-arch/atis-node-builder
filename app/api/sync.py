"""API endpoint to manually trigger RITA entity sync from Google Sheets."""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.logging import logger
from app.services.rita_intake import RITAIntakeService

router = APIRouter(prefix="/api/sync", tags=["sync"])


class SyncStatusResponse(BaseModel):
    """Response for sync status and results."""
    status: str = Field(..., description="Sync operation status")
    message: str = Field(default="", description="Status message")
    entity_count: int = Field(default=0, description="Number of entities synced")
    file_path: str = Field(default="", description="Path to the synced file")
    file_exists: bool = Field(default=False, description="Whether the file exists")
    timestamp: str = Field(default="", description="When the sync was performed")
    error: Optional[str] = Field(default=None, description="Error message if any")


class SyncTriggerResponse(BaseModel):
    """Response for sync trigger."""
    sync_id: str = Field(..., description="Unique sync operation ID")
    status: str = Field(..., description="Initial status")
    message: str = Field(default="", description="Status message")


SYNC_STORE: dict[str, dict[str, Any]] = {}


def _run_sync_script() -> tuple[int, str, str]:
    """Run the sync_rita_entities.py script and return (returncode, stdout, stderr)."""
    root = Path(__file__).resolve().parents[2]
    script_path = root / "scripts" / "sync_rita_entities.py"
    
    if not script_path.exists():
        return 1, "", f"Script not found: {script_path}"
    
    # Run the script in a subprocess with the current Python environment
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root)
    
    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=str(root),
            capture_output=True,
            text=True,
            env=env,
            timeout=300,  # 5 minute timeout
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return 1, "", "Sync script timed out after 5 minutes"
    except Exception as e:
        return 1, "", str(e)


async def _execute_sync(sync_id: str) -> None:
    """Execute the sync operation asynchronously."""
    record = SYNC_STORE.get(sync_id)
    if record is None:
        return
    
    try:
        record["status"] = "running"
        record["message"] = "Starting RITA entity sync..."
        record["started_at"] = datetime.utcnow().isoformat()
        
        # Run the sync script
        returncode, stdout, stderr = _run_sync_script()
        
        if returncode != 0:
            record["status"] = "failed"
            record["message"] = f"Sync script failed with return code {returncode}"
            record["error"] = stderr or stdout
            record["completed_at"] = datetime.utcnow().isoformat()
            return
        
        # Verify the file was updated
        service = RITAIntakeService()
        diagnostics = service.get_snapshot_diagnostics()
        
        record["status"] = "completed"
        record["message"] = stdout.strip() or "Sync completed successfully"
        record["entity_count"] = diagnostics.get("entity_count", 0)
        record["file_path"] = diagnostics.get("snapshot_path", "")
        record["file_exists"] = diagnostics.get("snapshot_exists", False)
        record["completed_at"] = datetime.utcnow().isoformat()
        record["error"] = None
        
    except Exception as e:
        record["status"] = "failed"
        record["message"] = f"Sync failed: {str(e)}"
        record["error"] = str(e)
        record["completed_at"] = datetime.utcnow().isoformat()


@router.post("/rita-entities", response_model=SyncTriggerResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_rita_sync() -> SyncTriggerResponse:
    """
    Trigger a manual sync of RITA entities from Google Sheets.
    
    This endpoint runs the sync_rita_entities.py script which:
    1. Authenticates to Google using workload identity or service account
    2. Reads the ENTITY_RAW worksheet from the configured spreadsheet
    3. Validates and writes the snapshot to data/rita_entities.json
    4. Commits the changes to git (if running in a git repo)
    
    Note: Requires GOOGLE_SHEETS_SPREADSHEET_ID and GOOGLE_SHEETS_WORKSHEET_NAME
    environment variables to be configured, along with appropriate Google auth.
    """
    import uuid
    
    sync_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    
    record = {
        "sync_id": sync_id,
        "status": "queued",
        "message": "Sync operation queued",
        "started_at": now,
        "completed_at": None,
        "entity_count": 0,
        "file_path": "",
        "file_exists": False,
        "error": None,
    }
    SYNC_STORE[sync_id] = record
    
    # Start the sync in the background
    asyncio.create_task(_execute_sync(sync_id))
    
    return SyncTriggerResponse(
        sync_id=sync_id,
        status="queued",
        message="Sync operation queued and starting..."
    )


@router.get("/rita-entities/status/{sync_id}", response_model=SyncStatusResponse)
async def get_sync_status(sync_id: str) -> SyncStatusResponse:
    """Get the status of a specific sync operation."""
    record = SYNC_STORE.get(sync_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sync operation '{sync_id}' not found"
        )
    
    return SyncStatusResponse(
        status=record.get("status", "unknown"),
        message=record.get("message", ""),
        entity_count=record.get("entity_count", 0),
        file_path=record.get("file_path", ""),
        file_exists=record.get("file_exists", False),
        timestamp=record.get("completed_at") or record.get("started_at", ""),
        error=record.get("error"),
    )


@router.get("/rita-entities/status", response_model=SyncStatusResponse)
async def get_latest_sync_status() -> SyncStatusResponse:
    """Get the status of the most recent sync operation."""
    if not SYNC_STORE:
        # Check the current state of the file
        service = RITAIntakeService()
        diagnostics = service.get_snapshot_diagnostics()
        return SyncStatusResponse(
            status="idle",
            message="No sync operation has been triggered yet",
            entity_count=diagnostics.get("entity_count", 0),
            file_path=diagnostics.get("snapshot_path", ""),
            file_exists=diagnostics.get("snapshot_exists", False),
            timestamp="",
            error=None,
        )
    
    # Get the most recent sync
    latest_sync_id = max(SYNC_STORE.keys(), key=lambda k: SYNC_STORE[k].get("started_at", ""))
    record = SYNC_STORE[latest_sync_id]
    
    return SyncStatusResponse(
        status=record.get("status", "unknown"),
        message=record.get("message", ""),
        entity_count=record.get("entity_count", 0),
        file_path=record.get("file_path", ""),
        file_exists=record.get("file_exists", False),
        timestamp=record.get("completed_at") or record.get("started_at", ""),
        error=record.get("error"),
    )


@router.get("/rita-entities", response_model=SyncStatusResponse)
async def get_rita_entities_status() -> SyncStatusResponse:
    """
    Get the current status of RITA entities file.
    
    This is a simple endpoint that returns the current state without
    triggering a sync. Use this to check if entities are loaded.
    """
    service = RITAIntakeService()
    diagnostics = service.get_snapshot_diagnostics()
    
    # Also check if we have entities
    try:
        entities = service.get_entities()
        entity_count = len(entities)
    except Exception:
        entity_count = 0
    
    return SyncStatusResponse(
        status="idle",
        message=f"RITA entities file status: {entity_count} entities loaded",
        entity_count=entity_count,
        file_path=diagnostics.get("snapshot_path", ""),
        file_exists=diagnostics.get("snapshot_exists", False),
        timestamp=datetime.utcnow().isoformat(),
        error=None,
    )
