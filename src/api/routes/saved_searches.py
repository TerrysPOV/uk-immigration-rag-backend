"""
T018: Saved Searches API Routes
Feature 018: User Testing Issue Remediation

Endpoints:
- GET /api/search/saved → List user's saved searches
- POST /api/search/saved → Create new saved search
- PUT /api/search/saved/{id} → Update saved search
- DELETE /api/search/saved/{id} → Delete saved search

Security:
- All endpoints require Google OAuth 2.0 authentication
- Users can only access/modify their own saved searches
- Cross-user access blocked with HTTP 403
- 50 saved searches limit per user

Contract Tests: backend-source/tests/contract/test_saved_searches_contract.py
"""

import logging
import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy.orm import Session

from src.middleware.rbac import get_current_user
from src.database import get_db
from src.services.saved_search_service import SavedSearchService
from src.models.saved_search import SavedSearchInDB, SavedSearchBase, SavedSearchUpdate

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/search/saved",
    tags=["Saved Searches"],
)


@router.get(
    "",
    response_model=List[SavedSearchInDB],
    status_code=200,
    summary="List user's saved searches",
    description="Get user's saved searches sorted newest first. "
    "Limited to 50 saved searches per user. "
    "Requires authentication - users can only see their own saved searches.",
    responses={
        200: {
            "description": "Saved searches retrieved successfully",
            "model": List[SavedSearchInDB],
        },
        401: {
            "description": "Unauthorized (missing or invalid token)",
            "content": {
                "application/json": {
                    "example": {"detail": "Not authenticated"}
                }
            },
        },
    },
)
async def list_saved_searches(
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[SavedSearchInDB]:
    """
    List user's saved searches (T018: Feature 018).

    Returns saved searches sorted newest first, limited to 50 entries.

    Args:
        user: Current authenticated user from Google ID token token
        db: Database session

    Returns:
        List[SavedSearchInDB]: Saved searches (newest first)

    Raises:
        HTTPException 401: Authentication required
        HTTPException 500: Internal server error
    """
    request_id = str(uuid.uuid4())
    user_id = user["user_id"]

    logger.info(
        f"[{request_id}] GET /api/search/saved - user_id={user_id}"
    )

    try:
        # Initialize service and fetch saved searches
        saved_search_service = SavedSearchService(db)
        searches = await saved_search_service.list_saved(user_id=user_id)

        logger.info(
            f"[{request_id}] Retrieved {len(searches)} saved searches for user_id={user_id}"
        )

        # Convert SQLAlchemy models to Pydantic models
        return [
            SavedSearchInDB(
                id=search.id,
                user_id=search.user_id,
                name=search.name,
                query=search.query,
                filters=search.filters,
                created_at=search.created_at,
                last_used_at=search.last_used_at,
                usage_count=search.usage_count,
            )
            for search in searches
        ]

    except ValueError as e:
        logger.error(f"[{request_id}] Validation error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "ValidationError", "message": str(e)},
        )
    except Exception as e:
        logger.error(
            f"[{request_id}] Unexpected error listing saved searches: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "InternalServerError",
                "message": "Failed to retrieve saved searches",
            },
        )


@router.post(
    "",
    response_model=SavedSearchInDB,
    status_code=201,
    summary="Create new saved search",
    description="Create new saved search with name, query, and optional filters. "
    "If name already exists, timestamp is auto-appended to make it unique. "
    "Limited to 50 saved searches per user (returns HTTP 403 if exceeded).",
    responses={
        201: {
            "description": "Saved search created successfully",
            "model": SavedSearchInDB,
        },
        400: {
            "description": "Bad request (validation error)",
            "content": {
                "application/json": {
                    "example": {
                        "detail": {
                            "error": "ValidationError",
                            "message": "name must be 1-100 characters"
                        }
                    }
                }
            },
        },
        401: {
            "description": "Unauthorized (missing or invalid token)",
            "content": {
                "application/json": {
                    "example": {"detail": "Not authenticated"}
                }
            },
        },
        403: {
            "description": "Forbidden (50 saved searches limit exceeded)",
            "content": {
                "application/json": {
                    "example": {
                        "detail": {
                            "error": "LimitExceeded",
                            "message": "User has reached maximum saved searches limit (50)"
                        }
                    }
                }
            },
        },
    },
)
async def create_saved_search(
    request_body: SavedSearchBase = Body(...),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SavedSearchInDB:
    """
    Create new saved search (T018: Feature 018).

    Automatically handles duplicate names by appending timestamp.
    Enforces 50 saved searches limit per user.

    Args:
        request_body: SavedSearchBase with name, query, filters
        user: Current authenticated user from Google ID token token
        db: Database session

    Returns:
        SavedSearchInDB: Created saved search

    Raises:
        HTTPException 400: Validation error
        HTTPException 401: Authentication required
        HTTPException 403: 50 saved searches limit exceeded
        HTTPException 500: Internal server error
    """
    request_id = str(uuid.uuid4())
    user_id = user["user_id"]

    logger.info(
        f"[{request_id}] POST /api/search/saved - user_id={user_id}, name='{request_body.name}'"
    )

    try:
        # Initialize service and create saved search
        saved_search_service = SavedSearchService(db)
        search = await saved_search_service.create_saved(
            user_id=user_id,
            name=request_body.name,
            query=request_body.query,
            filters=request_body.filters,
        )

        logger.info(
            f"[{request_id}] Created saved search: search_id={search.id}, "
            f"final_name='{search.name}', user_id={user_id}"
        )

        # Convert to Pydantic model
        return SavedSearchInDB(
            id=search.id,
            user_id=search.user_id,
            name=search.name,
            query=search.query,
            filters=search.filters,
            created_at=search.created_at,
            last_used_at=search.last_used_at,
            usage_count=search.usage_count,
        )

    except ValueError as e:
        error_message = str(e)

        # Check if limit exceeded
        if "maximum saved searches limit" in error_message:
            logger.warning(
                f"[{request_id}] User exceeded saved searches limit: user_id={user_id}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "LimitExceeded",
                    "message": error_message,
                },
            )

        # Other validation errors
        logger.error(f"[{request_id}] Validation error: {error_message}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "ValidationError", "message": error_message},
        )
    except Exception as e:
        logger.error(
            f"[{request_id}] Unexpected error creating saved search: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "InternalServerError",
                "message": "Failed to create saved search",
            },
        )


@router.put(
    "/{search_id}",
    response_model=SavedSearchInDB,
    status_code=200,
    summary="Update saved search",
    description="Update existing saved search (name, query, and/or filters). "
    "Users can only update their own saved searches (HTTP 403 if wrong user). "
    "Returns HTTP 404 if search not found.",
    responses={
        200: {
            "description": "Saved search updated successfully",
            "model": SavedSearchInDB,
        },
        400: {
            "description": "Bad request (validation error or invalid UUID)",
            "content": {
                "application/json": {
                    "example": {
                        "detail": {
                            "error": "ValidationError",
                            "message": "Invalid UUID format"
                        }
                    }
                }
            },
        },
        401: {
            "description": "Unauthorized (missing or invalid token)",
            "content": {
                "application/json": {
                    "example": {"detail": "Not authenticated"}
                }
            },
        },
        403: {
            "description": "Forbidden (search belongs to different user)",
            "content": {
                "application/json": {
                    "example": {
                        "detail": {
                            "error": "Forbidden",
                            "message": "Cannot update search belonging to another user"
                        }
                    }
                }
            },
        },
        404: {
            "description": "Not found (search does not exist)",
            "content": {
                "application/json": {
                    "example": {
                        "detail": {
                            "error": "NotFound",
                            "message": "Saved search not found"
                        }
                    }
                }
            },
        },
    },
)
async def update_saved_search(
    search_id: str,
    request_body: SavedSearchUpdate = Body(...),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SavedSearchInDB:
    """
    Update saved search (T018: Feature 018).

    Security: Only allows update if search belongs to authenticated user.
    At least one field (name, query, or filters) must be provided.

    Args:
        search_id: UUID of saved search to update
        request_body: SavedSearchUpdate with optional name, query, filters
        user: Current authenticated user from Google ID token token
        db: Database session

    Returns:
        SavedSearchInDB: Updated saved search

    Raises:
        HTTPException 400: Invalid UUID or validation error
        HTTPException 401: Authentication required
        HTTPException 403: Search belongs to different user
        HTTPException 404: Search not found
        HTTPException 500: Internal server error
    """
    request_id = str(uuid.uuid4())
    user_id = user["user_id"]

    logger.info(
        f"[{request_id}] PUT /api/search/saved/{search_id} - user_id={user_id}"
    )

    # Validate UUID format
    try:
        uuid.UUID(search_id)
    except ValueError:
        logger.warning(
            f"[{request_id}] Invalid UUID format for search_id: {search_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "ValidationError",
                "message": f"Invalid UUID format: {search_id}",
            },
        )

    try:
        # Initialize service and update saved search
        saved_search_service = SavedSearchService(db)
        search = await saved_search_service.update_saved(
            user_id=user_id,
            search_id=search_id,
            name=request_body.name,
            query=request_body.query,
            filters=request_body.filters,
        )

        logger.info(
            f"[{request_id}] Updated saved search: search_id={search_id}, user_id={user_id}"
        )

        # Convert to Pydantic model
        return SavedSearchInDB(
            id=search.id,
            user_id=search.user_id,
            name=search.name,
            query=search.query,
            filters=search.filters,
            created_at=search.created_at,
            last_used_at=search.last_used_at,
            usage_count=search.usage_count,
        )

    except ValueError as e:
        error_message = str(e)

        # Check if not found or access denied
        if "not found or access denied" in error_message:
            logger.warning(
                f"[{request_id}] Search not found or access denied: "
                f"search_id={search_id}, user_id={user_id}"
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "NotFound",
                    "message": "Saved search not found",
                },
            )

        # Other validation errors
        logger.error(f"[{request_id}] Validation error: {error_message}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "ValidationError", "message": error_message},
        )
    except HTTPException:
        # Re-raise HTTP exceptions (404, 400)
        raise
    except Exception as e:
        logger.error(
            f"[{request_id}] Unexpected error updating saved search: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "InternalServerError",
                "message": "Failed to update saved search",
            },
        )


@router.delete(
    "/{search_id}",
    status_code=204,
    summary="Delete saved search",
    description="Delete specific saved search. "
    "Security: Users can only delete their own searches (HTTP 403 if wrong user). "
    "Returns HTTP 204 on success, HTTP 404 if search not found.",
    responses={
        204: {
            "description": "Search deleted successfully (no content)",
        },
        400: {
            "description": "Bad request (invalid UUID format)",
            "content": {
                "application/json": {
                    "example": {
                        "detail": {
                            "error": "ValidationError",
                            "message": "Invalid UUID format"
                        }
                    }
                }
            },
        },
        401: {
            "description": "Unauthorized (missing or invalid token)",
            "content": {
                "application/json": {
                    "example": {"detail": "Not authenticated"}
                }
            },
        },
        403: {
            "description": "Forbidden (search belongs to different user)",
            "content": {
                "application/json": {
                    "example": {
                        "detail": {
                            "error": "Forbidden",
                            "message": "Cannot delete search belonging to another user"
                        }
                    }
                }
            },
        },
        404: {
            "description": "Not found (search does not exist)",
            "content": {
                "application/json": {
                    "example": {
                        "detail": {
                            "error": "NotFound",
                            "message": "Saved search not found"
                        }
                    }
                }
            },
        },
    },
)
async def delete_saved_search(
    search_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """
    Delete saved search (T018: Feature 018).

    Security: Only allows deletion if search belongs to authenticated user.
    Returns 204 on success, 403 if wrong user, 404 if not found.

    Args:
        search_id: UUID of saved search to delete
        user: Current authenticated user from Google ID token token
        db: Database session

    Returns:
        None (HTTP 204 - no content)

    Raises:
        HTTPException 400: Invalid UUID format
        HTTPException 401: Authentication required
        HTTPException 403: Search belongs to different user
        HTTPException 404: Search not found
        HTTPException 500: Internal server error
    """
    request_id = str(uuid.uuid4())
    user_id = user["user_id"]

    logger.info(
        f"[{request_id}] DELETE /api/search/saved/{search_id} - user_id={user_id}"
    )

    # Validate UUID format
    try:
        uuid.UUID(search_id)
    except ValueError:
        logger.warning(
            f"[{request_id}] Invalid UUID format for search_id: {search_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "ValidationError",
                "message": f"Invalid UUID format: {search_id}",
            },
        )

    try:
        # Initialize service and attempt deletion
        saved_search_service = SavedSearchService(db)
        deleted = await saved_search_service.delete_saved(user_id=user_id, search_id=search_id)

        if not deleted:
            # Search not found or belongs to different user
            # For security, return 404 in both cases to not leak existence information
            logger.warning(
                f"[{request_id}] Search not found or access denied: "
                f"search_id={search_id}, user_id={user_id}"
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "NotFound",
                    "message": "Saved search not found",
                },
            )

        logger.info(
            f"[{request_id}] Successfully deleted saved search: "
            f"search_id={search_id}, user_id={user_id}"
        )

        # Return 204 No Content (FastAPI automatically handles empty response)
        return None

    except HTTPException:
        # Re-raise HTTP exceptions (404, 400)
        raise
    except ValueError as e:
        logger.error(f"[{request_id}] Validation error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "ValidationError", "message": str(e)},
        )
    except Exception as e:
        logger.error(
            f"[{request_id}] Unexpected error deleting saved search: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "InternalServerError",
                "message": "Failed to delete saved search",
            },
        )
