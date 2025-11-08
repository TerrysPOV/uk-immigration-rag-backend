"""
FastAPI application for UK Immigration RAG system (T020).

This is the main entry point for the RAG API service.
Implements lifespan management, dependency injection, and endpoint routing.

Features:
- Async lifespan for pipeline initialization/cleanup
- Global error handlers with structured logging
- CORS configuration for frontend integration
- Health check and metrics endpoints
- Structured JSON logging

Endpoints:
- POST /api/rag/query: Natural language query (FR-001)
- GET /api/rag/health: Health check (FR-002)
- POST /api/rag/reindex: Document reindexing (FR-003)
"""

import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()
import sys
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from src.api.routes.rag import router as rag_router, set_pipeline
from src.api.routes.models import router as models_router
from src.api.routes.search_history import router as search_history_router
from src.api.routes.saved_searches import router as saved_searches_router
from src.api.routes.admin import router as admin_router  # Feature 019: Admin endpoints
from src.api.routes.template_workflow import router as template_router  # Feature 023: Template Workflow
from src.api.routes.graph import router as graph_router  # Feature NEO4J-001: Graph traversals
from src.api.models.rag import ErrorResponse
from rag.pipelines.haystack_retrieval import create_production_pipeline, HaystackRetrievalPipeline
from src.services.rag_service import get_rag_service

# Feature 011: Document Ingestion & Batch Processing
from src.api import websocket
from src.api import processing
from src.api import ingestion

# ============================================================================
# Logging Configuration
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger(__name__)


# ============================================================================
# Application Lifespan Management
# ============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """
    Async lifespan context manager for application startup/shutdown.

    Startup:
    1. Load environment variables
    2. Initialize Haystack retrieval pipeline
    3. Verify Qdrant connection
    4. Verify DeepInfra API key
    5. Set global pipeline instance for dependency injection

    Shutdown:
    1. Close Qdrant connections
    2. Clean up pipeline resources

    Yields:
        None (lifespan context)
    """
    # Startup
    logger.info("🚀 Starting UK Immigration RAG API...")

    try:
        # Verify required environment variables
        required_env_vars = ["DEEPINFRA_API_KEY"]
        missing_vars = [var for var in required_env_vars if not os.getenv(var)]

        if missing_vars:
            logger.error(f"Missing required environment variables: {missing_vars}")
            raise ValueError(f"Missing environment variables: {missing_vars}")

        # Initialize RAG service (T003: Feature 015)
        logger.info("Initializing RAG service...")

        rag_service = get_rag_service()
        await rag_service.initialize()

        # Verify initialization with health check
        health_status = await rag_service.health_check()

        logger.info(
            f"✅ RAG pipeline initialized",
            extra={
                "status": health_status.status,
                "document_count": health_status.document_count,
                "quantization_active": health_status.quantization_active,
                "compression_ratio": f"{health_status.compression_ratio:.1%}",
                "memory_mb": f"{health_status.memory_mb:.1f}",
            },
        )

        # Also initialize production pipeline for backward compatibility
        # (Will be removed once all endpoints migrate to RAGService)
        pipeline = create_production_pipeline(
            qdrant_url=os.getenv("QDRANT_URL", "http://localhost:6333"),
            collection_name=os.getenv("QDRANT_COLLECTION", "gov_uk_immigration"),
        )

        # Set global pipeline for dependency injection
        set_pipeline(pipeline)

        # Initialize Neo4J graph schema if enabled (Feature NEO4J-001)
        if os.getenv("GRAPH_EXTRACTION_ENABLED", "false").lower() == "true":
            try:
                from src.services.neo4j_graph_service import get_graph_service

                neo4j_uri = os.getenv("NEO4J_URI")
                neo4j_user = os.getenv("NEO4J_USER", "neo4j")
                neo4j_password = os.getenv("NEO4J_PASSWORD")
                neo4j_database = os.getenv("NEO4J_DATABASE", "neo4j")

                if neo4j_uri and neo4j_password:
                    logger.info("Initializing Neo4J graph schema...")
                    graph_service = get_graph_service(
                        neo4j_uri=neo4j_uri,
                        neo4j_user=neo4j_user,
                        neo4j_password=neo4j_password,
                        neo4j_database=neo4j_database,
                    )
                    graph_service.initialize_schema()
                    logger.info("✅ Neo4J graph schema initialized")
                else:
                    logger.warning("Neo4J credentials not configured, skipping graph initialization")
            except Exception as e:
                logger.warning(f"Neo4J initialization failed (non-fatal): {e}")

        logger.info("✅ RAG API ready to serve requests")

        # Yield control to application
        yield

        # Shutdown
        logger.info("🛑 Shutting down UK Immigration RAG API...")

        # Cleanup pipeline resources
        try:
            # Close Qdrant connections if needed
            # (Haystack handles cleanup internally)
            logger.info("✅ Pipeline cleanup complete")
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")

    except Exception as e:
        logger.exception(f"Fatal error during startup: {e}")
        raise


# ============================================================================
# FastAPI Application
# ============================================================================

app = FastAPI(
    title="UK Immigration RAG API",
    description="Retrieval-Augmented Generation API for UK Immigration guidance documents. "
    "Powered by Haystack 2.x, Qdrant vector database, and DeepInfra embeddings.",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)


# ============================================================================
# Security Headers Middleware
# ============================================================================


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Add OWASP-recommended security headers to all responses.

    Security Fix (T073): HIGH-priority - Protect against XSS, clickjacking, MIME-sniffing
    """

    async def dispatch(self, request, call_next):
        response = await call_next(request)

        # OWASP Secure Headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Content Security Policy (restrictive for API)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "frame-ancestors 'none'"
        )

        return response


# Add security middleware
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=[
        "161.35.44.166",
        "localhost",
        "vectorgov.poview.ai",
        "www.vectorgov.poview.ai",
        "*.gov.uk",
    ],
)


# ============================================================================
# CORS Middleware
# ============================================================================

# CORS Configuration: Same-origin deployment (frontend + backend on 161.35.44.166 via nginx)
# Security Fix (T073): HIGH-priority - Restrictive CORS with defense in depth
#
# Deployment Model:
# - Production: nginx serves frontend and proxies /api/* to backend (same-origin)
# - Development: Separate origins (frontend:3000, backend:8000) require CORS
#
# Default Origins (can be overridden via CORS_ORIGINS environment variable):
# - https://161.35.44.166 (production)
# - http://localhost:3000 (development frontend)
# - http://localhost:8000 (development backend)
#
# For production-only deployment (no dev origins), set: CORS_ORIGINS=https://vectorgov.poview.ai
DEFAULT_CORS_ORIGINS = "https://vectorgov.poview.ai,https://www.vectorgov.poview.ai,https://161.35.44.166,http://localhost:3000,http://localhost:8000"

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", DEFAULT_CORS_ORIGINS).split(","),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],  # Explicit headers instead of "*"
)


# ============================================================================
# Global Exception Handlers
# ============================================================================


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle Pydantic validation errors with structured response."""
    logger.warning(f"Validation error", extra={"path": request.url.path, "errors": exc.errors()})

    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "error": "ValidationError",
            "message": "Request validation failed",
            "details": exc.errors(),
        },
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Handle HTTP exceptions with structured response."""
    logger.error(
        f"HTTP exception",
        extra={"path": request.url.path, "status_code": exc.status_code, "detail": exc.detail},
    )

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.__class__.__name__,
            "message": exc.detail if isinstance(exc.detail, str) else str(exc.detail),
        },
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle unexpected exceptions with structured response."""
    logger.exception(
        f"Unhandled exception",
        extra={"path": request.url.path, "exception_type": exc.__class__.__name__},
    )

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "InternalServerError",
            "message": "An unexpected error occurred. Please contact support.",
        },
    )


# ============================================================================
# Route Registration
# ============================================================================

# Include RAG endpoints
app.include_router(rag_router)

# Include models endpoint (ModelPicker restoration)
app.include_router(models_router)

# Feature 018: Include search history and saved searches endpoints
app.include_router(search_history_router)
app.include_router(saved_searches_router)

# Feature 011: Include ingestion and WebSocket endpoints
app.include_router(ingestion.router)
app.include_router(processing.router)
app.include_router(websocket.router)

# Feature 019: Include admin endpoints (reprocessing)
app.include_router(admin_router)

# Feature 023: Include template workflow endpoints
app.include_router(template_router)

# Feature NEO4J-001: Include graph traversal endpoints
app.include_router(graph_router)


# ============================================================================
# Root Endpoint
# ============================================================================


@app.get(
    "/",
    summary="API Root",
    description="Root endpoint with API information and links to documentation.",
)
async def root():
    """Return API information and navigation links."""
    return {
        "service": "UK Immigration RAG API",
        "version": "1.0.0",
        "status": "operational",
        "documentation": {"interactive": "/docs", "redoc": "/redoc", "openapi": "/openapi.json"},
        "endpoints": {
            "query": "POST /api/rag/query",
            "health": "GET /api/rag/health",
            "reindex": "POST /api/rag/reindex",
        },
        "features": {
            "binary_quantization": True,
            "hybrid_search": os.getenv("RAG_HYBRID_SEARCH_ENABLED", "true") == "true",
            "reranking": os.getenv("RAG_RERANKING_ENABLED", "true") == "true",
            "query_rewrite": os.getenv("RAG_QUERY_REWRITE_ENABLED", "true") == "true",
        },
    }


# ============================================================================
# Application Entry Point
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    # Get configuration from environment
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))
    reload = os.getenv("API_RELOAD", "false").lower() == "true"

    logger.info(f"Starting server on {host}:{port} (reload={reload})")

    uvicorn.run("main:app", host=host, port=port, reload=reload, log_level="info")
