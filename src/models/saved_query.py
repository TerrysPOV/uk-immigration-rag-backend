"""
T032: SavedQuery Model
Database model for user-saved complex search queries for reuse

Entity: SavedQuery
Purpose: User-saved complex search query for reuse
Table: saved_queries

Features:
- Boolean query syntax storage and validation
- Parsed AST (Abstract Syntax Tree) storage
- Field-specific search filters
- Usage tracking (last_executed_at, execution_count)
"""

from datetime import datetime
from typing import Optional
from sqlalchemy import Column, VARCHAR, TEXT, Integer, TIMESTAMP, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship, validates
from pydantic import BaseModel, Field, validator
import uuid

from .base import Base


class SavedQuery(Base):
    """
    SavedQuery model for reusable search queries.

    Attributes:
        id (uuid): Primary key
        user_id (uuid): Foreign key to users.id
        query_name (str): User-defined query name (1-200 characters)
        query_syntax (str): Boolean query string
        field_filters (dict): Field-specific search filters (JSONB)
        boolean_operators (dict): Parsed AST of boolean operators (JSONB)
        created_at (datetime): Creation timestamp
        last_executed_at (datetime): Last execution timestamp
        execution_count (int): Total execution count

    Validation:
        - query_name must be 1-200 characters
        - query_syntax must be valid boolean expression (validated by jsep parser)
        - field_filters must have keys from: ['title', 'content', 'metadata', 'author', 'date']
        - boolean_operators must be valid AST structure
        - execution_count must be >= 0

    Cascade Behavior:
        - ON DELETE CASCADE when user deleted (cascade on delete)

    Relationships:
        - user: Many-to-one with User
    """

    __tablename__ = "saved_queries"

    # Columns
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    query_name = Column(VARCHAR(200), nullable=False)
    query_syntax = Column(TEXT, nullable=False)
    field_filters = Column(JSONB, nullable=True)
    boolean_operators = Column(JSONB, nullable=False)
    created_at = Column(TIMESTAMP, nullable=False, default=datetime.utcnow)
    last_executed_at = Column(TIMESTAMP, nullable=True)
    execution_count = Column(Integer, nullable=False, default=0)

    # Allowed field filter keys
    ALLOWED_FIELD_FILTERS = ["title", "content", "metadata", "author", "date"]

    # Relationships (to be defined after all models are created)
    # user = relationship("User", back_populates="saved_queries")

    __table_args__ = (
        Index(
            "idx_saved_queries_user",
            "user_id",
            "last_executed_at",
            postgresql_ops={"last_executed_at": "DESC"},
        ),
    )

    @validates("query_name")
    def validate_query_name(self, key, value):
        """Validate query_name is 1-200 characters."""
        if not (1 <= len(value) <= 200):
            raise ValueError(f"query_name must be 1-200 characters, got {len(value)}")
        return value

    @validates("field_filters")
    def validate_field_filters(self, key, value):
        """Validate field_filters has keys from allowed list."""
        if value is None:
            return value

        if not isinstance(value, dict):
            raise ValueError("field_filters must be a JSON object")

        invalid_keys = set(value.keys()) - set(self.ALLOWED_FIELD_FILTERS)
        if invalid_keys:
            raise ValueError(
                f"field_filters contains invalid keys {invalid_keys}. Allowed: {self.ALLOWED_FIELD_FILTERS}"
            )

        return value

    @validates("execution_count")
    def validate_execution_count(self, key, value):
        """Validate execution_count is non-negative."""
        if value < 0:
            raise ValueError(f"execution_count must be >= 0, got {value}")
        return value

    def __repr__(self):
        return f"<SavedQuery(id='{self.id}', name='{self.query_name}', user_id='{self.user_id}', executions={self.execution_count})>"


# Pydantic schemas for API validation
class SavedQueryBase(BaseModel):
    """Base saved query schema."""

    query_name: str = Field(
        ..., description="User-defined query name", min_length=1, max_length=200
    )
    query_syntax: str = Field(..., description="Boolean query string")
    field_filters: Optional[dict] = Field(None, description="Field-specific search filters")
    boolean_operators: dict = Field(..., description="Parsed AST of boolean operators")

    @validator("field_filters")
    def validate_field_keys(cls, v):
        if v is None:
            return v

        invalid_keys = set(v.keys()) - set(SavedQuery.ALLOWED_FIELD_FILTERS)
        if invalid_keys:
            raise ValueError(
                f"field_filters contains invalid keys {invalid_keys}. Allowed: {SavedQuery.ALLOWED_FIELD_FILTERS}"
            )
        return v


class SavedQueryCreate(SavedQueryBase):
    """Schema for creating new saved query."""

    user_id: uuid.UUID = Field(..., description="User ID who owns this query")


class SavedQueryUpdate(BaseModel):
    """Schema for updating existing saved query (partial update)."""

    query_name: Optional[str] = Field(None, min_length=1, max_length=200)
    query_syntax: Optional[str] = None
    field_filters: Optional[dict] = None
    boolean_operators: Optional[dict] = None


class SavedQueryInDB(SavedQueryBase):
    """Schema for saved query stored in database."""

    id: uuid.UUID
    user_id: uuid.UUID
    created_at: datetime
    last_executed_at: Optional[datetime]
    execution_count: int

    class Config:
        orm_mode = True


class SavedQueryExecution(BaseModel):
    """Schema for saved query execution request."""

    query_id: uuid.UUID = Field(..., description="Saved query ID to execute")
    limit: Optional[int] = Field(None, description="Override result limit", ge=1, le=1000)
    offset: Optional[int] = Field(None, description="Override result offset", ge=0)
