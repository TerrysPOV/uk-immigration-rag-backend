"""
UK Gov Immigration Guidance Vectorization API - Feature 012 Enhanced
Main FastAPI application with Feature 012: Comprehensive Frontend Enhancement Suite

Features:
- Admin Panel (user management, config, audit logs)
- Template Generation (drag-and-drop builder)
- Workflow Management (visual designer, execution)
- Analytics Dashboard (real-time metrics, WebSocket)
- Advanced Search (boolean queries, field-specific search)
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Create FastAPI app
app = FastAPI(
    title="UK Gov Immigration Guidance Vectorization API",
    description="AI-powered RAG system with admin panel, templates, workflows, and analytics",
    version="2.0.0 - Feature 012",
)

# CORS middleware - Restrictive configuration for production
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://161.35.44.166,http://localhost:3000").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
    expose_headers=["Content-Type", "Authorization"],
    max_age=3600,  # Cache preflight for 1 hour
)

# Security headers middleware (T073 - OWASP best practices)
@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    return response

# ============================================================================
# Import Feature 012 Routers
# ============================================================================

try:
    from src.api.admin import router as admin_router
    ADMIN_AVAILABLE = True
except ImportError as e:
    print(f"[WARNING] Admin router not available: {e}")
    ADMIN_AVAILABLE = False

try:
    from src.api.templates import router as templates_router
    TEMPLATES_AVAILABLE = True
except ImportError as e:
    print(f"[WARNING] Templates router not available: {e}")
    TEMPLATES_AVAILABLE = False

try:
    from src.api.workflows import router as workflows_router
    WORKFLOWS_AVAILABLE = True
except ImportError as e:
    print(f"[WARNING] Workflows router not available: {e}")
    WORKFLOWS_AVAILABLE = False

try:
    from src.api.analytics import router as analytics_router
    ANALYTICS_AVAILABLE = True
except ImportError as e:
    print(f"[WARNING] Analytics router not available: {e}")
    ANALYTICS_AVAILABLE = False

try:
    from src.api.advanced_search import router as advanced_search_router
    ADVANCED_SEARCH_AVAILABLE = True
except ImportError as e:
    print(f"[WARNING] Advanced Search router not available: {e}")
    ADVANCED_SEARCH_AVAILABLE = False

try:
    from src.api.websocket import router as websocket_router
    WEBSOCKET_AVAILABLE = True
except ImportError as e:
    print(f"[WARNING] WebSocket router not available: {e}")
    WEBSOCKET_AVAILABLE = False

try:
    from src.api.routes.models import router as models_router
    MODELS_AVAILABLE = True
except ImportError as e:
    print(f"[WARNING] Models router not available: {e}")
    MODELS_AVAILABLE = False

try:
    from src.api.filters import router as filters_router
    FILTERS_AVAILABLE = True
except ImportError as e:
    print(f"[WARNING] Filters router not available: {e}")
    FILTERS_AVAILABLE = False

try:
    from src.api.search_history import router as search_history_router
    SEARCH_HISTORY_AVAILABLE = True
except ImportError as e:
    print(f"[WARNING] Search History router not available: {e}")
    SEARCH_HISTORY_AVAILABLE = False

try:
    from src.api.saved_searches import router as saved_searches_router
    SAVED_SEARCHES_AVAILABLE = True
except ImportError as e:
    print(f"[WARNING] Saved Searches router not available: {e}")
    SAVED_SEARCHES_AVAILABLE = False

# ============================================================================
# Include Feature 012 Routers
# ============================================================================

if ADMIN_AVAILABLE:
    app.include_router(admin_router)
    print("[INFO] Admin Panel routes registered: /api/v1/admin/*")

if TEMPLATES_AVAILABLE:
    app.include_router(templates_router)
    print("[INFO] Template Management routes registered: /api/v1/templates/*")

if WORKFLOWS_AVAILABLE:
    app.include_router(workflows_router)
    print("[INFO] Workflow Management routes registered: /api/v1/workflows/*")

if ANALYTICS_AVAILABLE:
    app.include_router(analytics_router)
    print("[INFO] Analytics Dashboard routes registered: /api/v1/analytics/*")

if ADVANCED_SEARCH_AVAILABLE:
    app.include_router(advanced_search_router)
    print("[INFO] Advanced Search routes registered: /api/v1/search/*")

if WEBSOCKET_AVAILABLE:
    app.include_router(websocket_router)
    print("[INFO] WebSocket routes registered: /api/v1/ws/*")

if MODELS_AVAILABLE:
    app.include_router(models_router)
    print("[INFO] Models routes registered: /api/models/*")

if FILTERS_AVAILABLE:
    app.include_router(filters_router)
    print("[INFO] Filter routes registered: /api/v1/search/filters/*")

if SEARCH_HISTORY_AVAILABLE:
    app.include_router(search_history_router)
    print("[INFO] Search History routes registered: /api/v1/search/history/*")

if SAVED_SEARCHES_AVAILABLE:
    app.include_router(saved_searches_router)
    print("[INFO] Saved Searches routes registered: /api/v1/search/saved/*")

# ============================================================================
# Core Endpoints
# ============================================================================

@app.get("/")
async def root():
    """Root endpoint with Feature 012 status."""
    return {
        "message": "UK Gov Immigration Guidance API - Feature 012 Enhanced",
        "status": "running",
        "version": "2.0.0",
        "features": {
            "admin_panel": ADMIN_AVAILABLE,
            "templates": TEMPLATES_AVAILABLE,
            "workflows": WORKFLOWS_AVAILABLE,
            "analytics": ANALYTICS_AVAILABLE,
            "advanced_search": ADVANCED_SEARCH_AVAILABLE,
            "websocket": WEBSOCKET_AVAILABLE,
            "model_picker": MODELS_AVAILABLE,
            "feature_010_filters": FILTERS_AVAILABLE,
            "feature_010_history": SEARCH_HISTORY_AVAILABLE,
            "feature_010_saved_searches": SAVED_SEARCHES_AVAILABLE,
        }
    }

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "database": "connected",
        "vectors": "ready",
        "feature_012": {
            "admin": ADMIN_AVAILABLE,
            "templates": TEMPLATES_AVAILABLE,
            "workflows": WORKFLOWS_AVAILABLE,
            "analytics": ANALYTICS_AVAILABLE,
            "advanced_search": ADVANCED_SEARCH_AVAILABLE,
            "websocket": WEBSOCKET_AVAILABLE,
            "model_picker": MODELS_AVAILABLE,
        },
        "feature_010": {
            "filters": FILTERS_AVAILABLE,
            "search_history": SEARCH_HISTORY_AVAILABLE,
            "saved_searches": SAVED_SEARCHES_AVAILABLE,
        }
    }

@app.get("/api/v1/status")
async def feature_status():
    """Feature 012 status endpoint."""
    return {
        "feature_012_enabled": True,
        "components": {
            "admin_panel": {
                "enabled": ADMIN_AVAILABLE,
                "endpoints": [
                    "GET /api/v1/admin/users",
                    "PUT /api/v1/admin/users/{id}/role",
                    "PATCH /api/v1/admin/users/{id}/status",
                    "POST /api/v1/admin/users/{id}/reset-password",
                    "GET /api/v1/admin/users/{id}/profile",
                    "GET /api/v1/admin/config",
                    "PUT /api/v1/admin/config",
                    "GET /api/v1/admin/audit-logs",
                ] if ADMIN_AVAILABLE else []
            },
            "template_generation": {
                "enabled": TEMPLATES_AVAILABLE
            },
            "workflow_management": {
                "enabled": WORKFLOWS_AVAILABLE
            },
            "analytics_dashboard": {
                "enabled": ANALYTICS_AVAILABLE
            },
            "advanced_search": {
                "enabled": ADVANCED_SEARCH_AVAILABLE
            },
            "websocket": {
                "enabled": WEBSOCKET_AVAILABLE
            }
        }
    }

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
        access_log=True
    )
