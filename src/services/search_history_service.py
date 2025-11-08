"""
T010: SearchHistory Service
CRUD operations for user search history with FIFO eviction

Feature 018: User Testing Issue Remediation
Provides search history management with automatic pruning at 100 entries per user
"""

import logging
from typing import List, Optional, Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import desc

from src.models.search_history import SearchHistoryEntry

logger = logging.getLogger(__name__)


class SearchHistoryService:
    """
    Service for search history management.

    Features:
    - User-scoped search history (filtered by user_id from Google OAuth token)
    - Auto-creation after every search execution
    - FIFO eviction at 100 entries per user
    - No cross-user access (security enforced)
    """

    MAX_HISTORY_ENTRIES = 100

    def __init__(self, db_session: Session):
        """
        Initialize search history service.

        Args:
            db_session: SQLAlchemy database session
        """
        self.db = db_session

    async def list_history(
        self,
        user_id: str,
        limit: int = 100
    ) -> List[SearchHistoryEntry]:
        """
        List user's search history (newest first).

        Args:
            user_id: User identifier from Google OAuth 2.0 token
            limit: Maximum entries to return (default 100, max 100)

        Returns:
            List of SearchHistoryEntry sorted by timestamp DESC

        Raises:
            ValueError: If user_id empty or limit invalid
        """
        if not user_id or len(user_id.strip()) == 0:
            raise ValueError("user_id must be non-empty")

        if limit < 1 or limit > self.MAX_HISTORY_ENTRIES:
            raise ValueError(f"limit must be 1-{self.MAX_HISTORY_ENTRIES}, got {limit}")

        # Query user's history, newest first
        entries = self.db.query(SearchHistoryEntry).filter(
            SearchHistoryEntry.user_id == user_id
        ).order_by(
            desc(SearchHistoryEntry.timestamp)
        ).limit(limit).all()

        logger.info(f"Listed {len(entries)} search history entries for user_id={user_id}")

        return entries

    async def create_entry(
        self,
        user_id: str,
        query: str,
        result_count: Optional[int] = None,
        filters_applied: Optional[Dict[str, Any]] = None,
        execution_time_ms: Optional[int] = None
    ) -> SearchHistoryEntry:
        """
        Create new search history entry with automatic FIFO eviction.

        This method is called automatically after every search execution.

        Args:
            user_id: User identifier from Google OAuth token
            query: Search query text (1-1000 characters)
            result_count: Number of results returned (optional)
            filters_applied: Applied filters as JSON object (optional)
            execution_time_ms: Query latency in milliseconds (optional)

        Returns:
            Created SearchHistoryEntry

        Raises:
            ValueError: If validation fails
        """
        # Create new entry
        entry = SearchHistoryEntry(
            user_id=user_id,
            query=query,
            result_count=result_count,
            filters_applied=filters_applied or {},
            execution_time_ms=execution_time_ms
        )

        self.db.add(entry)
        self.db.commit()
        self.db.refresh(entry)

        logger.info(f"Created search history entry for user_id={user_id}, query='{query[:50]}...'")

        # Auto-evict if user exceeds limit
        await self.evict_old_entries(user_id)

        return entry

    async def delete_entry(self, user_id: str, entry_id: str) -> bool:
        """
        Delete specific search history entry.

        Security: Only deletes if entry belongs to user_id (no cross-user access).

        Args:
            user_id: User identifier from Google OAuth token
            entry_id: SearchHistoryEntry UUID to delete

        Returns:
            True if deleted, False if not found or wrong user

        Raises:
            ValueError: If user_id or entry_id empty
        """
        if not user_id or len(user_id.strip()) == 0:
            raise ValueError("user_id must be non-empty")

        if not entry_id or len(str(entry_id).strip()) == 0:
            raise ValueError("entry_id must be non-empty")

        # Find entry with user ownership check
        entry = self.db.query(SearchHistoryEntry).filter(
            SearchHistoryEntry.id == entry_id,
            SearchHistoryEntry.user_id == user_id  # Security: prevent cross-user deletion
        ).first()

        if not entry:
            logger.warning(f"Entry not found or wrong user: entry_id={entry_id}, user_id={user_id}")
            return False

        self.db.delete(entry)
        self.db.commit()

        logger.info(f"Deleted search history entry: entry_id={entry_id}, user_id={user_id}")

        return True

    async def evict_old_entries(self, user_id: str) -> int:
        """
        Evict oldest entries if user exceeds MAX_HISTORY_ENTRIES (FIFO).

        Called automatically after create_entry().

        Args:
            user_id: User identifier from Google OAuth token

        Returns:
            Number of entries evicted

        Raises:
            ValueError: If user_id empty
        """
        if not user_id or len(user_id.strip()) == 0:
            raise ValueError("user_id must be non-empty")

        # Count user's entries
        total_count = self.db.query(SearchHistoryEntry).filter(
            SearchHistoryEntry.user_id == user_id
        ).count()

        if total_count <= self.MAX_HISTORY_ENTRIES:
            return 0  # No eviction needed

        # Calculate how many to evict
        evict_count = total_count - self.MAX_HISTORY_ENTRIES

        # Get oldest entries to evict
        oldest_entries = self.db.query(SearchHistoryEntry).filter(
            SearchHistoryEntry.user_id == user_id
        ).order_by(
            SearchHistoryEntry.timestamp.asc()  # Oldest first
        ).limit(evict_count).all()

        # Delete oldest entries
        for entry in oldest_entries:
            self.db.delete(entry)

        self.db.commit()

        logger.info(f"FIFO evicted {evict_count} old entries for user_id={user_id} (kept {self.MAX_HISTORY_ENTRIES})")

        return evict_count

    async def get_entry_count(self, user_id: str) -> int:
        """
        Get total count of search history entries for user.

        Args:
            user_id: User identifier from Google OAuth token

        Returns:
            Total entry count (0-100)

        Raises:
            ValueError: If user_id empty
        """
        if not user_id or len(user_id.strip()) == 0:
            raise ValueError("user_id must be non-empty")

        count = self.db.query(SearchHistoryEntry).filter(
            SearchHistoryEntry.user_id == user_id
        ).count()

        return count
