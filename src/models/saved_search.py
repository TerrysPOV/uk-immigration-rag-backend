"""
T006: SavedSearch Model
Database model for user-defined saved searches with usage tracking

Entity: SavedSearch
Purpose: Persistent saved searches for quick re-execution
Table: saved_searches

Features:
- User-defined names with uniqueness constraint per user
- Separate query and filters fields (not JSONB combined)
- Usage tracking (last_used_at, usage_count)
- 50 search limit per user
"""

from datetime import datetime
from typing import Optional
import uuid
from sqlalchemy import Column, Integer, VARCHAR, TEXT, TIMESTAMP, Index, UniqueConstraint, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import validates
from pydantic import BaseModel, Field, validator

from .base import Base


class SavedSearch(Base):
    """
    SavedSearch model for persistent user searches.

    Attributes:
        id (uuid): Primary key
        user_id (str): User identifier from Google OAuth 2.0 token sub claim
        name (str): User-defined search name (unique per user)
        query (str): Search query text to re-execute
        filters (dict): Applied filters as JSON object (nullable)
        created_at (datetime): Creation timestamp
        last_used_at (datetime): Last execution timestamp (nullable)
        usage_count (int): How many times re-executed

    Validation:
        - name: 1-100 characters, unique per user_id
        - query: 1-1000 characters
        - filters: valid JSON if provided
        - usage_count: >= 0
        - Max 50 saved searches per user_id

    Indexes:
        - idx_saved_searches_user: user_id for fast lookup
        - idx_saved_searches_last_used: last_used_at for sorting by usage
        - unique_saved_search_per_user: (user_id, name) unique constraint
    """

    __tablename__ = "saved_searches"

    # Columns
    id = Column(UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()", nullable=False)
    user_id = Column(VARCHAR(255), nullable=False, index=True, comment="From Google OAuth 2.0 token sub claim")
    name = Column(VARCHAR(100), nullable=False, comment="User-provided name (auto-append timestamp if duplicate)")
    query = Column(TEXT, nullable=False, comment="Search query to re-execute")
    filters = Column(JSONB, nullable=True, comment="JSON object of saved filters")
    created_at = Column(TIMESTAMP, nullable=False, server_default="CURRENT_TIMESTAMP", comment="When search was saved")
    last_used_at = Column(TIMESTAMP, nullable=True, comment="Last execution timestamp")
    usage_count = Column(Integer, nullable=False, server_default="0", comment="How many times re-executed")

    # Constraints
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="unique_saved_search_per_user"),
        CheckConstraint("LENGTH(name) >= 1 AND LENGTH(name) <= 100", name="check_name_length"),
        CheckConstraint("LENGTH(query) >= 1 AND LENGTH(query) <= 1000", name="check_query_length"),
        CheckConstraint("usage_count >= 0", name="check_usage_count_positive"),
        Index("idx_saved_searches_user", "user_id"),
        Index("idx_saved_searches_last_used", "last_used_at"),
        {"comment": "User saved searches (limit 50 per user)"}
    )

    @validates("name")
    def validate_name(self, key, value):
        """Validate name length 1-100 characters."""
        if not value or len(value) < 1:
            raise ValueError("name must be at least 1 character")
        if len(value) > 100:
            raise ValueError(f"name must be <= 100 characters, got {len(value)}")
        return value

    @validates("query")
    def validate_query_length(self, key, value):
        """Validate query length 1-1000 characters."""
        if not value or len(value) < 1:
            raise ValueError("query must be at least 1 character")
        if len(value) > 1000:
            raise ValueError(f"query must be <= 1000 characters, got {len(value)}")
        return value

    @validates("usage_count")
    def validate_usage_count(self, key, value):
        """Validate usage_count is non-negative."""
        if value is not None and value < 0:
            raise ValueError(f"usage_count must be non-negative, got {value}")
        return value

    def increment_usage(self):
        """Increment usage_count and update last_used_at timestamp."""
        self.usage_count += 1
        self.last_used_at = datetime.utcnow()

    def __repr__(self):
        return f"<SavedSearch(id='{self.id}', user_id='{self.user_id}', name='{self.name}', usage={self.usage_count})>"


# Pydantic schemas for API validation

class SavedSearchBase(BaseModel):
    """Base saved search schema."""

    name: str = Field(..., description="User-defined search name", min_length=1, max_length=100)
    query: str = Field(..., description="Search query text", min_length=1, max_length=1000)
    filters: Optional[dict] = Field(None, description="Applied filters (JSONB)")


class SavedSearchCreate(SavedSearchBase):
    """Schema for creating new saved search."""

    user_id: str = Field(..., description="User identifier from Google ID token", max_length=255)


class SavedSearchUpdate(BaseModel):
    """Schema for updating existing saved search."""

    name: Optional[str] = Field(None, description="New search name", min_length=1, max_length=100)
    query: Optional[str] = Field(None, description="New search query", min_length=1, max_length=1000)
    filters: Optional[dict] = Field(None, description="New filters (JSONB)")


class SavedSearchInDB(SavedSearchBase):
    """Schema for saved search stored in database."""

    id: uuid.UUID
    user_id: str
    created_at: datetime
    last_used_at: Optional[datetime]
    usage_count: int

    class Config:
        from_attributes = True


class SavedSearchListResponse(BaseModel):
    """Schema for saved search list API response."""

    saved_searches: list[SavedSearchInDB] = Field(
        ..., description="Saved searches (max 50, newest first)"
    )
    total_count: int = Field(..., description="Total saved searches for user", ge=0, le=50)

    @validator("total_count")
    def validate_total_count(cls, v, values):
        """Validate total_count matches saved_searches length and is <= 50."""
        if "saved_searches" in values and len(values["saved_searches"]) != v:
            raise ValueError("total_count must match saved_searches length")
        if v > 50:
            raise ValueError("total_count must be <= 50 (limit enforced)")
        return v
