"""
T011: SavedSearch Service
CRUD operations for user saved searches with usage tracking

Feature 018: User Testing Issue Remediation
Provides saved search management with name uniqueness and usage analytics
"""

import logging
from typing import List, Optional, Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import desc
from sqlalchemy.exc import IntegrityError

from src.models.saved_search import SavedSearch

logger = logging.getLogger(__name__)


class SavedSearchService:
    """
    Service for saved search management.

    Features:
    - User-scoped saved searches (filtered by user_id from Google OAuth token)
    - Name uniqueness per user (auto-append timestamp if duplicate)
    - Usage tracking (last_used_at, usage_count)
    - 50 search limit per user
    - No cross-user access (security enforced)
    """

    MAX_SAVED_SEARCHES = 50

    def __init__(self, db_session: Session):
        """
        Initialize saved search service.

        Args:
            db_session: SQLAlchemy database session
        """
        self.db = db_session

    async def list_saved(self, user_id: str) -> List[SavedSearch]:
        """
        List user's saved searches (newest first).

        Args:
            user_id: User identifier from Google OAuth 2.0 token

        Returns:
            List of SavedSearch sorted by created_at DESC

        Raises:
            ValueError: If user_id empty
        """
        if not user_id or len(user_id.strip()) == 0:
            raise ValueError("user_id must be non-empty")

        # Query user's saved searches
        searches = self.db.query(SavedSearch).filter(
            SavedSearch.user_id == user_id
        ).order_by(
            desc(SavedSearch.created_at)
        ).all()

        logger.info(f"Listed {len(searches)} saved searches for user_id={user_id}")

        return searches

    async def create_saved(
        self,
        user_id: str,
        name: str,
        query: str,
        filters: Optional[Dict[str, Any]] = None
    ) -> SavedSearch:
        """
        Create new saved search with duplicate name handling.

        If name already exists for user, auto-appends timestamp.

        Args:
            user_id: User identifier from Google OAuth token
            name: User-provided search name (1-100 characters)
            query: Search query text (1-1000 characters)
            filters: Applied filters as JSON object (optional)

        Returns:
            Created SavedSearch

        Raises:
            ValueError: If validation fails or user exceeds 50 search limit
        """
        # Check limit
        current_count = await self.get_saved_count(user_id)
        if current_count >= self.MAX_SAVED_SEARCHES:
            raise ValueError(
                f"User has reached maximum saved searches limit ({self.MAX_SAVED_SEARCHES}). "
                f"Please delete an existing search before creating a new one."
            )

        # Handle duplicate names by appending timestamp
        final_name = name
        attempt = 0
        max_attempts = 5

        while attempt < max_attempts:
            try:
                # Try to create with current name
                search = SavedSearch(
                    user_id=user_id,
                    name=final_name,
                    query=query,
                    filters=filters or {}
                )

                self.db.add(search)
                self.db.commit()
                self.db.refresh(search)

                logger.info(f"Created saved search for user_id={user_id}, name='{final_name}'")

                return search

            except IntegrityError:
                # Unique constraint violation - name already exists
                self.db.rollback()
                attempt += 1

                if attempt == 1:
                    # First retry: append timestamp
                    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                    final_name = f"{name}_{timestamp}"
                    logger.info(f"Name '{name}' exists, retrying with '{final_name}'")
                else:
                    # Subsequent retries: append attempt number
                    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                    final_name = f"{name}_{timestamp}_{attempt}"
                    logger.info(f"Name conflict persists, retrying with '{final_name}'")

        # Max attempts exceeded
        raise ValueError(f"Failed to create saved search after {max_attempts} attempts (name conflicts)")

    async def update_saved(
        self,
        user_id: str,
        search_id: str,
        name: Optional[str] = None,
        query: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None
    ) -> SavedSearch:
        """
        Update existing saved search.

        Security: Only updates if search belongs to user_id (no cross-user access).

        Args:
            user_id: User identifier from Google OAuth token
            search_id: SavedSearch UUID to update
            name: New search name (optional)
            query: New search query (optional)
            filters: New filters (optional)

        Returns:
            Updated SavedSearch

        Raises:
            ValueError: If search not found, wrong user, or validation fails
        """
        if not user_id or len(user_id.strip()) == 0:
            raise ValueError("user_id must be non-empty")

        if not search_id or len(str(search_id).strip()) == 0:
            raise ValueError("search_id must be non-empty")

        # Find search with user ownership check
        search = self.db.query(SavedSearch).filter(
            SavedSearch.id == search_id,
            SavedSearch.user_id == user_id  # Security: prevent cross-user modification
        ).first()

        if not search:
            raise ValueError(f"Saved search not found or access denied: search_id={search_id}")

        # Update fields if provided
        if name is not None:
            search.name = name
        if query is not None:
            search.query = query
        if filters is not None:
            search.filters = filters

        self.db.commit()
        self.db.refresh(search)

        logger.info(f"Updated saved search: search_id={search_id}, user_id={user_id}")

        return search

    async def delete_saved(self, user_id: str, search_id: str) -> bool:
        """
        Delete specific saved search.

        Security: Only deletes if search belongs to user_id (no cross-user access).

        Args:
            user_id: User identifier from Google OAuth token
            search_id: SavedSearch UUID to delete

        Returns:
            True if deleted, False if not found or wrong user

        Raises:
            ValueError: If user_id or search_id empty
        """
        if not user_id or len(user_id.strip()) == 0:
            raise ValueError("user_id must be non-empty")

        if not search_id or len(str(search_id).strip()) == 0:
            raise ValueError("search_id must be non-empty")

        # Find search with user ownership check
        search = self.db.query(SavedSearch).filter(
            SavedSearch.id == search_id,
            SavedSearch.user_id == user_id  # Security: prevent cross-user deletion
        ).first()

        if not search:
            logger.warning(f"Search not found or wrong user: search_id={search_id}, user_id={user_id}")
            return False

        self.db.delete(search)
        self.db.commit()

        logger.info(f"Deleted saved search: search_id={search_id}, user_id={user_id}")

        return True

    async def execute_saved(self, user_id: str, search_id: str) -> SavedSearch:
        """
        Mark saved search as executed (increments usage_count, updates last_used_at).

        Called when user clicks saved search to re-execute query.

        Args:
            user_id: User identifier from Google OAuth token
            search_id: SavedSearch UUID to execute

        Returns:
            Updated SavedSearch with incremented usage_count

        Raises:
            ValueError: If search not found or wrong user
        """
        if not user_id or len(user_id.strip()) == 0:
            raise ValueError("user_id must be non-empty")

        if not search_id or len(str(search_id).strip()) == 0:
            raise ValueError("search_id must be non-empty")

        # Find search with user ownership check
        search = self.db.query(SavedSearch).filter(
            SavedSearch.id == search_id,
            SavedSearch.user_id == user_id  # Security: prevent cross-user execution
        ).first()

        if not search:
            raise ValueError(f"Saved search not found or access denied: search_id={search_id}")

        # Increment usage tracking
        search.increment_usage()  # Model method: increments count, updates timestamp

        self.db.commit()
        self.db.refresh(search)

        logger.info(
            f"Executed saved search: search_id={search_id}, user_id={user_id}, "
            f"usage_count={search.usage_count}"
        )

        return search

    async def get_saved_count(self, user_id: str) -> int:
        """
        Get total count of saved searches for user.

        Args:
            user_id: User identifier from Google OAuth token

        Returns:
            Total saved search count (0-50)

        Raises:
            ValueError: If user_id empty
        """
        if not user_id or len(user_id.strip()) == 0:
            raise ValueError("user_id must be non-empty")

        count = self.db.query(SavedSearch).filter(
            SavedSearch.user_id == user_id
        ).count()

        return count
