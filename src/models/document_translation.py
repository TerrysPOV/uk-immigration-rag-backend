"""
T008: DocumentTranslation Model (Updated for Feature 024)
Database model for plain English translation cache

Entity: DocumentTranslation
Purpose: Cache plain English translations to reduce OpenRouter API costs
Table: document_translations

Feature 018: 24-hour expiring cache
Feature 022: Permanent content-addressable cache with prompt versioning
Feature 024: Model-specific caching (different models cache separately)

Features:
- System-wide cache (shared across users)
- Multiple reading levels per document (grade6, grade8, grade10)
- Permanent storage (no TTL expiration)
- Content-addressable: MD5 hash of source content
- Prompt versioning: MD5 hash of prompt template
- Model-specific: Each model maintains separate cache entries
- Unique constraint on (document_id, source_hash, reading_level, prompt_hash, model_used)
"""

from datetime import datetime, timedelta
from typing import Optional
import uuid
from sqlalchemy import Column, VARCHAR, TEXT, TIMESTAMP, Index, UniqueConstraint, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import validates
from pydantic import BaseModel, Field, validator

from .base import Base


class DocumentTranslation(Base):
    """
    DocumentTranslation model for plain English translation caching.

    T010: Updated for Feature 022 (Permanent Content-Addressable Caching)
    T024: Updated for Feature 024 (Model-Specific Caching)

    Attributes:
        id (uuid): Primary key
        document_id (str): Reference to source document
        source_hash (str): MD5 hash of source content (32 hex chars)
        reading_level (str): Target reading level (grade6, grade8, grade10)
        prompt_hash (str): MD5 hash of prompt template (32 hex chars)
        translated_text (str): Plain English translation
        model_used (str): OpenRouter model identifier
        generated_at (datetime): Cache timestamp
        expires_at (datetime): DEPRECATED - was 24h TTL, now nullable (permanent cache)
        user_id (str): User who requested (for rate limiting tracking, nullable)

    Validation:
        - reading_level: must be one of grade6, grade8, grade10
        - translated_text: minimum 50 characters
        - source_hash: required, 32 characters (MD5)
        - prompt_hash: required, 32 characters (MD5)
        - Unique constraint: (document_id, source_hash, reading_level, prompt_hash, model_used)

    Cache Behavior:
        - Key: (document_id, source_hash, reading_level, prompt_hash, model_used)
        - TTL: None (permanent storage)
        - Invalidation: Automatic when source content, prompt template, or model changes
        - Scope: System-wide (shared across users)
        - Model-Specific: Each model maintains separate cache entries

    Indexes:
        - uq_translation_cache: (document_id, source_hash, reading_level, prompt_hash, model_used) UNIQUE for cache lookups
        - idx_source_hash: source_hash for finding content versions
        - idx_prompt_hash: prompt_hash for finding prompt versions (A/B testing)
        - idx_document_translations_generated_at: generated_at for audit queries
    """

    __tablename__ = "document_translations"

    # Allowed reading levels
    ALLOWED_READING_LEVELS = ["grade6", "grade8", "grade10"]

    # Columns
    id = Column(UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()", nullable=False)
    document_id = Column(VARCHAR(255), nullable=False, comment="Reference to source document")
    source_hash = Column(VARCHAR(32), nullable=False, comment="MD5 hash of source content for content-addressable caching")  # T010: Feature 022
    reading_level = Column(VARCHAR(20), nullable=False, comment="Target reading level (grade6, grade8, grade10)")
    prompt_hash = Column(VARCHAR(32), nullable=False, comment="MD5 hash of prompt template for automatic invalidation")  # T010: Feature 022
    translated_text = Column(TEXT, nullable=False, comment="Plain English translation")
    model_used = Column(VARCHAR(100), nullable=False, comment="OpenRouter model identifier")
    generated_at = Column(TIMESTAMP, nullable=False, server_default="CURRENT_TIMESTAMP", comment="Cache timestamp")
    expires_at = Column(TIMESTAMP, nullable=True, comment="DEPRECATED - was 24h TTL, now NULL (permanent cache)")  # T010: Feature 022
    user_id = Column(VARCHAR(255), nullable=True, comment="User who requested (for rate limiting tracking)")

    # Constraints
    __table_args__ = (
        UniqueConstraint("document_id", "source_hash", "reading_level", "prompt_hash", "model_used", name="uq_translation_cache"),  # T024: Feature 024 - Model-specific caching
        CheckConstraint("reading_level IN ('grade6', 'grade8', 'grade10')", name="check_reading_level_valid"),
        CheckConstraint("LENGTH(translated_text) >= 50", name="check_translation_min_length"),
        Index("idx_source_hash", "source_hash"),  # T010: Feature 022
        Index("idx_prompt_hash", "prompt_hash"),  # T010: Feature 022
        Index("idx_document_translations_generated_at", "generated_at"),
        {"comment": "Plain English translation cache (permanent, content-addressable with prompt versioning and model-specific caching)"}
    )

    @validates("reading_level")
    def validate_reading_level(self, key, value):
        """Validate reading_level is in allowed list."""
        if value not in self.ALLOWED_READING_LEVELS:
            raise ValueError(
                f"reading_level must be one of {self.ALLOWED_READING_LEVELS}, got '{value}'"
            )
        return value

    @validates("translated_text")
    def validate_translated_text(self, key, value):
        """Validate translated_text minimum length."""
        if not value or len(value) < 50:
            raise ValueError(f"translated_text must be >= 50 characters, got {len(value) if value else 0}")
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
        return f"<DocumentTranslation(id='{self.id}', document_id='{self.document_id}', level='{self.reading_level}', expires={self.expires_at.isoformat()})>"


# Pydantic schemas for API validation

class DocumentTranslationBase(BaseModel):
    """Base document translation schema."""

    document_id: str = Field(..., description="Document identifier", max_length=255)
    reading_level: str = Field(..., description="Target reading level (grade6/grade8/grade10)")
    translated_text: str = Field(..., description="Plain English translation", min_length=50)
    model_used: str = Field(..., description="OpenRouter model identifier", max_length=100)

    @validator("reading_level")
    def validate_reading_level(cls, v):
        """Validate reading_level is allowed value."""
        if v not in DocumentTranslation.ALLOWED_READING_LEVELS:
            raise ValueError(
                f"reading_level must be one of {DocumentTranslation.ALLOWED_READING_LEVELS}, got '{v}'"
            )
        return v


class DocumentTranslationCreate(DocumentTranslationBase):
    """Schema for creating new document translation cache entry."""

    user_id: Optional[str] = Field(None, description="User who requested", max_length=255)


class DocumentTranslationInDB(DocumentTranslationBase):
    """Schema for document translation stored in database."""

    id: uuid.UUID
    generated_at: datetime
    expires_at: datetime
    user_id: Optional[str]

    class Config:
        from_attributes = True


class TranslateResponse(BaseModel):
    """Schema for translate API response."""

    document_id: str = Field(..., description="Document identifier")
    translated_text: str = Field(..., description="Plain English translation")
    reading_level: str = Field(..., description="Target reading level")
    model_used: str = Field(..., description="OpenRouter model identifier")
    cached: bool = Field(default=False, description="Whether result was from cache")

    class Config:
        from_attributes = True
