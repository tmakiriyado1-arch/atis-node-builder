"""API endpoints for the local NORA processing pipeline."""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_processor

router = APIRouter(tags=["nora"])


@router.post("/process", status_code=status.HTTP_200_OK)
async def process_document(path: str = "", processor=Depends(get_processor)):
    file_path = Path(path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="source file not found")
    return processor.process_file(file_path)


@router.post("/process-directory", status_code=status.HTTP_200_OK)
async def process_directory(path: str = "", processor=Depends(get_processor)):
    directory = Path(path)
    if not directory.exists() or not directory.is_dir():
        raise HTTPException(status_code=404, detail="directory not found")
    return processor.process_directory(directory)


@router.get("/unresolved", status_code=status.HTTP_200_OK)
async def list_unresolved(processor=Depends(get_processor)):
    return processor.list_unresolved()
