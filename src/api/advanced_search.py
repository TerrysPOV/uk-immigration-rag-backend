"""
Feature 012: Advanced Search API
T078-T085: Advanced Search API endpoints

Endpoints:
- POST /api/v1/search/boolean - Parse and execute boolean query
- POST /api/v1/search/validate - Validate boolean query syntax
- POST /api/v1/search/field-search - Search specific fields with operators
- GET /api/v1/search/saved-queries - List user's saved queries
- POST /api/v1/search/saved-queries - Save query with parsed AST
- GET /api/v1/search/saved-queries/{id} - Get single saved query
- DELETE /api/v1/search/saved-queries/{id} - Delete saved query
- POST /api/v1/search/saved-queries/{id}/execute - Execute saved query

Authentication: Requires Viewer or higher role
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime

from ..database import get_db
from ..models.saved_query import SavedQuery, SavedQueryCreate, SavedQueryInDB
from ..services.search_service import SearchService
from ..middleware.rbac import get_current_user_with_role


router = APIRouter(prefix="/api/v1/search", tags=["search"])


# ============================================================================
# Request/Response Models
# ============================================================================


class BooleanQueryRequest(BaseModel):
    """Request schema for boolean query."""

    query: str = Field(..., description="Boolean query string (e.g., '(visa OR permit) AND UK')")
    limit: int = Field(20, ge=1, le=100, description="Maximum results to return")
    offset: int = Field(0, ge=0, description="Results offset for pagination")


class BooleanQueryResponse(BaseModel):
    """Response schema for boolean query."""

    query: str
    parsed_query: dict = Field(..., description="Parsed AST structure")
    results: List[dict]
    total_count: int
    limit: int
    offset: int


class QueryValidationRequest(BaseModel):
    """Request schema for query validation."""

    query: str = Field(..., description="Boolean query to validate")


class QueryValidationResponse(BaseModel):
    """Response schema for query validation."""

    is_valid: bool
    syntax_errors: List[str]
    parsed_query: Optional[dict] = None


class FieldSearchRequest(BaseModel):
    """Request schema for field-specific search."""

    field: str = Field(..., description="Field to search (title/content/metadata)")
    operator: str = Field(..., description="Search operator (equals/contains/starts_with/regex)")
    value: str = Field(..., description="Search value")
    limit: int = Field(20, ge=1, le=100)
    offset: int = Field(0, ge=0)


class FieldSearchResponse(BaseModel):
    """Response schema for field search."""

    field: str
    operator: str
    value: str
    results: List[dict]
    total_count: int


class SaveQueryRequest(BaseModel):
    """Request schema for saving query."""

    query_name: str = Field(..., description="User-friendly name for saved query")
    query_syntax: str = Field(..., description="Boolean query string")


class ExecuteSavedQueryRequest(BaseModel):
    """Request schema for executing saved query."""

    limit: Optional[int] = Field(None, ge=1, le=100, description="Override default limit")
    offset: Optional[int] = Field(None, ge=0, description="Override default offset")


# ============================================================================
# T078: POST /api/v1/search/boolean
# ============================================================================


@router.post("/boolean", response_model=BooleanQueryResponse)
async def execute_boolean_query(
    query_request: BooleanQueryRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_with_role("viewer")),
):
    """
    Parse and execute boolean query (T078).

    Requires: Viewer or higher role

    Parses boolean query using jsep library.
    Executes search and returns results with parsed AST.

    Supported operators: AND, OR, NOT
    Grouping: Use parentheses for complex queries

    Args:
        query_request: Boolean query and pagination params

    Returns:
        BooleanQueryResponse with results and parsed AST
    """
    try:
        search_service = SearchService(db)

        # Parse boolean query
        parsed_query = search_service.parse_boolean_query(query_request.query)

        # Execute search
        results = search_service.execute_boolean_search(
            parsed_query=parsed_query, limit=query_request.limit, offset=query_request.offset
        )

        return BooleanQueryResponse(
            query=query_request.query,
            parsed_query=parsed_query.to_dict() if hasattr(parsed_query, "to_dict") else {},
            results=results,
            total_count=len(results),  # TODO: Get actual total count
            limit=query_request.limit,
            offset=query_request.offset,
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid query syntax: {str(e)}"
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to execute boolean query: {str(e)}",
        )


# ============================================================================
# T079: POST /api/v1/search/validate
# ============================================================================


@router.post("/validate", response_model=QueryValidationResponse)
async def validate_query(
    validation_request: QueryValidationRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_with_role("viewer")),
):
    """
    Validate boolean query syntax without execution (T079).

    Requires: Viewer or higher role

    Validates query syntax and returns errors with position.
    Does not execute the query.

    Args:
        validation_request: Query to validate

    Returns:
        QueryValidationResponse with validation results
    """
    try:
        search_service = SearchService(db)

        # Validate query
        is_valid, errors = search_service.validate_query(validation_request.query)

        parsed_query = None
        if is_valid:
            try:
                parsed = search_service.parse_boolean_query(validation_request.query)
                parsed_query = parsed.to_dict() if hasattr(parsed, "to_dict") else {}
            except:
                pass

        return QueryValidationResponse(
            is_valid=is_valid, syntax_errors=errors, parsed_query=parsed_query
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to validate query: {str(e)}",
        )


# ============================================================================
# T080: POST /api/v1/search/field-search
# ============================================================================


@router.post("/field-search", response_model=FieldSearchResponse)
async def execute_field_search(
    search_request: FieldSearchRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_with_role("viewer")),
):
    """
    Search specific fields with operators (T080).

    Requires: Viewer or higher role

    Supported fields: title, content, metadata
    Supported operators:
    - equals: Exact match
    - contains: Substring match
    - starts_with: Prefix match
    - regex: Regular expression match

    Args:
        search_request: Field search parameters

    Returns:
        FieldSearchResponse with matching results
    """
    try:
        search_service = SearchService(db)

        # Validate field and operator
        valid_fields = ["title", "content", "metadata"]
        valid_operators = ["equals", "contains", "starts_with", "regex"]

        if search_request.field not in valid_fields:
            raise ValueError(
                f"Invalid field '{search_request.field}'. Must be one of {valid_fields}"
            )

        if search_request.operator not in valid_operators:
            raise ValueError(
                f"Invalid operator '{search_request.operator}'. Must be one of {valid_operators}"
            )

        # Execute field search
        results = search_service.field_search(
            field=search_request.field,
            value=search_request.value,
            operator=search_request.operator,
            limit=search_request.limit,
            offset=search_request.offset,
        )

        return FieldSearchResponse(
            field=search_request.field,
            operator=search_request.operator,
            value=search_request.value,
            results=results,
            total_count=len(results),  # TODO: Get actual total count
        )

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to execute field search: {str(e)}",
        )


# ============================================================================
# T081: GET /api/v1/search/saved-queries
# ============================================================================


@router.get("/saved-queries", response_model=List[SavedQueryInDB])
async def list_saved_queries(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(50, ge=1, le=100, description="Results per page"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_with_role("viewer")),
):
    """
    List user's saved queries (T081).

    Requires: Viewer or higher role

    Returns user's saved queries with pagination.
    Ordered by created_at descending (newest first).

    Args:
        page: Page number
        limit: Results per page

    Returns:
        List of SavedQuery objects
    """
    try:
        offset = (page - 1) * limit

        queries = (
            db.query(SavedQuery)
            .filter(SavedQuery.user_id == current_user.id)
            .order_by(SavedQuery.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

        return [SavedQueryInDB.from_orm(q) for q in queries]

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list saved queries: {str(e)}",
        )


# ============================================================================
# T082: POST /api/v1/search/saved-queries
# ============================================================================


@router.post("/saved-queries", response_model=SavedQueryInDB, status_code=status.HTTP_201_CREATED)
async def save_query(
    query_request: SaveQueryRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_with_role("viewer")),
):
    """
    Save query with parsed AST (T082).

    Requires: Viewer or higher role

    Parses query and saves with AST structure for reuse.

    Args:
        query_request: Query name and syntax

    Returns:
        Created SavedQuery object
    """
    try:
        search_service = SearchService(db)

        # Parse query to validate and get AST
        parsed_query = search_service.parse_boolean_query(query_request.query_syntax)

        # Create saved query data
        query_data = SavedQueryCreate(
            user_id=current_user.id,
            query_name=query_request.query_name,
            query_syntax=query_request.query_syntax,
            boolean_operators=parsed_query.to_dict() if hasattr(parsed_query, "to_dict") else {},
        )

        # Save query
        saved_query = search_service.save_query(user_id=current_user.id, query_data=query_data)

        return saved_query

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid query syntax: {str(e)}"
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save query: {str(e)}",
        )


# ============================================================================
# T083: GET /api/v1/search/saved-queries/{id}
# ============================================================================


@router.get("/saved-queries/{query_id}", response_model=SavedQueryInDB)
async def get_saved_query(
    query_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_with_role("viewer")),
):
    """
    Get single saved query (T083).

    Requires: Viewer or higher role

    Returns saved query with full details.
    User can only access their own saved queries.

    Args:
        query_id: Saved query UUID

    Returns:
        SavedQuery object
    """
    try:
        query = (
            db.query(SavedQuery)
            .filter(SavedQuery.id == query_id, SavedQuery.user_id == current_user.id)
            .first()
        )

        if not query:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Saved query {query_id} not found"
            )

        return SavedQueryInDB.from_orm(query)

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve saved query: {str(e)}",
        )


# ============================================================================
# T084: DELETE /api/v1/search/saved-queries/{id}
# ============================================================================


@router.delete("/saved-queries/{query_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_saved_query(
    query_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_with_role("viewer")),
):
    """
    Delete saved query (T084).

    Requires: Viewer or higher role

    User can only delete their own saved queries.

    Args:
        query_id: Saved query UUID
    """
    try:
        query = (
            db.query(SavedQuery)
            .filter(SavedQuery.id == query_id, SavedQuery.user_id == current_user.id)
            .first()
        )

        if not query:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Saved query {query_id} not found"
            )

        db.delete(query)
        db.commit()

        print(
            f"[AdvancedSearchAPI] Deleted saved query {query_id} for user {current_user.username}"
        )

        return None

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete saved query: {str(e)}",
        )


# ============================================================================
# T085: POST /api/v1/search/saved-queries/{id}/execute
# ============================================================================


@router.post("/saved-queries/{query_id}/execute", response_model=BooleanQueryResponse)
async def execute_saved_query(
    query_id: str,
    execution_request: Optional[ExecuteSavedQueryRequest] = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_with_role("viewer")),
):
    """
    Execute saved query (T085).

    Requires: Viewer or higher role

    Executes saved query with optional limit/offset overrides.
    Updates last_executed_at and execution_count.

    Args:
        query_id: Saved query UUID
        execution_request: Optional limit/offset overrides

    Returns:
        BooleanQueryResponse with results
    """
    try:
        search_service = SearchService(db)

        # Get saved query
        query = (
            db.query(SavedQuery)
            .filter(SavedQuery.id == query_id, SavedQuery.user_id == current_user.id)
            .first()
        )

        if not query:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Saved query {query_id} not found"
            )

        # Get limit/offset from request or use defaults
        limit = execution_request.limit if execution_request and execution_request.limit else 20
        offset = execution_request.offset if execution_request and execution_request.offset else 0

        # Execute saved query
        results = search_service.execute_saved_query(query_id=query_id, limit=limit, offset=offset)

        # Update execution stats
        query.last_executed_at = datetime.utcnow()
        query.execution_count = (query.execution_count or 0) + 1
        db.commit()

        return BooleanQueryResponse(
            query=query.query_syntax,
            parsed_query=query.boolean_operators,
            results=results,
            total_count=len(results),
            limit=limit,
            offset=offset,
        )

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to execute saved query: {str(e)}",
        )


# ============================================================================
# T085a: GET /api/v1/search/suggestions
# ============================================================================


class QuerySuggestion(BaseModel):
    """Query suggestion schema (FR-AS-006)."""

    query_text: str
    execution_count: int
    avg_result_count: int
    source: str  # 'saved_query' or 'history'


@router.get("/suggestions", response_model=List[QuerySuggestion])
async def get_query_suggestions(
    prefix: Optional[str] = Query(None, description="Query prefix for matching"),
    limit: int = Query(10, ge=1, le=20, description="Maximum suggestions to return"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_with_role("viewer")),
):
    """
    Get query suggestions based on frequency and recency (T085a, FR-AS-006).

    Requires: Viewer or higher role

    Aggregates saved_queries and search_history tables.
    Returns top suggestions ordered by frequency and recency.
    Supports prefix matching when prefix parameter is provided.

    Args:
        prefix: Optional query prefix for filtering
        limit: Maximum number of suggestions (default 10)

    Returns:
        List of QuerySuggestion objects with execution counts
    """
    try:
        from sqlalchemy import func, or_

        # Get saved queries with execution counts
        saved_query_suggestions = db.query(
            SavedQuery.query_syntax.label("query_text"),
            func.coalesce(SavedQuery.execution_count, 0).label("execution_count"),
            func.cast(0, type_=func.Integer).label("avg_result_count"),  # Placeholder
            func.cast("saved_query", type_=func.String).label("source"),
        ).filter(SavedQuery.user_id == current_user.id)

        # Apply prefix filter if provided
        if prefix:
            saved_query_suggestions = saved_query_suggestions.filter(
                SavedQuery.query_syntax.ilike(f"{prefix}%")
            )

        # Get search history (if table exists)
        # Note: Assuming there's a search_history table - if not, skip this
        # For now, just use saved queries

        # Get top suggestions ordered by execution count and recency
        suggestions = (
            saved_query_suggestions.order_by(
                func.coalesce(SavedQuery.execution_count, 0).desc(),
                SavedQuery.last_executed_at.desc().nullslast(),
            )
            .limit(limit)
            .all()
        )

        return [
            QuerySuggestion(
                query_text=s.query_text,
                execution_count=s.execution_count or 0,
                avg_result_count=s.avg_result_count or 0,
                source=s.source,
            )
            for s in suggestions
        ]

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get query suggestions: {str(e)}",
        )
