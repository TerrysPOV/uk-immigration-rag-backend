"""
T045-T048: Saved Searches API Endpoints
Endpoints for managing user-defined saved searches

Endpoints:
- GET /api/v1/search/saved
- POST /api/v1/search/saved
- PUT /api/v1/search/saved/{id}
- DELETE /api/v1/search/saved/{id}
"""

import logging
import uuid
from typing import List
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from src.middleware.rbac import get_current_user, User
from src.models.saved_search import (
    SavedSearch,
    SavedSearchCreate,
    SavedSearchUpdate,
    SavedSearchInDB,
    SavedSearchResponse,
)
from src.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/search/saved", tags=["saved-searches"])


@router.get(
    "",
    response_model=SavedSearchResponse,
    summary="Get Saved Searches",
    description="Retrieve user's saved searches (max 20, newest first). "
    "Saved searches persist permanently until user deletes them.",
)
async def get_saved_searches(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SavedSearchResponse:
    """
    GET /api/v1/search/saved

    Returns user's saved searches ordered by created_at DESC.
    Max 20 saved searches per user.

    Returns:
        SavedSearchResponse with saved_searches array and total_count
    """
    logger.info(f"GET /search/saved - user: {user.username}")

    # Query saved searches for user (max 20, newest first)
    saved_searches = (
        db.query(SavedSearch)
        .filter(SavedSearch.user_id == user.user_id)
        .order_by(SavedSearch.created_at.desc())
        .limit(20)
        .all()
    )

    total_count = len(saved_searches)

    logger.info(f"Found {total_count} saved searches for user {user.username}")

    return SavedSearchResponse(
        saved_searches=[SavedSearchInDB.from_orm(s) for s in saved_searches],
        total_count=total_count,
    )


@router.post(
    "",
    response_model=SavedSearchInDB,
    status_code=status.HTTP_201_CREATED,
    summary="Create Saved Search",
    description="Save a search with custom name. Max 20 saved searches per user. "
    "Name must be unique per user.",
)
async def create_saved_search(
    search: SavedSearchCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SavedSearchInDB:
    """
    POST /api/v1/search/saved

    Create new saved search with user-defined name.
    Enforces 20 saved search limit per user.

    Body:
        {
            "name": "Recent visa guidance",
            "search_query": {
                "query_text": "visa requirements",
                "filters": {"document_type": ["guidance"], "date_range": {"preset": "last_6_months"}}
            },
            "user_id": "user-123"
        }

    Returns:
        Created SavedSearchInDB entry

    Raises:
        400: Name already exists for user or limit exceeded
    """
    logger.info(
        f"POST /search/saved - user: {user.username}, name: '{search.name}'"
    )

    # Validate user_id matches authenticated user
    if search.user_id != user.user_id:
        logger.warning(
            f"User {user.username} attempted to save search for different user {search.user_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot save search for different user",
        )

    # Check if user has reached 20 saved search limit
    existing_count = (
        db.query(SavedSearch)
        .filter(SavedSearch.user_id == user.user_id)
        .count()
    )

    if existing_count >= 20:
        logger.warning(
            f"User {user.username} has reached 20 saved search limit"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maximum 20 saved searches per user. Please delete an existing search.",
        )

    # Check for duplicate name
    existing_search = (
        db.query(SavedSearch)
        .filter(SavedSearch.user_id == user.user_id)
        .filter(SavedSearch.name == search.name)
        .first()
    )

    if existing_search:
        logger.warning(
            f"User {user.username} attempted to create duplicate saved search name '{search.name}'"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Saved search with name '{search.name}' already exists. Please choose a different name.",
        )

    # Create new saved search
    new_search = SavedSearch(
        user_id=search.user_id,
        name=search.name,
        search_query=search.search_query,
    )

    try:
        db.add(new_search)
        db.commit()
        db.refresh(new_search)

        logger.info(f"Created saved search {new_search.id} for user {user.username}")

        return SavedSearchInDB.from_orm(new_search)

    except IntegrityError as e:
        db.rollback()
        logger.error(f"IntegrityError creating saved search: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Saved search with name '{search.name}' already exists.",
        )


@router.put(
    "/{search_id}",
    response_model=SavedSearchInDB,
    summary="Update Saved Search",
    description="Update saved search name. Name must be unique per user.",
)
async def update_saved_search(
    search_id: uuid.UUID,
    update: SavedSearchUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SavedSearchInDB:
    """
    PUT /api/v1/search/saved/{search_id}

    Update saved search name. Only the name can be updated, not the search_query.

    Body:
        {
            "name": "Updated search name"
        }

    Returns:
        Updated SavedSearchInDB entry

    Raises:
        404: Search not found
        400: Name already exists for user
    """
    logger.info(
        f"PUT /search/saved/{search_id} - user: {user.username}, new_name: '{update.name}'"
    )

    # Find saved search
    saved_search = (
        db.query(SavedSearch)
        .filter(SavedSearch.id == search_id)
        .first()
    )

    if not saved_search:
        logger.warning(f"Saved search {search_id} not found")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Saved search {search_id} not found",
        )

    # Validate ownership
    if saved_search.user_id != user.user_id:
        logger.warning(
            f"User {user.username} attempted to update saved search {search_id} belonging to {saved_search.user_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot update saved search for different user",
        )

    # Check for duplicate name (excluding current search)
    existing_search = (
        db.query(SavedSearch)
        .filter(SavedSearch.user_id == user.user_id)
        .filter(SavedSearch.name == update.name)
        .filter(SavedSearch.id != search_id)
        .first()
    )

    if existing_search:
        logger.warning(
            f"User {user.username} attempted to rename saved search to existing name '{update.name}'"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Saved search with name '{update.name}' already exists. Please choose a different name.",
        )

    # Update name
    saved_search.name = update.name
    db.commit()
    db.refresh(saved_search)

    logger.info(f"Updated saved search {search_id} name to '{update.name}' for user {user.username}")

    return SavedSearchInDB.from_orm(saved_search)


@router.delete(
    "/{search_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Saved Search",
    description="Delete saved search by ID.",
)
async def delete_saved_search(
    search_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    DELETE /api/v1/search/saved/{search_id}

    Delete saved search. Validates that search belongs to authenticated user.
    """
    logger.info(f"DELETE /search/saved/{search_id} - user: {user.username}")

    # Find saved search
    saved_search = (
        db.query(SavedSearch)
        .filter(SavedSearch.id == search_id)
        .first()
    )

    if not saved_search:
        logger.warning(f"Saved search {search_id} not found")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Saved search {search_id} not found",
        )

    # Validate ownership
    if saved_search.user_id != user.user_id:
        logger.warning(
            f"User {user.username} attempted to delete saved search {search_id} belonging to {saved_search.user_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot delete saved search for different user",
        )

    # Delete saved search
    db.delete(saved_search)
    db.commit()

    logger.info(f"Deleted saved search {search_id} for user {user.username}")

    return


@router.post(
    "/{search_id}/execute",
    response_model=SavedSearchInDB,
    summary="Execute Saved Search",
    description="Update last_executed_at timestamp when saved search is executed.",
)
async def execute_saved_search(
    search_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SavedSearchInDB:
    """
    POST /api/v1/search/saved/{search_id}/execute

    Update last_executed_at timestamp for saved search.
    Frontend calls this after executing a saved search to track usage.

    Returns:
        Updated SavedSearchInDB entry
    """
    logger.info(f"POST /search/saved/{search_id}/execute - user: {user.username}")

    # Find saved search
    saved_search = (
        db.query(SavedSearch)
        .filter(SavedSearch.id == search_id)
        .first()
    )

    if not saved_search:
        logger.warning(f"Saved search {search_id} not found")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Saved search {search_id} not found",
        )

    # Validate ownership
    if saved_search.user_id != user.user_id:
        logger.warning(
            f"User {user.username} attempted to execute saved search {search_id} belonging to {saved_search.user_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot execute saved search for different user",
        )

    # Update last_executed_at
    saved_search.last_executed_at = datetime.utcnow()
    db.commit()
    db.refresh(saved_search)

    logger.info(f"Updated last_executed_at for saved search {search_id}")

    return SavedSearchInDB.from_orm(saved_search)
