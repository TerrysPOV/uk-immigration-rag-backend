"""
FastAPI routes for Neo4J Graph endpoints (NEO4J-001).

Implements graph-related HTTP endpoints:
- POST /api/rag/graph/extract: Trigger entity extraction and graph population
- GET /api/rag/graph/stats: Get graph statistics
- POST /api/rag/query-graph: RAG query with graph traversal
- GET /api/rag/graph/entity/{entity_id}: Get entity details
- GET /api/rag/graph/visualize/{entity_id}: Get visualization data
- GET /api/rag/graph/search: Search entities

All endpoints return JSON with appropriate HTTP status codes.
"""

import os
import logging
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, status, BackgroundTasks, Depends, Query
from pydantic import BaseModel, Field

from src.services.neo4j_graph_service import get_graph_service
from src.services.neo4j_graph_retriever import get_graph_retriever
from src.middleware.rbac import get_current_user, get_current_user_optional

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/api/rag/graph", tags=["Graph"])


# ============================================================================
# Request/Response Models
# ============================================================================


class GraphExtractionRequest(BaseModel):
    """Request to trigger graph extraction."""

    document_ids: Optional[List[str]] = Field(
        None, description="Document IDs to extract (None = all documents)"
    )
    enable_llm_extraction: bool = Field(
        True, description="Enable LLM-based extraction for complex entities"
    )


class GraphExtractionResponse(BaseModel):
    """Response from graph extraction trigger."""

    job_id: str = Field(..., description="Job ID for tracking extraction progress")
    status: str = Field(..., description="Job status (queued, running, completed, failed)")
    message: str = Field(..., description="Human-readable status message")


class GraphStatsResponse(BaseModel):
    """Graph statistics response."""

    node_counts: Dict[str, int] = Field(..., description="Node counts by type")
    relationship_counts: Dict[str, int] = Field(..., description="Relationship counts by type")
    total_nodes: int = Field(..., description="Total number of nodes")
    total_relationships: int = Field(..., description="Total number of relationships")
    graph_density: float = Field(..., description="Graph density (0-1)")
    last_updated: str = Field(..., description="Last update timestamp (ISO format)")


class GraphHealthResponse(BaseModel):
    """Graph health check response."""

    status: str = Field(..., description="Health status (healthy, degraded, unhealthy, error)")
    orphaned_nodes: int = Field(0, description="Number of orphaned nodes")
    broken_references: int = Field(0, description="Number of broken chunk_id references")
    warnings: List[str] = Field(default_factory=list, description="Health warnings")
    errors: List[str] = Field(default_factory=list, description="Health errors")
    timestamp: str = Field(..., description="Check timestamp (ISO format)")


class QueryGraphRequest(BaseModel):
    """Request for graph-augmented RAG query."""

    query: str = Field(..., min_length=1, max_length=1000, description="Natural language query")
    use_graph: bool = Field(True, description="Enable graph traversal retrieval")
    max_graph_depth: int = Field(3, ge=1, le=5, description="Maximum graph traversal depth")
    top_k: int = Field(5, ge=1, le=100, description="Number of results to return")


class QueryGraphResponse(BaseModel):
    """Response for graph-augmented query."""

    query: str = Field(..., description="Original query")
    results: List[Dict[str, Any]] = Field(..., description="Retrieved documents")
    graph_paths: List[Dict[str, Any]] = Field(
        default_factory=list, description="Graph traversal paths (for explainability)"
    )
    took_ms: float = Field(..., description="Query execution time in milliseconds")


class EntityDetailsResponse(BaseModel):
    """Entity details response."""

    id: str = Field(..., description="Entity ID")
    labels: List[str] = Field(..., description="Entity labels/types")
    properties: Dict[str, Any] = Field(..., description="Entity properties")
    relationships: Dict[str, List[Dict[str, Any]]] = Field(
        ..., description="Incoming and outgoing relationships"
    )


class VisualizationDataResponse(BaseModel):
    """Visualization data response."""

    nodes: List[Dict[str, Any]] = Field(..., description="Graph nodes")
    edges: List[Dict[str, Any]] = Field(..., description="Graph edges")


class EntitySearchRequest(BaseModel):
    """Entity search request."""

    search_term: str = Field(..., min_length=1, max_length=200, description="Search query")
    entity_types: Optional[List[str]] = Field(
        None, max_items=10, description="Filter by entity types"
    )
    limit: int = Field(20, ge=1, le=100, description="Maximum results")


class EntitySearchResponse(BaseModel):
    """Entity search response."""

    results: List[Dict[str, Any]] = Field(..., description="Matching entities")
    total: int = Field(..., description="Total number of results")


# ============================================================================
# Helper Functions
# ============================================================================


def get_neo4j_config() -> Dict[str, str]:
    """
    Get Neo4J configuration from environment variables.

    Returns:
        Dictionary with neo4j_uri, neo4j_user, neo4j_password, neo4j_database

    Raises:
        HTTPException: If required environment variables are missing
    """
    neo4j_uri = os.getenv("NEO4J_URI")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD")
    neo4j_database = os.getenv("NEO4J_DATABASE", "neo4j")

    if not neo4j_uri:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Neo4J not configured. Set NEO4J_URI environment variable.",
        )

    if not neo4j_password:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Neo4J not configured. Set NEO4J_PASSWORD environment variable.",
        )

    return {
        "neo4j_uri": neo4j_uri,
        "neo4j_user": neo4j_user,
        "neo4j_password": neo4j_password,
        "neo4j_database": neo4j_database,
    }


# ============================================================================
# Endpoints
# ============================================================================


@router.post(
    "/extract", status_code=status.HTTP_202_ACCEPTED, response_model=GraphExtractionResponse
)
async def trigger_graph_extraction(
    request: GraphExtractionRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
):
    """
    Trigger entity extraction and graph population.

    Background task processes documents in batches.
    Returns job_id for status checking.

    NOTE: This is a simplified version that returns immediately.
    In production, this would queue a Celery task for async processing.
    """
    try:
        # Validate Neo4J configuration is available
        get_neo4j_config()

        # For now, return a placeholder job ID
        # In production, this would queue a Celery task
        import uuid

        job_id = str(uuid.uuid4())

        logger.info(
            f"Graph extraction requested (job_id={job_id}, "
            f"document_ids={request.document_ids}, "
            f"llm_extraction={request.enable_llm_extraction})"
        )

        return GraphExtractionResponse(
            job_id=job_id,
            status="queued",
            message=f"Graph extraction queued. Processing {len(request.document_ids) if request.document_ids else 'all'} documents.",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error triggering graph extraction: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to trigger graph extraction: {str(e)}",
        )


@router.get("/stats", response_model=GraphStatsResponse)
async def get_graph_statistics():
    """
    Return Neo4J graph statistics.

    Returns node counts, relationship counts, graph density, etc.
    """
    try:
        config = get_neo4j_config()
        graph_service = get_graph_service(**config)

        stats = graph_service.get_graph_statistics()

        return GraphStatsResponse(**stats)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting graph statistics: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get graph statistics: {str(e)}",
        )


@router.get("/health", response_model=GraphHealthResponse)
async def get_graph_health():
    """
    Perform Neo4J graph health check.

    Checks for:
    - Orphaned nodes (no relationships)
    - Broken chunk_id references
    - Connection status
    """
    try:
        config = get_neo4j_config()
        graph_service = get_graph_service(**config)

        health = graph_service.health_check()

        return GraphHealthResponse(**health)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error checking graph health: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to check graph health: {str(e)}",
        )


@router.post("/query", response_model=QueryGraphResponse)
async def query_with_graph(
    request: QueryGraphRequest, user: dict = Depends(get_current_user_optional)
):
    """
    RAG query with optional graph traversal.

    Combines vector search with graph traversal for improved results.
    Returns documents and graph traversal paths for explainability.
    """
    try:
        import time

        start_time = time.time()

        config = get_neo4j_config()

        if not request.use_graph:
            # Graph retrieval disabled, return empty results
            return QueryGraphResponse(
                query=request.query,
                results=[],
                graph_paths=[],
                took_ms=(time.time() - start_time) * 1000,
            )

        # Get graph retriever
        graph_retriever = get_graph_retriever(
            neo4j_uri=config["neo4j_uri"],
            neo4j_user=config["neo4j_user"],
            neo4j_password=config["neo4j_password"],
            neo4j_database=config["neo4j_database"],
            max_depth=request.max_graph_depth,
            top_k=request.top_k,
        )

        # Run graph retrieval
        result = graph_retriever.run(query=request.query)

        # Convert documents to dict format
        results = []
        for doc in result["documents"]:
            results.append(
                {
                    "id": doc.id,
                    "content": doc.content,
                    "metadata": doc.meta if doc.meta else {},
                }
            )

        took_ms = (time.time() - start_time) * 1000

        return QueryGraphResponse(
            query=request.query,
            results=results,
            graph_paths=result["graph_paths"],
            took_ms=took_ms,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error querying with graph: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Graph query failed: {str(e)}",
        )


@router.get("/entity/{entity_id}", response_model=EntityDetailsResponse)
async def get_entity_details(entity_id: str):
    """
    Get details about a specific graph entity.

    Returns entity properties, labels, and relationships.
    """
    try:
        config = get_neo4j_config()
        graph_service = get_graph_service(**config)

        entity = graph_service.get_entity_details(entity_id)

        if not entity:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Entity {entity_id} not found"
            )

        return EntityDetailsResponse(**entity)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting entity details: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get entity details: {str(e)}",
        )


@router.get("/visualize/{entity_id}", response_model=VisualizationDataResponse)
async def visualize_entity_graph(
    entity_id: str, depth: int = Query(2, ge=1, le=4, description="Traversal depth")
):
    """
    Return graph data for visualization (nodes, edges).

    Frontend can render using D3.js, Cytoscape.js, or vis.js.
    """
    try:
        config = get_neo4j_config()
        graph_service = get_graph_service(**config)

        viz_data = graph_service.get_visualization_data(entity_id, depth)

        return VisualizationDataResponse(**viz_data)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting visualization data: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get visualization data: {str(e)}",
        )


@router.post("/search", response_model=EntitySearchResponse)
async def search_entities(
    request: EntitySearchRequest, user: dict = Depends(get_current_user_optional)
):
    """
    Search for entities by text/name.

    Optionally filter by entity types.
    """
    try:
        config = get_neo4j_config()
        graph_service = get_graph_service(**config)

        results = graph_service.search_entities(
            search_term=request.search_term,
            entity_types=request.entity_types,
            limit=request.limit,
        )

        return EntitySearchResponse(results=results, total=len(results))

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error searching entities: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Entity search failed: {str(e)}",
        )
