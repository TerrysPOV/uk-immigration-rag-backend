"""
T005: SearchHistoryEntry Model
Database model for user search history with FIFO eviction at 100 entries

Entity: SearchHistoryEntry
Purpose: Track user search queries for history panel
Table: search_history

Features:
- User-scoped access (filtered by user_id from Google OAuth 2.0 token)
- Automatic FIFO eviction after 100 entries per user
- JSONB filter storage for complex filter combinations
- Query performance monitoring (execution_time_ms)
"""

from datetime import datetime
from typing import Optional
import uuid
from sqlalchemy import Column, Integer, VARCHAR, TEXT, TIMESTAMP, Index, CheckConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import validates
from pydantic import BaseModel, Field, validator

from .base import Base


class SearchHistoryEntry(Base):
    """
    SearchHistoryEntry model for user search tracking.

    Attributes:
        id (uuid): Primary key
        user_id (str): User identifier from Google OAuth 2.0 token sub claim
        query (str): Original search query string
        timestamp (datetime): When search was executed
        result_count (int): Number of results returned (nullable)
        filters_applied (dict): Applied filters as JSON object (nullable)
        execution_time_ms (int): Query latency in milliseconds (nullable)

    Validation:
        - query: 1-1000 characters
        - result_count: >= 0 if provided
        - user_id: required from authentication
        - Auto-pruning: FIFO eviction after 100 entries per user

    Indexes:
        - idx_search_history_user_timestamp: (user_id, timestamp DESC) for fast retrieval
    """

    __tablename__ = "search_history"

    # Columns
    id = Column(UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()", nullable=False)
    user_id = Column(VARCHAR(255), nullable=False, index=True, comment="From Google OAuth 2.0 token sub claim")
    query = Column(TEXT, nullable=False, comment="Original search query string")
    timestamp = Column(TIMESTAMP, nullable=False, server_default="CURRENT_TIMESTAMP", comment="When search was executed")
    result_count = Column(Integer, nullable=True, comment="Number of results returned")
    filters_applied = Column(JSONB, nullable=True, comment="JSON object of applied filters")
    execution_time_ms = Column(Integer, nullable=True, comment="Query latency for monitoring")

    # Constraints
    __table_args__ = (
        CheckConstraint("LENGTH(query) >= 1 AND LENGTH(query) <= 1000", name="check_query_length"),
        CheckConstraint("result_count >= 0", name="check_result_count_positive"),
        Index(
            "idx_search_history_user_timestamp",
            "user_id",
            "timestamp",
            postgresql_ops={"timestamp": "DESC"},
        ),
        Index("idx_search_history_timestamp", "timestamp"),
        {"comment": "User search history for history panel (FIFO eviction at 100 entries per user)"}
    )

    @validates("query")
    def validate_query_length(self, key, value):
        """Validate query length 1-1000 characters."""
        if not value or len(value) < 1:
            raise ValueError("query must be at least 1 character")
        if len(value) > 1000:
            raise ValueError(f"query must be <= 1000 characters, got {len(value)}")
        return value

    @validates("result_count")
    def validate_result_count(self, key, value):
        """Validate result_count is non-negative."""
        if value is not None and value < 0:
            raise ValueError(f"result_count must be non-negative, got {value}")
        return value

    @validates("user_id")
    def validate_user_id(self, key, value):
        """Validate user_id is non-empty."""
        if not value or len(value) < 1:
            raise ValueError("user_id must be non-empty")
        return value

    def __repr__(self):
        return f"<SearchHistoryEntry(id='{self.id}', user_id='{self.user_id}', query='{self.query[:30]}...', count={self.result_count})>"


# Pydantic schemas for API validation

class SearchHistoryEntryBase(BaseModel):
    """Base search history entry schema."""

    query: str = Field(..., description="Search query text", min_length=1, max_length=1000)
    result_count: Optional[int] = Field(None, description="Number of results", ge=0)
    filters_applied: Optional[dict] = Field(None, description="Applied filters (JSONB)")
    execution_time_ms: Optional[int] = Field(None, description="Query latency in ms", ge=0)


class SearchHistoryEntryCreate(SearchHistoryEntryBase):
    """Schema for creating new search history entry."""

    user_id: str = Field(..., description="User identifier from Google ID token", max_length=255)


class SearchHistoryEntryInDB(SearchHistoryEntryBase):
    """Schema for search history entry stored in database."""

    id: uuid.UUID
    user_id: str
    timestamp: datetime

    class Config:
        from_attributes = True


class SearchHistoryListResponse(BaseModel):
    """Schema for search history list API response."""

    entries: list[SearchHistoryEntryInDB] = Field(
        ..., description="Search history entries (max 100, newest first)"
    )
    total_count: int = Field(..., description="Total entries for user", ge=0, le=100)

    @validator("total_count")
    def validate_total_count(cls, v, values):
        """Validate total_count matches entries length and is <= 100."""
        if "entries" in values and len(values["entries"]) != v:
            raise ValueError("total_count must match entries length")
        if v > 100:
            raise ValueError("total_count must be <= 100 (FIFO eviction enforced)")
        return v
