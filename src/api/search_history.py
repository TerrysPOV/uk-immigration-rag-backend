"""
T041-T044: Search History API Endpoints
Endpoints for managing user search history with auto-pruning

Endpoints:
- GET /api/v1/search/history
- POST /api/v1/search/history
- DELETE /api/v1/search/history (clear all)
- DELETE /api/v1/search/history/{id} (delete single)
"""

import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.middleware.rbac import get_current_user, User
from src.models.search_history import (
    SearchHistory,
    SearchHistoryCreate,
    SearchHistoryInDB,
    SearchHistoryResponse,
)
from src.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/search/history", tags=["search-history"])


@router.get(
    "",
    response_model=SearchHistoryResponse,
    summary="Get Search History",
    description="Retrieve user's search history (max 50 entries, newest first). "
    "History is stored per authenticated user and persists across sessions.",
)
async def get_search_history(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SearchHistoryResponse:
    """
    GET /api/v1/search/history

    Returns user's search history with automatic 50-entry limit.
    Results are ordered by timestamp DESC (newest first).

    Returns:
        SearchHistoryResponse with entries array and total_count
    """
    logger.info(f"GET /search/history - user: {user.username}")

    # Query search history for user (max 50, newest first)
    history_entries = (
        db.query(SearchHistory)
        .filter(SearchHistory.user_id == user.user_id)
        .order_by(SearchHistory.timestamp.desc())
        .limit(50)
        .all()
    )

    total_count = len(history_entries)

    logger.info(f"Found {total_count} history entries for user {user.username}")

    return SearchHistoryResponse(
        entries=[SearchHistoryInDB.from_orm(entry) for entry in history_entries],
        total_count=total_count,
    )


@router.post(
    "",
    response_model=SearchHistoryInDB,
    status_code=status.HTTP_201_CREATED,
    summary="Add to Search History",
    description="Add new search to user's history. Auto-prunes to keep only latest 50 entries.",
)
async def add_to_search_history(
    search: SearchHistoryCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SearchHistoryInDB:
    """
    POST /api/v1/search/history

    Add new search entry to history and auto-prune if over 50 entries.

    Body:
        {
            "query_text": "visa requirements",
            "filters": {"document_type": ["guidance"]},
            "result_count": 42,
            "user_id": "user-123"
        }

    Returns:
        Created SearchHistoryInDB entry
    """
    logger.info(
        f"POST /search/history - user: {user.username}, query: '{search.query_text[:50]}...'"
    )

    # Validate user_id matches authenticated user
    if search.user_id != user.user_id:
        logger.warning(
            f"User {user.username} attempted to add history for different user {search.user_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot add history for different user",
        )

    # Create new history entry
    new_entry = SearchHistory(
        user_id=search.user_id,
        query_text=search.query_text,
        filters=search.filters,
        result_count=search.result_count,
    )

    db.add(new_entry)
    db.commit()
    db.refresh(new_entry)

    # Auto-prune: Keep only latest 50 entries
    await _auto_prune_history(user.user_id, db)

    logger.info(f"Added history entry {new_entry.id} for user {user.username}")

    return SearchHistoryInDB.from_orm(new_entry)


@router.delete(
    "",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Clear All History",
    description="Delete all search history for the authenticated user.",
)
async def clear_search_history(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    DELETE /api/v1/search/history

    Delete all history entries for authenticated user.
    """
    logger.info(f"DELETE /search/history - user: {user.username}")

    # Delete all history for user
    deleted_count = (
        db.query(SearchHistory)
        .filter(SearchHistory.user_id == user.user_id)
        .delete()
    )

    db.commit()

    logger.info(f"Deleted {deleted_count} history entries for user {user.username}")

    return


@router.delete(
    "/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Single History Entry",
    description="Delete specific search history entry by ID.",
)
async def delete_history_entry(
    entry_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    DELETE /api/v1/search/history/{entry_id}

    Delete specific history entry. Validates that entry belongs to authenticated user.
    """
    logger.info(f"DELETE /search/history/{entry_id} - user: {user.username}")

    # Find entry
    entry = db.query(SearchHistory).filter(SearchHistory.id == entry_id).first()

    if not entry:
        logger.warning(f"History entry {entry_id} not found")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"History entry {entry_id} not found",
        )

    # Validate ownership
    if entry.user_id != user.user_id:
        logger.warning(
            f"User {user.username} attempted to delete history entry {entry_id} belonging to {entry.user_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot delete history entry for different user",
        )

    # Delete entry
    db.delete(entry)
    db.commit()

    logger.info(f"Deleted history entry {entry_id} for user {user.username}")

    return


async def _auto_prune_history(user_id: str, db: Session):
    """
    Auto-prune search history to keep only latest 50 entries per user.

    Args:
        user_id: User identifier
        db: Database session
    """
    # Get count of entries
    total_count = db.query(SearchHistory).filter(SearchHistory.user_id == user_id).count()

    if total_count > 50:
        # Get IDs of oldest entries to delete
        entries_to_keep = (
            db.query(SearchHistory.id)
            .filter(SearchHistory.user_id == user_id)
            .order_by(SearchHistory.timestamp.desc())
            .limit(50)
            .subquery()
        )

        # Delete entries not in keep list
        deleted_count = (
            db.query(SearchHistory)
            .filter(SearchHistory.user_id == user_id)
            .filter(SearchHistory.id.notin_(entries_to_keep))
            .delete(synchronize_session=False)
        )

        db.commit()

        logger.info(f"Auto-pruned {deleted_count} old history entries for user {user_id}")
