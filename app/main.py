"""
ATIS Node Builder - Main FastAPI Application
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import API_TITLE, API_VERSION, API_DESCRIPTION
from app.logging import logger
from app.api.entities import router as entities_router
from app.api.nodes import router as nodes_router
from app.api.processing import router as processing_router

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
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(entities_router)
app.include_router(nodes_router)
app.include_router(processing_router)

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
