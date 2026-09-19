"""
ATIS Node Builder - Main FastAPI Application
"""
import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import API_TITLE, API_VERSION, API_DESCRIPTION
from app.logging import logger
from app.api.entities import router as entities_router
from app.api.nodes import router as nodes_router
from app.api.processing import router as processing_router
from app.api.runs import router as runs_router


def _cors_origins() -> list[str]:
    raw = os.getenv("NORA_FRONTEND_ORIGIN") or os.getenv("NORA_FRONTEND_ORIGINS") or ""
    origins = [part.strip() for part in raw.split(",") if part.strip()]
    if not origins:
        return ["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:4173"]
    return origins


# Initialize FastAPI app
app = FastAPI(
    title=API_TITLE,
    version=API_VERSION,
    description=API_DESCRIPTION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(entities_router)
app.include_router(nodes_router)
app.include_router(processing_router)
app.include_router(runs_router)


@app.exception_handler(HTTPException)
async def handle_http_exception(request: Request, exc: HTTPException):
    detail = exc.detail
    payload = detail
    if isinstance(detail, dict) and "error" in detail:
        payload = detail
    else:
        payload = {"error": {"code": f"HTTP_{exc.status_code}", "message": str(detail) if detail else "Request failed"}}
    return JSONResponse(status_code=exc.status_code, content=payload)


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, exc: RequestValidationError):
    message = "; ".join(error.get("msg", "Validation error") for error in exc.errors())
    payload = {"error": {"code": "VALIDATION_ERROR", "message": message}}
    return JSONResponse(status_code=422, content=payload)


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception):
    logger.exception("Unhandled application error")
    payload = {"error": {"code": "INTERNAL_SERVER_ERROR", "message": "An unexpected server error occurred."}}
    return JSONResponse(status_code=500, content=payload)

# Health check endpoint
@app.get("/health")
async def health_check():
    """Service health check"""
    return {
        "status": "ok",
        "service": "atis-node-builder",
        "version": API_VERSION,
    }

# Root endpoint
@app.get("/")
async def root():
    """API root endpoint"""
    return {
        "service": "ATIS Node Builder",
        "version": API_VERSION,
        "docs": "/docs",
        "status": "ready",
    }

# Startup event
@app.on_event("startup")
async def startup_event():
    """Initialize services on startup"""
    logger.info("ATIS Node Builder starting up...")
    # TODO: Initialize database connection, schema registry, entity registry, etc.

# Shutdown event
@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info("ATIS Node Builder shutting down...")
    # TODO: Close database connections, cleanup resources, etc.

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
