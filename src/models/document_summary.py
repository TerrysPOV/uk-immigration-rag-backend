"""
T007: DocumentSummary Model
Database model for AI-generated summary cache

Entity: DocumentSummary
Purpose: Cache AI-generated summaries to reduce OpenRouter API costs
Table: document_summaries

Features:
- System-wide cache (shared across users)
- 24-hour TTL (time-to-live)
- LRU eviction when cache exceeds 1GB
- Word count validation
"""

from datetime import datetime, timedelta
from typing import Optional
import uuid
from sqlalchemy import Column, Integer, VARCHAR, TEXT, TIMESTAMP, Index, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import validates
from pydantic import BaseModel, Field, validator

from .base import Base


class DocumentSummary(Base):
    """
    DocumentSummary model for AI-generated summary caching.

    Attributes:
        id (uuid): Primary key
        document_id (str): Reference to source document
        summary_text (str): Generated summary (150-250 words)
        word_count (int): Actual word count
        model_used (str): OpenRouter model identifier
        generated_at (datetime): Cache timestamp
        expires_at (datetime): Cache expiration (generated_at + 24h)
        user_id (str): User who requested (for rate limiting tracking, nullable)

    Validation:
        - summary_text: minimum 50 characters
        - word_count: > 0
        - expires_at: exactly 24 hours after generated_at

    Cache Behavior:
        - Key: document_id
        - TTL: 24 hours
        - Eviction: LRU when storage > 1GB
        - Scope: System-wide (shared across users)

    Indexes:
        - idx_document_summaries_doc_expiry: (document_id, expires_at) for cache lookups
        - idx_document_summaries_expires_at: expires_at for expiration queries
        - idx_document_summaries_generated_at: generated_at for LRU eviction
    """

    __tablename__ = "document_summaries"

    # Columns
    id = Column(UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()", nullable=False)
    document_id = Column(VARCHAR(255), nullable=False, index=True, comment="Reference to source document")
    summary_text = Column(TEXT, nullable=False, comment="Generated summary (150-250 words)")
    word_count = Column(Integer, nullable=False, comment="Actual word count")
    model_used = Column(VARCHAR(100), nullable=False, comment="OpenRouter model identifier")
    generated_at = Column(TIMESTAMP, nullable=False, server_default="CURRENT_TIMESTAMP", comment="Cache timestamp")
    expires_at = Column(TIMESTAMP, nullable=False, comment="Cache expiration (generated_at + 24h)")
    user_id = Column(VARCHAR(255), nullable=True, comment="User who requested (for rate limiting tracking)")

    # Constraints
    __table_args__ = (
        CheckConstraint("word_count > 0", name="check_word_count_positive"),
        CheckConstraint("LENGTH(summary_text) >= 50", name="check_summary_min_length"),
        Index("idx_document_summaries_doc_expiry", "document_id", "expires_at"),
        Index("idx_document_summaries_expires_at", "expires_at"),
        Index("idx_document_summaries_generated_at", "generated_at"),
        {"comment": "AI-generated summary cache (24h TTL, LRU eviction at 1GB)"}
    )

    @validates("word_count")
    def validate_word_count(self, key, value):
        """Validate word_count is positive."""
        if value is not None and value <= 0:
            raise ValueError(f"word_count must be positive, got {value}")
        return value

    @validates("summary_text")
    def validate_summary_text(self, key, value):
        """Validate summary_text minimum length."""
        if not value or len(value) < 50:
            raise ValueError(f"summary_text must be >= 50 characters, got {len(value) if value else 0}")
        return value

    def is_expired(self) -> bool:
        """Check if cache entry has expired."""
        return datetime.utcnow() > self.expires_at

    @staticmethod
    def calculate_expiry(generated_at: datetime = None) -> datetime:
        """Calculate expiry timestamp (24 hours from generated_at)."""
        if generated_at is None:
            generated_at = datetime.utcnow()
        return generated_at + timedelta(hours=24)

    def __repr__(self):
        return f"<DocumentSummary(id='{self.id}', document_id='{self.document_id}', words={self.word_count}, expires={self.expires_at.isoformat()})>"


# Pydantic schemas for API validation

class DocumentSummaryBase(BaseModel):
    """Base document summary schema."""

    document_id: str = Field(..., description="Document identifier", max_length=255)
    summary_text: str = Field(..., description="Generated summary", min_length=50)
    word_count: int = Field(..., description="Actual word count", gt=0)
    model_used: str = Field(..., description="OpenRouter model identifier", max_length=100)


class DocumentSummaryCreate(DocumentSummaryBase):
    """Schema for creating new document summary cache entry."""

    user_id: Optional[str] = Field(None, description="User who requested", max_length=255)


class DocumentSummaryInDB(DocumentSummaryBase):
    """Schema for document summary stored in database."""

    id: uuid.UUID
    generated_at: datetime
    expires_at: datetime
    user_id: Optional[str]

    class Config:
        from_attributes = True


class SummarizeResponse(BaseModel):
    """Schema for summarize API response."""

    document_id: str = Field(..., description="Document identifier")
    summary_text: str = Field(..., description="Generated summary (150-200 words)")
    word_count: int = Field(..., description="Actual word count", gt=0)
    model_used: str = Field(..., description="OpenRouter model identifier")
    cached: bool = Field(default=False, description="Whether result was from cache")

    class Config:
        from_attributes = True
