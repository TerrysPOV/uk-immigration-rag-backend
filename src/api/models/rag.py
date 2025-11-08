"""
Pydantic models for RAG API endpoints (T016).

Models align with spec.md Key Entities and Functional Requirements:
- RAGQuery: User's natural language question (FR-001)
- DocumentResult: Single document excerpt with metadata
- QueryResult: Ranked list of results (FR-001, FR-004)
- HealthStatus: System health check response (FR-002, FR-006, FR-007, FR-008)
- ReindexRequest: Reindexing trigger parameters (FR-003)
- ReindexResponse: Reindexing job status (FR-003, FR-004)

All models use proper HTTP status codes and JSON serialization per FR-004.
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, validator
from datetime import datetime
from enum import Enum


# ============================================================================
# POST /api/rag/query Models (FR-001, FR-004, FR-005)
# ============================================================================

class RAGQuery(BaseModel):
    """
    User's natural language question about UK immigration.
    
    Corresponds to spec.md Key Entity: RAG Query
    """
    query: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Natural language question about UK immigration guidance"
    )
    
    top_k: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Number of results to return after reranking"
    )
    
    filters: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional metadata filters (document_type, date_range, etc.)"
    )
    
    enable_hybrid_search: Optional[bool] = Field(
        default=None,
        description="Override RAG_HYBRID_SEARCH_ENABLED env var"
    )
    
    enable_reranking: Optional[bool] = Field(
        default=None,
        description="Override RAG_RERANKING_ENABLED env var"
    )
    
    @validator('query')
    def validate_query_not_empty(cls, v):
        """Ensure query is not just whitespace."""
        if not v.strip():
            raise ValueError("Query cannot be empty or whitespace only")
        return v.strip()
    
    class Config:
        json_schema_extra = {
            "example": {
                "query": "How do I apply for a UK work visa?",
                "top_k": 5,
                "filters": {"document_type": "guidance"},
                "enable_hybrid_search": True,
                "enable_reranking": True
            }
        }


class DocumentResult(BaseModel):
    """
    Single document excerpt from UK immigration guidance.
    
    Corresponds to spec.md Key Entity: Immigration Document
    """
    content: str = Field(
        ...,
        description="Document excerpt text"
    )
    
    score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Relevance score (0.0-1.0, higher is more relevant)"
    )
    
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Document metadata (title, URL, published_date, document_type)"
    )
    
    title: Optional[str] = Field(
        default=None,
        description="Document title (extracted from metadata)"
    )
    
    url: Optional[str] = Field(
        default=None,
        description="Source URL on gov.uk (extracted from metadata)"
    )
    
    published_date: Optional[str] = Field(
        default=None,
        description="Publication date (extracted from metadata)"
    )
    
    document_type: Optional[str] = Field(
        default=None,
        description="Document type: guidance, form, policy, etc."
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "content": "To apply for a Skilled Worker visa, you must have a job offer...",
                "score": 0.8542,
                "metadata": {
                    "title": "Skilled Worker visa",
                    "url": "https://www.gov.uk/skilled-worker-visa",
                    "published_date": "2024-01-15",
                    "document_type": "guidance"
                },
                "title": "Skilled Worker visa",
                "url": "https://www.gov.uk/skilled-worker-visa",
                "published_date": "2024-01-15",
                "document_type": "guidance"
            }
        }


class QueryResult(BaseModel):
    """
    Ranked list of document excerpts relevant to user's question.
    
    Corresponds to spec.md Key Entity: Query Result
    HTTP 200 response for POST /api/rag/query (FR-001, FR-004)
    """
    results: List[DocumentResult] = Field(
        ...,
        description="Ranked list of relevant document excerpts"
    )
    
    took_ms: float = Field(
        ...,
        ge=0.0,
        description="Query execution time in milliseconds (FR-005: <2000ms p95)"
    )
    
    total_results: int = Field(
        ...,
        ge=0,
        description="Total number of results returned"
    )
    
    query_preprocessed: bool = Field(
        default=False,
        description="Whether query preprocessing was applied"
    )
    
    hybrid_search_used: bool = Field(
        default=False,
        description="Whether BM25 hybrid search was used"
    )
    
    reranking_used: bool = Field(
        default=False,
        description="Whether cross-encoder reranking was used"
    )
    
    @validator('took_ms')
    def warn_slow_query(cls, v):
        """Log warning if query exceeds 2s target (FR-005)."""
        if v > 2000:
            import logging
            logging.warning(f"Query latency {v:.0f}ms exceeds 2s target (FR-005)")
        return v
    
    class Config:
        json_schema_extra = {
            "example": {
                "results": [
                    {
                        "content": "To apply for a Skilled Worker visa...",
                        "score": 0.8542,
                        "metadata": {"title": "Skilled Worker visa"},
                        "title": "Skilled Worker visa",
                        "url": "https://www.gov.uk/skilled-worker-visa"
                    }
                ],
                "took_ms": 1250.5,
                "total_results": 1,
                "query_preprocessed": True,
                "hybrid_search_used": True,
                "reranking_used": True
            }
        }


# ============================================================================
# GET /api/rag/health Models (FR-002, FR-006, FR-007, FR-008)
# ============================================================================

class HealthStatus(BaseModel):
    """
    System health check response.
    
    HTTP 200 response for GET /api/rag/health (FR-002)
    Reports binary quantization status (FR-006, FR-008) and memory usage (FR-007)
    """
    status: str = Field(
        ...,
        description="Overall system status: healthy, degraded, unhealthy"
    )
    
    document_count: int = Field(
        ...,
        ge=0,
        description="Number of documents indexed (FR-014: should be 775)"
    )
    
    quantization_active: bool = Field(
        ...,
        description="Whether binary quantization is enabled (FR-006)"
    )
    
    compression_ratio: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Compression ratio achieved (FR-006: should be >=0.97)"
    )
    
    memory_mb: float = Field(
        ...,
        ge=0.0,
        description="Total memory footprint in MB (FR-007: must be <500MB)"
    )
    
    qdrant_status: str = Field(
        default="unknown",
        description="Qdrant connection status: connected, disconnected, error"
    )
    
    deepinfra_status: str = Field(
        default="unknown",
        description="DeepInfra API status: available, unavailable, error"
    )
    
    bm25_index_status: str = Field(
        default="unknown",
        description="BM25 Whoosh index status: loaded, missing, error"
    )
    
    pipeline_components: List[str] = Field(
        default_factory=list,
        description="Active pipeline components"
    )
    
    last_check: datetime = Field(
        default_factory=datetime.utcnow,
        description="Timestamp of health check"
    )
    
    @validator('compression_ratio')
    def validate_compression(cls, v, values):
        """Warn if compression ratio below 97% threshold (FR-006, FR-008)."""
        if v < 0.97:
            import logging
            logging.warning(f"Compression ratio {v:.2%} below 97% threshold (FR-006)")
        return v
    
    @validator('memory_mb')
    def validate_memory(cls, v):
        """Warn if memory usage exceeds 500MB threshold (FR-007)."""
        if v > 500:
            import logging
            logging.warning(f"Memory usage {v:.0f}MB exceeds 500MB threshold (FR-007)")
        return v
    
    class Config:
        json_schema_extra = {
            "example": {
                "status": "healthy",
                "document_count": 775,
                "quantization_active": True,
                "compression_ratio": 0.97,
                "memory_mb": 194.5,
                "qdrant_status": "connected",
                "deepinfra_status": "available",
                "bm25_index_status": "loaded",
                "pipeline_components": ["query_preprocessor", "embedder", "retriever", "bm25_ranker", "reranker"],
                "last_check": "2025-10-04T12:34:56.789Z"
            }
        }


# ============================================================================
# POST /api/rag/reindex Models (FR-003, FR-016)
# ============================================================================

class ReindexRequest(BaseModel):
    """
    Request to trigger document reindexing.
    
    HTTP request body for POST /api/rag/reindex (FR-003)
    """
    force: bool = Field(
        default=False,
        description="Force reindex even if documents haven't changed"
    )
    
    source_filter: Optional[str] = Field(
        default=None,
        description="Only reindex documents matching source filter (e.g., 'guidance', 'forms')"
    )
    
    clear_existing: bool = Field(
        default=False,
        description="Clear existing index before reindexing (destructive operation)"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "force": False,
                "source_filter": "guidance",
                "clear_existing": False
            }
        }


class ReindexStatus(str, Enum):
    """Reindexing job status."""
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ReindexResponse(BaseModel):
    """
    Response from reindexing operation.
    
    HTTP 202 response for POST /api/rag/reindex (FR-003, FR-004)
    """
    job_id: str = Field(
        ...,
        description="Unique job ID for tracking reindex operation"
    )
    
    status: ReindexStatus = Field(
        ...,
        description="Current status of reindexing job"
    )
    
    message: str = Field(
        default="Reindexing job queued successfully",
        description="Human-readable status message"
    )
    
    estimated_duration_seconds: Optional[int] = Field(
        default=None,
        description="Estimated time to completion in seconds"
    )
    
    progress_pct: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=100.0,
        description="Completion percentage (0-100)"
    )
    
    documents_processed: Optional[int] = Field(
        default=None,
        ge=0,
        description="Number of documents processed so far"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "job_id": "550e8400-e29b-41d4-a716-446655440000",
                "status": "queued",
                "message": "Reindexing job queued successfully",
                "estimated_duration_seconds": 180,
                "progress_pct": 0.0,
                "documents_processed": 0
            }
        }


# ============================================================================
# Error Response Models (FR-004)
# ============================================================================

class ErrorDetail(BaseModel):
    """Detailed error information."""
    field: Optional[str] = Field(
        default=None,
        description="Field name that caused the error (for validation errors)"
    )
    message: str = Field(
        ...,
        description="Error message"
    )
    error_code: Optional[str] = Field(
        default=None,
        description="Machine-readable error code"
    )


class ErrorResponse(BaseModel):
    """
    Standard error response for all endpoints.
    
    HTTP 400, 500, 503 responses (FR-004)
    """
    error: str = Field(
        ...,
        description="Error type or category"
    )
    
    message: str = Field(
        ...,
        description="Human-readable error message"
    )
    
    details: Optional[List[ErrorDetail]] = Field(
        default=None,
        description="Detailed error information (e.g., validation errors)"
    )
    
    request_id: Optional[str] = Field(
        default=None,
        description="Request ID for debugging"
    )
    
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="Error timestamp"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "error": "ValidationError",
                "message": "Query validation failed",
                "details": [
                    {
                        "field": "query",
                        "message": "Query cannot be empty or whitespace only",
                        "error_code": "EMPTY_QUERY"
                    }
                ],
                "request_id": "req-123456",
                "timestamp": "2025-10-04T12:34:56.789Z"
            }
        }
