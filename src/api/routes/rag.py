"""
FastAPI routes for RAG endpoints (T017-T019).

Implements three HTTP endpoints per spec.md Functional Requirements:
- POST /api/rag/query: Natural language query endpoint (FR-001, FR-005)
- GET /api/rag/health: System health check (FR-002, FR-006, FR-007, FR-008)
- POST /api/rag/reindex: Document reindexing (FR-003, FR-016)

All endpoints return JSON with appropriate HTTP status codes (FR-004).
Endpoints integrate with Haystack pipeline created in T014.
"""

import os
import time
import hashlib
import uuid
import psutil
from pydantic import BaseModel, Field
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import JSONResponse
from datetime import datetime
import logging

# Qdrant exceptions for graceful degradation (T008)
from qdrant_client.http.exceptions import UnexpectedResponse as QdrantException
from qdrant_client.models import Filter, FieldCondition, MatchValue

from src.api.models.rag import (
    RAGQuery,
    QueryResult,
    DocumentResult,
    HealthStatus,
    ReindexRequest,
    ReindexResponse,
    ReindexStatus,
    ErrorResponse,
)
from src.rag.pipelines.haystack_retrieval import HaystackRetrievalPipeline, create_production_pipeline
from src.services.rag_service import get_rag_service, RAGService
from src.services.openrouter_service import OpenRouterService
from src.models.document_summary import SummarizeResponse
from src.models.document_translation import TranslateResponse
from src.database import get_db
from src.middleware.rbac import get_current_user, get_current_user_optional
from sqlalchemy.orm import Session

# Initialize logger
logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/api/rag", tags=["RAG"])

# Global pipeline instance (initialized at app startup via lifespan)

# Request model for chunk translation (RAG-appropriate)
class TranslateChunkRequest(BaseModel):
    """Request model for chunk translation."""
    chunk_text: str = Field(..., description="Text chunk to translate from search results")
    title: Optional[str] = Field("Document", description="Document title for context")
    url: Optional[str] = Field("", description="Document URL for reference")
    reading_level: str = Field("grade8", description="Target reading level (grade6/grade8/grade10)")
    model: Optional[str] = Field(None, description="Model to use for translation (e.g., qwen/qwen-2.5-72b-instruct)")
_pipeline: Optional[HaystackRetrievalPipeline] = None


def get_pipeline() -> HaystackRetrievalPipeline:
    """
    Dependency injection for Haystack pipeline.

    Raises:
        HTTPException: 503 if pipeline not initialized
    """
    if _pipeline is None:
        raise HTTPException(
            status_code=503, detail="RAG pipeline not initialized. Check application startup logs."
        )
    return _pipeline


def set_pipeline(pipeline: HaystackRetrievalPipeline):
    """Set global pipeline instance (called during app startup)."""
    global _pipeline
    _pipeline = pipeline


async def get_rag_service_dependency() -> RAGService:
    """
    Dependency injection for RAGService (T007: Feature 015).

    Raises:
        HTTPException: 503 if RAG service not initialized
    """
    rag_service = get_rag_service()
    if not rag_service.initialized:
        raise HTTPException(
            status_code=503,
            detail="RAG service not initialized. Please wait for startup to complete or check logs.",
        )
    return rag_service

async def fetch_document_content_from_qdrant(document_identifier: str, rag_service: RAGService) -> tuple[str, dict]:
    """
    Fetch all chunks for a document from Qdrant and reconstruct full text.

    Args:
        document_identifier: Can be URL, document_id hash, or document_pk
        rag_service: RAG service instance with Qdrant client

    Returns:
        Full document text (concatenated chunks in order)

    Raises:
        HTTPException: 404 if document not found, 500 if Qdrant error
    """
    try:
        # Try multiple search strategies to find the document
        # 1. Try as document_id hash first
        search_result = rag_service.qdrant_client.scroll(
            collection_name=rag_service.collection_name,
            scroll_filter=Filter(
                must=[
                    FieldCondition(
                        key="document_id",
                        match=MatchValue(value=document_identifier)
                    )
                ]
            ),
            limit=1000,
            with_payload=True,
            with_vectors=False,
        )

        points = search_result[0]

        # 2. If not found, try as URL
        if not points:
            search_result = rag_service.qdrant_client.scroll(
                collection_name=rag_service.collection_name,
                scroll_filter=Filter(
                    must=[
                        FieldCondition(
                            key="url",
                            match=MatchValue(value=document_identifier)
                        )
                    ]
                ),
                limit=1000,
                with_payload=True,
                with_vectors=False,
            )
            points = search_result[0]

        # 3. If STILL not found, try as document_pk (integer)
        if not points:
            try:
                doc_pk = int(document_identifier)
                search_result = rag_service.qdrant_client.scroll(
                    collection_name=rag_service.collection_name,
                    scroll_filter=Filter(
                        must=[
                            FieldCondition(
                                key="document_pk",
                                match=MatchValue(value=doc_pk)
                            )
                        ]
                    ),
                    limit=1000,
                    with_payload=True,
                    with_vectors=False,
                )
                points = search_result[0]
            except (ValueError, TypeError):
                pass  # Not an integer, skip this strategy

        # NOW check if we found anything
        if not points:
            logger.warning(f"No chunks found for document: {document_identifier}")
            raise HTTPException(
                status_code=404,
                detail={"error": "DocumentNotFound", "message": f"No content found for document: {document_identifier}"}
            )

        # Extract metadata from first chunk (all chunks have same document metadata)
        first_point = points[0]
        metadata = {
            "title": first_point.payload.get("title", "Unknown Document"),
            "url": first_point.payload.get("url", ""),
            "document_type": first_point.payload.get("document_type", "guidance")
        }

        # Sort chunks by chunk_index to maintain document order
        chunks_with_index = []
        for point in points:
            text = point.payload.get("chunk_text", "")
            chunk_index = point.payload.get("chunk_index", 0)
            chunks_with_index.append((chunk_index, text))

        # Sort by index and concatenate
        chunks_with_index.sort(key=lambda x: x[0])
        full_text = "\n\n".join(chunk[1] for chunk in chunks_with_index)

        # Validate that we have actual content
        if not full_text or len(full_text.strip()) == 0:
            logger.error(f"Document found but has no text content: {document_identifier}")
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "DocumentContentEmpty",
                    "message": f"This document exists but has no content. Try a different search result."
                }
            )

        logger.info(f"Fetched {len(points)} chunks for document: {document_identifier[:60]}...")
        return full_text, metadata

    except QdrantException as e:
        logger.error(f"Qdrant error fetching document: {e}")
        raise HTTPException(
            status_code=500,
            detail={"error": "InternalServerError", "message": "Failed to fetch document from vector database"}
        )


# ============================================================================
# POST /api/rag/query - Natural Language Query (FR-001, FR-005)
# ============================================================================


@router.post(
    "/query",
    response_model=QueryResult,
    status_code=200,
    summary="Query UK immigration guidance",
    description="Submit a natural language question and receive relevant document excerpts. "
    "Response time must be <2s for p95 latency (FR-005).",
    responses={
        200: {"description": "Successful query with ranked results", "model": QueryResult},
        400: {"description": "Invalid query (empty, too long, malformed)", "model": ErrorResponse},
        500: {
            "description": "Internal server error (pipeline failure, API error)",
            "model": ErrorResponse,
        },
        503: {
            "description": "Service unavailable (Qdrant down, DeepInfra unreachable)",
            "model": ErrorResponse,
        },
    },
)
async def query_rag(
    query: RAGQuery, request: Request, rag_service: RAGService = Depends(get_rag_service_dependency)
) -> QueryResult:
    """
    Execute RAG query against UK immigration guidance documents (T007: Feature 015).

    This endpoint uses the RAGService layer which handles:
    1. Query validation (1-1000 chars, not empty)
    2. Embedding generation via DeepInfra API (FR-017, FR-019)
    3. Document retrieval from Qdrant with binary quantization (FR-006)
    4. Response formatting with metadata

    Performance constraint: p95 latency <2s (FR-005)

    Args:
        query: RAGQuery with user's question and optional parameters
        request: FastAPI Request (for logging/tracing)
        rag_service: Injected RAGService instance

    Returns:
        QueryResult with ranked document excerpts and metadata

    Raises:
        HTTPException 400: Query validation failed
        HTTPException 500: Pipeline execution error
        HTTPException 503: RAG service not initialized or unavailable
    """
    request_id = str(uuid.uuid4())
    logger.info(
        f"RAG query received (T007)",
        extra={
            "request_id": request_id,
            "query_length": len(query.query),
            "top_k": query.top_k,
        },
    )

    start_time = time.time()

    try:
        # Execute query via RAGService (T007: Feature 015)
        result = await rag_service.query(query)

        elapsed_ms = (time.time() - start_time) * 1000

        logger.info(
            f"RAG query completed",
            extra={
                "request_id": request_id,
                "took_ms": elapsed_ms,
                "results_count": result.total_results,
            },
        )

        # FR-005: Log warning if latency exceeds 2s
        if elapsed_ms > 2000:
            logger.warning(
                f"Query latency {elapsed_ms:.0f}ms exceeds 2s target (FR-005)",
                extra={"request_id": request_id, "latency_ms": elapsed_ms},
            )

        return result

    except ValueError as e:
        # Validation or API key errors
        logger.error(f"Query validation error: {e}", extra={"request_id": request_id})
        raise HTTPException(
            status_code=400,
            detail={"error": "ValidationError", "message": str(e), "request_id": request_id},
        )

    except QdrantException as e:
        # T008: Graceful degradation - Qdrant connection/operational errors
        logger.error(f"Qdrant error: {e}", extra={"request_id": request_id})
        raise HTTPException(
            status_code=503,
            detail={
                "error": "QdrantUnavailable",
                "message": "RAG pipeline not initialized. Please try again later.",
                "request_id": request_id,
            },
        )

    except ConnectionError as e:
        # DeepInfra or other network errors (T008)
        logger.error(f"External service unavailable: {e}", extra={"request_id": request_id})
        raise HTTPException(
            status_code=503,
            detail={"error": "ServiceUnavailable", "message": str(e), "request_id": request_id},
        )

    except Exception as e:
        # Unexpected errors (T008: Graceful degradation)
        logger.exception(f"Query execution failed: {e}", extra={"request_id": request_id})
        raise HTTPException(
            status_code=500,
            detail={"error": "InternalServerError", "message": str(e), "request_id": request_id},
        )


# ============================================================================
# GET /api/rag/health - System Health Check (FR-002, FR-006, FR-007, FR-008)
# ============================================================================


@router.get(
    "/health",
    response_model=HealthStatus,
    status_code=200,
    summary="Check RAG system health",
    description="Reports system status, document count, binary quantization status, "
    "compression ratio, and memory usage. "
    "Validates FR-006 (quantization active), FR-007 (memory <500MB), "
    "FR-008 (compression ratio >=97%).",
    responses={
        200: {"description": "Health check successful", "model": HealthStatus},
        503: {
            "description": "System unhealthy (Qdrant down, memory exceeded, etc.)",
            "model": ErrorResponse,
        },
    },
)
async def health_check(rag_service: RAGService = Depends(get_rag_service_dependency)) -> HealthStatus:
    """
    Perform comprehensive health check of RAG system (T007: Feature 015).

    Uses RAGService.health_check() which validates:
    1. Qdrant connection and document count
    2. Binary quantization status (FR-006: must be active)
    3. Compression ratio (FR-008: must be >=97%)
    4. Memory usage (FR-007: must be <500MB)
    5. DeepInfra API availability
    6. Pipeline components

    Returns:
        HealthStatus with system metrics and component status

    Raises:
        HTTPException 503: RAG service not initialized or system unhealthy
    """
    logger.info("Health check requested (T007)")

    try:
        # Execute health check via RAGService (T007: Feature 015)
        health_status = await rag_service.health_check()

        logger.info(
            f"Health check completed: {health_status.status}",
            extra={
                "status": health_status.status,
                "document_count": health_status.document_count,
                "quantization_active": health_status.quantization_active,
                "compression_ratio": health_status.compression_ratio,
            },
        )

        # Return 503 if unhealthy (T008: Graceful degradation)
        if health_status.status == "unhealthy":
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "ServiceUnhealthy",
                    "message": "RAG system is unhealthy",
                    "status": health_status.status,
                    "qdrant_status": health_status.qdrant_status,
                    "deepinfra_status": health_status.deepinfra_status,
                },
            )

        return health_status

    except HTTPException:
        # Re-raise HTTPException (already has correct status code)
        raise

    except QdrantException as e:
        # T008: Graceful degradation - Qdrant connection errors during health check
        logger.error(f"Qdrant error during health check: {e}")
        raise HTTPException(
            status_code=503,
            detail={
                "error": "QdrantUnavailable",
                "message": "Qdrant vector database is unavailable. Please try again later.",
            },
        )

    except Exception as e:
        # Unexpected errors (T008: Graceful degradation)
        logger.exception(f"Health check failed: {e}")
        raise HTTPException(
            status_code=503,
            detail={
                "error": "HealthCheckFailed",
                "message": f"Health check failed: {str(e)}",
            },
        )


# ============================================================================
# POST /api/rag/reindex - Document Reindexing (FR-003, FR-016)
# ============================================================================


@router.post(
    "/reindex",
    response_model=ReindexResponse,
    status_code=202,
    summary="Trigger document reindexing",
    description="Queue a background job to reindex all UK immigration documents. "
    "Supports zero-downtime reindexing (FR-016). "
    "Admin-only endpoint (requires authentication).",
    responses={
        202: {"description": "Reindexing job queued successfully", "model": ReindexResponse},
        400: {"description": "Invalid reindex request", "model": ErrorResponse},
        503: {"description": "Reindexing service unavailable", "model": ErrorResponse},
    },
)
async def reindex_documents(
    request_body: ReindexRequest,
    request: Request,
    pipeline: HaystackRetrievalPipeline = Depends(get_pipeline),
) -> ReindexResponse:
    """
    Trigger document reindexing operation.

    This endpoint queues a background job to:
    1. Fetch documents from DigitalOcean Spaces (FR-014)
    2. Generate embeddings via DeepInfra API (FR-017, FR-019)
    3. Index documents in Qdrant with binary quantization (FR-006)
    4. Rebuild BM25 Whoosh index (FR-010)
    5. Verify no data loss (FR-014, FR-015)
    6. Support zero-downtime reindexing (FR-016)

    Note: Actual reindexing implementation is stubbed for now.
    Production implementation would use Celery/background tasks.

    Args:
        request_body: ReindexRequest with force, source_filter, clear_existing
        request: FastAPI Request
        pipeline: Injected Haystack pipeline

    Returns:
        ReindexResponse with job ID and status

    Raises:
        HTTPException 400: Invalid request parameters
        HTTPException 503: Reindexing service unavailable
    """
    request_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())

    logger.info(
        f"Reindex request received",
        extra={
            "request_id": request_id,
            "job_id": job_id,
            "force": request_body.force,
            "source_filter": request_body.source_filter,
            "clear_existing": request_body.clear_existing,
        },
    )

    # Warning for destructive operations
    if request_body.clear_existing:
        logger.warning(
            f"Destructive reindex requested (clear_existing=True)",
            extra={"request_id": request_id, "job_id": job_id},
        )

    # TODO: Implement actual background job queueing
    # For now, return a mock response indicating job is queued
    # Production implementation would:
    # 1. Create Celery task or background worker
    # 2. Queue job with parameters
    # 3. Return job ID for status tracking
    # 4. Implement GET /api/rag/reindex/{job_id} status endpoint

    response = ReindexResponse(
        job_id=job_id,
        status=ReindexStatus.QUEUED,
        message="Reindexing job queued successfully. "
        "Note: Background job execution not yet implemented. "
        "This is a stub response for FR-003 compliance.",
        estimated_duration_seconds=180,  # Estimate: 3 minutes for 775 documents
        progress_pct=0.0,
        documents_processed=0,
    )

    logger.info(
        f"Reindex job queued",
        extra={"request_id": request_id, "job_id": job_id, "status": response.status},
    )

    return response


# ============================================================================
# POST /api/rag/summarize - AI-Generated Document Summary (T016)
# ============================================================================


@router.post(
    "/summarize",
    response_model=SummarizeResponse,
    status_code=200,
    summary="Generate AI summary of document",
    description="Generate AI-powered summary (150-250 words) of UK government guidance document. "
    "Uses OpenRouter API with 24-hour caching. Rate limit: 10 req/min per user.",
    responses={
        200: {"description": "Summary generated successfully", "model": SummarizeResponse},
        400: {"description": "Invalid request (max_words out of range)", "model": ErrorResponse},
        401: {"description": "Unauthorized (missing or invalid token)", "model": ErrorResponse},
        404: {"description": "Document not found", "model": ErrorResponse},
        408: {"description": "Request timeout (OpenRouter > 30s)", "model": ErrorResponse},
        429: {"description": "Rate limit exceeded (10 req/min)", "model": ErrorResponse},
    },
)
async def summarize_document(
    document_id: str,
    max_words: int = 200,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SummarizeResponse:
    """
    Generate AI summary of document (T016: Feature 018).

    Uses OpenRouter API to generate plain English summary following GDS content design standards:
    - Target word count: 150-250 words
    - Reading age: 9 years old
    - Active voice, short sentences (max 25 words)
    - Everyday language

    Cache behavior:
    - 24-hour TTL (time-to-live)
    - System-wide cache (shared across users)
    - LRU eviction at 1GB

    Args:
        document_id: Document identifier to summarize
        max_words: Target word count (150-250, default 200)
        user: Authenticated user from Google OAuth token
        db: Database session

    Returns:
        SummarizeResponse with summary_text, word_count, model_used

    Raises:
        HTTPException 400: max_words out of range
        HTTPException 401: Missing or invalid token
        HTTPException 404: Document not found
        HTTPException 408: OpenRouter API timeout (>30s)
        HTTPException 429: Rate limit exceeded
    """
    request_id = str(uuid.uuid4())
    user_id = user.get("user_id") if user else "anonymous"

    logger.info(
        f"Summarize request received (T016)",
        extra={
            "request_id": request_id,
            "document_id": document_id,
            "max_words": max_words,
            "user_id": user_id,
        },
    )

    # Validate max_words range
    if not (150 <= max_words <= 250):
        logger.error(f"Invalid max_words: {max_words} (must be 150-250)")
        raise HTTPException(
            status_code=400,
            detail={"error": "ValidationError", "message": f"max_words must be 150-250, got {max_words}"},
        )

    # Initialize OpenRouter service
    openrouter_service = OpenRouterService(db)

    # Fetch actual document content from Qdrant
    try:
        document_text = await fetch_document_content_from_qdrant(document_id, rag_service)
    except HTTPException as e:
        if e.status_code == 404:
            logger.error(f"Document not found: {document_id}")
        raise e

    try:
        # Generate summary via OpenRouter service (with caching)
        result = await openrouter_service.summarize(
            document_id=document_id, document_text=document_text, max_words=max_words, user_id=user_id
        )

        logger.info(
            f"Summary generated successfully",
            extra={
                "request_id": request_id,
                "document_id": document_id,
                "word_count": result["word_count"],
                "cached": result.get("cached", False),
            },
        )

        return SummarizeResponse(**result)

    except ValueError as e:
        # Validation errors
        logger.error(f"Summarize validation error: {e}", extra={"request_id": request_id})
        raise HTTPException(status_code=400, detail={"error": "ValidationError", "message": str(e)})

    except ConnectionError as e:
        # OpenRouter API unavailable
        logger.error(f"OpenRouter connection error: {e}", extra={"request_id": request_id})
        raise HTTPException(
            status_code=503,
            detail={"error": "ServiceUnavailable", "message": "OpenRouter API is unavailable. Please try again later."},
        )

    except TimeoutError as e:
        # OpenRouter API timeout (>30s)
        logger.error(f"OpenRouter timeout: {e}", extra={"request_id": request_id})
        raise HTTPException(status_code=408, detail={"error": "RequestTimeout", "message": "Request timed out after 30 seconds"})

    except Exception as e:
        # Unexpected errors
        logger.exception(f"Summarize failed: {e}", extra={"request_id": request_id})
        raise HTTPException(status_code=500, detail={"error": "InternalServerError", "message": str(e)})


# ============================================================================
# POST /api/rag/document/translate - Plain English Translation (T016)
# ============================================================================


@router.post(
    "/document/translate",
    response_model=TranslateResponse,
    status_code=200,
    summary="Translate document to plain English",
    description="Translate UK government guidance to plain English at specified reading level (grade6/8/10). "
    "Uses OpenRouter API with 24-hour caching. Rate limit: 10 req/min per user.",
    responses={
        200: {"description": "Translation generated successfully", "model": TranslateResponse},
        400: {"description": "Invalid request (invalid reading_level)", "model": ErrorResponse},
        401: {"description": "Unauthorized (missing or invalid token)", "model": ErrorResponse},
        404: {"description": "Document not found", "model": ErrorResponse},
        408: {"description": "Request timeout (OpenRouter > 30s)", "model": ErrorResponse},
        429: {"description": "Rate limit exceeded (10 req/min)", "model": ErrorResponse},
    },
)
async def translate_document(
    document_id: str,
    reading_level: str = "grade8",
    model: Optional[str] = None,
    user: dict = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
    rag_service: RAGService = Depends(get_rag_service_dependency),
) -> TranslateResponse:
    """
    Translate document to plain English (T016: Feature 018, T024: Feature 024).

    Uses OpenRouter API to generate plain English translation following GDS content design standards:
    - Reading levels: grade6 (age 9), grade8 (age 11), grade10 (age 13)
    - Sentence length: max 25 words
    - Active voice (not passive)
    - Plain language (everyday words, explain jargon)
    - Clear structure (bullet points, short paragraphs)

    Feature 024: Dynamic Model-Aware Document Chunking
    - Automatically detects if document exceeds model's output token limit
    - Splits large documents on section boundaries (markdown headers)
    - Translates chunks in parallel with caching
    - Combines chunks preserving markdown structure

    Cache behavior:
    - Permanent content-addressable caching (Feature 022)
    - Separate cache entries for each reading level
    - Composite key: (document_id, source_hash, reading_level, prompt_hash)

    Args:
        document_id: Document identifier to translate
        reading_level: Target reading level (grade6, grade8, grade10, default grade8)
        model: OpenRouter model identifier (None = use OPENROUTER_MODEL env var)
                Examples: "anthropic/claude-3-haiku", "qwen/qwen-2.5-72b-instruct"
        user: Authenticated user from Google OAuth token
        db: Database session

    Returns:
        TranslateResponse with translated_text, reading_level, model_used, chunks_processed

    Raises:
        HTTPException 400: Invalid reading_level
        HTTPException 401: Missing or invalid token
        HTTPException 404: Document not found
        HTTPException 408: OpenRouter API timeout (>30s)
        HTTPException 429: Rate limit exceeded
    """
    request_id = str(uuid.uuid4())
    user_id = user.get("user_id") if user else "anonymous"

    logger.info(
        f"Translate request received (T016)",
        extra={
            "request_id": request_id,
            "document_id": document_id,
            "reading_level": reading_level,
            "user_id": user_id,
        },
    )

    # Validate reading_level
    allowed_levels = ["grade6", "grade8", "grade10"]
    if reading_level not in allowed_levels:
        logger.error(f"Invalid reading_level: {reading_level} (must be grade6/8/10)")
        raise HTTPException(
            status_code=400,
            detail={
                "error": "ValidationError",
                "message": f"reading_level must be one of {allowed_levels}, got '{reading_level}'",
            },
        )

    # Initialize OpenRouter service
    openrouter_service = OpenRouterService(db)

    # Fetch actual document content and metadata from Qdrant
    try:
        document_text, metadata = await fetch_document_content_from_qdrant(document_id, rag_service)
    except HTTPException as e:
        if e.status_code == 404:
            logger.error(f"Document not found: {document_id}")
        raise e

    try:
        # Generate translation via OpenRouter service (with caching and chunking)
        # T024: Pass model parameter for dynamic chunking support
        result = await openrouter_service.translate(
            document_id=document_id,
            document_text=document_text,
            reading_level=reading_level,
            model=model,  # Feature 024: Model parameter from frontend
            user_id=user_id,
            metadata=metadata
        )

        logger.info(
            f"Translation generated successfully",
            extra={
                "request_id": request_id,
                "document_id": document_id,
                "reading_level": reading_level,
                "cached": result.get("cached", False),
            },
        )

        return TranslateResponse(**result)

    except ValueError as e:
        # Validation errors
        logger.error(f"Translate validation error: {e}", extra={"request_id": request_id})
        raise HTTPException(status_code=400, detail={"error": "ValidationError", "message": str(e)})

    except ConnectionError as e:
        # OpenRouter API unavailable
        logger.error(f"OpenRouter connection error: {e}", extra={"request_id": request_id})
        raise HTTPException(
            status_code=503,
            detail={"error": "ServiceUnavailable", "message": "OpenRouter API is unavailable. Please try again later."},
        )

    except TimeoutError as e:
        # OpenRouter API timeout (>30s)
        logger.error(f"OpenRouter timeout: {e}", extra={"request_id": request_id})
        raise HTTPException(status_code=408, detail={"error": "RequestTimeout", "message": "Request timed out after 30 seconds"})

    except Exception as e:
        # Unexpected errors
        logger.exception(f"Translate failed: {e}", extra={"request_id": request_id})
        raise HTTPException(status_code=500, detail={"error": "InternalServerError", "message": str(e)})


# ============================================================================
# POST /api/rag/translate-chunk - Translate Search Result Chunk (RAG-appropriate)
# ============================================================================

@router.post(
    "/translate-chunk",
    response_model=TranslateResponse,
    summary="Translate search result chunk to plain English (RAG-appropriate)",
    description="Translate a single search result chunk (500-1000 chars) to plain English",
    responses={
        200: {"description": "Translation generated successfully", "model": TranslateResponse},
        400: {"description": "Invalid reading level or empty chunk_text"},
        408: {"description": "OpenRouter API timeout"},
        429: {"description": "Rate limit exceeded"},
    },
)
async def translate_chunk(
    request: TranslateChunkRequest,
    user: dict = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
) -> TranslateResponse:
    """
    Translate a search result chunk to plain English (RAG-appropriate).

    This is the PROPER RAG approach:
    - Frontend sends chunk_text from search results
    - Translates only that chunk (fast, cheap)
    - No full-document reconstruction

    Args:
        request: TranslateChunkRequest with chunk_text, title, url, reading_level
        user: Authenticated user
        db: Database session

    Returns:
        TranslateResponse with translated_text, reading_level, model_used
    """
    request_id = str(uuid.uuid4())
    user_id = user.get("user_id") if user else "anonymous"

    # Generate cache key from chunk_text hash
    chunk_hash = hashlib.md5(request.chunk_text.encode()).hexdigest()[:16]

    logger.info(
        f"Translate chunk request (T016-RAG)",
        extra={
            "request_id": request_id,
            "chunk_hash": chunk_hash,
            "reading_level": request.reading_level,
            "chunk_length": len(request.chunk_text),
        },
    )

    # Validate reading_level
    allowed_levels = ["grade6", "grade8", "grade10"]
    if request.reading_level not in allowed_levels:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "ValidationError",
                "message": f"reading_level must be one of {allowed_levels}, got '{request.reading_level}'",
            },
        )

    # Validate chunk_text
    if not request.chunk_text or len(request.chunk_text.strip()) == 0:
        raise HTTPException(
            status_code=400,
            detail={"error": "ValidationError", "message": "chunk_text must be non-empty"},
        )

    # Initialize OpenRouter service
    openrouter_service = OpenRouterService(db)

    metadata = {
        "title": request.title,
        "url": request.url,
        "document_type": "guidance"
    }

    try:
        # Generate translation (uses chunk_hash for caching)
        # T024: Pass model parameter for dynamic model-aware chunking
        result = await openrouter_service.translate(
            document_id=chunk_hash,
            document_text=request.chunk_text,
            reading_level=request.reading_level,
            model=request.model,  # Feature 024: Model parameter from frontend
            user_id=user_id,
            metadata=metadata
        )

        logger.info(
            f"Chunk translation generated",
            extra={
                "request_id": request_id,
                "chunk_hash": chunk_hash,
                "cached": result.get("cached", False),
            },
        )

        return TranslateResponse(**result)

    except ValueError as e:
        raise HTTPException(status_code=400, detail={"error": "ValidationError", "message": str(e)})
    except ConnectionError:
        raise HTTPException(status_code=503, detail={"error": "ServiceUnavailable", "message": "OpenRouter API unavailable"})
    except TimeoutError:
        raise HTTPException(status_code=408, detail={"error": "RequestTimeout", "message": "Request timed out after 30 seconds"})
    except Exception as e:
        logger.exception(f"Translate failed: {e}")
        raise HTTPException(status_code=500, detail={"error": "InternalServerError", "message": str(e)})
