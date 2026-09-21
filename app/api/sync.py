"""API endpoint to manually trigger RITA entity sync from Google Sheets."""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import httpx

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
    workflow_run_url: Optional[str] = Field(default=None, description="URL to GitHub workflow run")


class SyncTriggerResponse(BaseModel):
    """Response for sync trigger."""
    sync_id: str = Field(..., description="Unique sync operation ID")
    status: str = Field(..., description="Initial status")
    message: str = Field(default="", description="Status message")


SYNC_STORE: dict[str, dict[str, Any]] = {}


async def _trigger_github_workflow() -> tuple[bool, str, str, Optional[str]]:
    """
    Trigger the GitHub Action workflow to sync RITA entities.
    
    Returns: (success, message, error, workflow_run_url)
    """
    token = os.getenv("GITHUB_TOKEN")
    repo = os.getenv("GITHUB_REPOSITORY", "tmakiriyado1-arch/atis-node-builder")
    
    if not token:
        return False, "", "GITHUB_TOKEN not configured. Cannot trigger workflow.", None
    
    url = f"https://api.github.com/repos/{repo}/actions/workflows/sync-rita-entities.yml/dispatches"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
    }
    payload = {"ref": "main"}
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code == 204:
                # Workflow triggered successfully
                # Try to get the workflow run URL
                workflow_url = f"https://github.com/{repo}/actions/workflows/sync-rita-entities.yml"
                return True, "GitHub Action workflow triggered successfully", "", workflow_url
            else:
                return False, "", f"GitHub API error: {response.status_code} - {response.text}", None
    except httpx.TimeoutException:
        return False, "", "GitHub API request timed out", None
    except httpx.HTTPStatusError as e:
        return False, "", f"GitHub API HTTP error: {e.response.status_code} - {e.response.text}", None
    except Exception as e:
        return False, "", f"Failed to trigger workflow: {str(e)}", None


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
        
        # Try GitHub workflow trigger first (preferred method)
        success, message, error, workflow_url = await _trigger_github_workflow()
        
        if success:
            record["status"] = "queued"
            record["message"] = message
            record["workflow_run_url"] = workflow_url
            record["completed_at"] = datetime.utcnow().isoformat()
            record["error"] = None
            logger.info(f"Sync {sync_id}: GitHub workflow triggered, URL={workflow_url}")
            return
        
        # Fallback: try local sync only if Google auth is explicitly configured
        google_token = os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or os.getenv("GOOGLE_SHEETS_API_KEY")
        if not google_token:
            # No Google auth available, cannot run local sync
            record["status"] = "failed"
            record["message"] = "Sync requires GitHub Action or Google authentication"
            record["error"] = error or "GITHUB_TOKEN not configured for GitHub workflow trigger, and no Google credentials available for local sync"
            record["completed_at"] = datetime.utcnow().isoformat()
            logger.error(f"Sync {sync_id}: No valid auth method - GitHub error: {error}")
            return
        
        # Fallback to local sync
        logger.info(f"Sync {sync_id}: Falling back to local sync...")
        record["message"] = "Falling back to local sync (GitHub trigger unavailable)..."
        
        returncode, stdout, stderr = _run_sync_script()
        
        if returncode != 0:
            record["status"] = "failed"
            record["message"] = f"Local sync failed with return code {returncode}"
            record["error"] = stderr or stdout
            record["completed_at"] = datetime.utcnow().isoformat()
            logger.error(f"Sync {sync_id}: Local sync failed - {stderr}")
            return
        
        # Verify the file was updated
        service = RITAIntakeService()
        diagnostics = service.get_snapshot_diagnostics()
        
        record["status"] = "completed"
        record["message"] = stdout.strip() or "Local sync completed successfully"
        record["entity_count"] = diagnostics.get("entity_count", 0)
        record["file_path"] = diagnostics.get("snapshot_path", "")
        record["file_exists"] = diagnostics.get("snapshot_exists", False)
        record["workflow_run_url"] = None
        record["completed_at"] = datetime.utcnow().isoformat()
        record["error"] = None
        logger.info(f"Sync {sync_id}: Local sync completed, entities={record['entity_count']}")
        
    except Exception as e:
        record["status"] = "failed"
        record["message"] = f"Sync failed: {str(e)}"
        record["error"] = str(e)
        record["completed_at"] = datetime.utcnow().isoformat()
        logger.exception(f"Sync {sync_id}: Unexpected error")


@router.post("/rita-entities", response_model=SyncTriggerResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_rita_sync() -> SyncTriggerResponse:
    """
    Trigger a manual sync of RITA entities from Google Sheets.
    
    This endpoint first attempts to trigger the GitHub Action workflow
    (sync-rita-entities.yml) which uses Workload Identity Federation.
    
    If GitHub workflow trigger is not available (no GITHUB_TOKEN),
    it falls back to local sync which requires Google credentials.
    
    **Recommended:** Configure GITHUB_TOKEN in Render environment with:
    - A GitHub Personal Access Token with `repo` scope
    
    This ensures sync works via GitHub Actions with proper WIF auth.
    
    Note: The GitHub Action at `.github/workflows/sync-rita-entities.yml` 
    authenticates to Google using Workload Identity Federation, reads 
    the configured RITA sheet, validates each row, and writes the 
    deterministic JSON snapshot to data/rita_entities.json.
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
        "workflow_run_url": None,
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
        workflow_run_url=record.get("workflow_run_url"),
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
            message="No sync operation has been triggered yet. Use POST /api/sync/rita-entities to trigger.",
            entity_count=diagnostics.get("entity_count", 0),
            file_path=diagnostics.get("snapshot_path", ""),
            file_exists=diagnostics.get("snapshot_exists", False),
            timestamp="",
            error=None,
            workflow_run_url=None,
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
        workflow_run_url=record.get("workflow_run_url"),
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
        workflow_run_url=None,
    )
