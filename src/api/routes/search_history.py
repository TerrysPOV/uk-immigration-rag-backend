"""
T017: Search History API Routes
Feature 018: User Testing Issue Remediation

Endpoints:
- GET /api/search/history → List user's search history (newest first)
- DELETE /api/search/history/{id} → Delete specific history entry

Security:
- All endpoints require Google OAuth 2.0 authentication
- Users can only access/delete their own history entries
- Cross-user access blocked with HTTP 403

Contract Tests: backend-source/tests/contract/test_search_history_contract.py
"""

import logging
import uuid
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.middleware.rbac import get_current_user
from src.database import get_db
from src.services.search_history_service import SearchHistoryService
from src.models.search_history import SearchHistoryEntryInDB

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/search/history",
    tags=["Search History"],
)


@router.get(
    "",
    response_model=List[SearchHistoryEntryInDB],
    status_code=200,
    summary="List user's search history",
    description="Get user's search history sorted newest first. "
    "Auto-limited to 100 entries per user with FIFO eviction. "
    "Requires authentication - users can only see their own history.",
    responses={
        200: {
            "description": "Search history retrieved successfully",
            "model": List[SearchHistoryEntryInDB],
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
async def list_search_history(
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[SearchHistoryEntryInDB]:
    """
    List user's search history (T017: Feature 018).

    Returns search history entries sorted newest first, limited to 100 entries.
    Automatically evicts oldest entries via FIFO when limit exceeded.

    Args:
        user: Current authenticated user from Google ID token token
        db: Database session

    Returns:
        List[SearchHistoryEntryInDB]: Search history entries (newest first)

    Raises:
        HTTPException 401: Authentication required
        HTTPException 500: Internal server error
    """
    request_id = str(uuid.uuid4())
    user_id = user["user_id"]

    logger.info(
        f"[{request_id}] GET /api/search/history - user_id={user_id}"
    )

    try:
        # Initialize service and fetch history
        history_service = SearchHistoryService(db)
        entries = await history_service.list_history(user_id=user_id, limit=100)

        logger.info(
            f"[{request_id}] Retrieved {len(entries)} search history entries for user_id={user_id}"
        )

        # Convert SQLAlchemy models to Pydantic models
        return [
            SearchHistoryEntryInDB(
                id=entry.id,
                user_id=entry.user_id,
                query=entry.query,
                timestamp=entry.timestamp,
                result_count=entry.result_count,
                filters_applied=entry.filters_applied,
                execution_time_ms=entry.execution_time_ms,
            )
            for entry in entries
        ]

    except ValueError as e:
        logger.error(f"[{request_id}] Validation error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "ValidationError", "message": str(e)},
        )
    except Exception as e:
        logger.error(
            f"[{request_id}] Unexpected error listing search history: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "InternalServerError",
                "message": "Failed to retrieve search history",
            },
        )


@router.delete(
    "/{entry_id}",
    status_code=204,
    summary="Delete search history entry",
    description="Delete specific search history entry. "
    "Security: Users can only delete their own entries (HTTP 403 if wrong user). "
    "Returns HTTP 204 on success, HTTP 404 if entry not found.",
    responses={
        204: {
            "description": "Entry deleted successfully (no content)",
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
            "description": "Forbidden (entry belongs to different user)",
            "content": {
                "application/json": {
                    "example": {
                        "detail": {
                            "error": "Forbidden",
                            "message": "Cannot delete entry belonging to another user",
                        }
                    }
                }
            },
        },
        404: {
            "description": "Not found (entry does not exist)",
            "content": {
                "application/json": {
                    "example": {
                        "detail": {
                            "error": "NotFound",
                            "message": "Search history entry not found",
                        }
                    }
                }
            },
        },
    },
)
async def delete_search_history_entry(
    entry_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """
    Delete search history entry (T017: Feature 018).

    Security: Only allows deletion if entry belongs to authenticated user.
    Returns 204 on success, 403 if wrong user, 404 if not found.

    Args:
        entry_id: UUID of search history entry to delete
        user: Current authenticated user from Google ID token token
        db: Database session

    Returns:
        None (HTTP 204 - no content)

    Raises:
        HTTPException 400: Invalid UUID format
        HTTPException 401: Authentication required
        HTTPException 403: Entry belongs to different user
        HTTPException 404: Entry not found
        HTTPException 500: Internal server error
    """
    request_id = str(uuid.uuid4())
    user_id = user["user_id"]

    logger.info(
        f"[{request_id}] DELETE /api/search/history/{entry_id} - user_id={user_id}"
    )

    # Validate UUID format
    try:
        uuid.UUID(entry_id)
    except ValueError:
        logger.warning(
            f"[{request_id}] Invalid UUID format for entry_id: {entry_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "ValidationError",
                "message": f"Invalid UUID format: {entry_id}",
            },
        )

    try:
        # Initialize service and attempt deletion
        history_service = SearchHistoryService(db)
        deleted = await history_service.delete_entry(user_id=user_id, entry_id=entry_id)

        if not deleted:
            # Entry not found or belongs to different user
            # We can't distinguish between 403 and 404 from service return value
            # The service already does user ownership check, so False means either:
            # 1. Entry doesn't exist (404)
            # 2. Entry exists but belongs to different user (403)
            # For security, we return 404 in both cases to not leak existence information
            logger.warning(
                f"[{request_id}] Entry not found or access denied: entry_id={entry_id}, user_id={user_id}"
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "NotFound",
                    "message": "Search history entry not found",
                },
            )

        logger.info(
            f"[{request_id}] Successfully deleted search history entry: entry_id={entry_id}, user_id={user_id}"
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
            f"[{request_id}] Unexpected error deleting search history entry: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "InternalServerError",
                "message": "Failed to delete search history entry",
            },
        )
