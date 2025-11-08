"""
T022: PromptVersion Model
Database model for saved playground prompt versions with soft-delete

Entity: PromptVersion
Purpose: Versioned storage of playground prompts for testing and iteration
Table: prompt_versions

Features:
- Soft-delete with 30-day retention (deleted_at nullable timestamp)
- Optimistic locking via version column
- Unique name constraint across all versions (active + deleted)
- Maximum prompt length 10,000 characters
- Author relationship to users table
"""

from datetime import datetime
from typing import Optional
from sqlalchemy import Column, VARCHAR, TEXT, Integer, TIMESTAMP, ForeignKey, Index, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship, validates
from pydantic import BaseModel, Field
import uuid

from .base import Base


class PromptVersion(Base):
    """
    PromptVersion model for playground prompt iterations.

    Attributes:
        id (uuid): Primary key
        name (str): Unique version name (1-255 characters)
        prompt_text (str): System prompt content (max 10,000 characters)
        author_id (uuid): Foreign key to users.id
        notes (str): Optional description of changes
        created_at (datetime): Creation timestamp
        deleted_at (datetime): Soft-delete timestamp (null = active)
        version (int): Optimistic locking version counter (default 1)

    Validation:
        - name must be unique across all versions
        - prompt_text must be <= 10,000 characters
        - author_id must reference existing user

    Cascade Behavior:
        - ON DELETE RESTRICT when user deleted (cannot delete user with versions)

    Optimistic Locking:
        - version column auto-increments on update
        - SQLAlchemy uses version_id_col for compare-and-swap

    Relationships:
        - author: Many-to-one with User
        - audit_logs: One-to-many with PlaygroundAuditLog
    """

    __tablename__ = "prompt_versions"

    # Columns
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(VARCHAR(255), nullable=False, unique=True)
    prompt_text = Column(TEXT, nullable=False)
    author_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    notes = Column(TEXT, nullable=True)
    created_at = Column(TIMESTAMP, nullable=False, default=datetime.utcnow)
    deleted_at = Column(TIMESTAMP, nullable=True)
    version = Column(Integer, nullable=False, default=1)

    # Relationships (to be defined after all models are created)
    # author = relationship("User", back_populates="prompt_versions")
    # audit_logs = relationship("PlaygroundAuditLog", back_populates="prompt_version")

    __table_args__ = (
        CheckConstraint("length(prompt_text) <= 10000", name="ck_prompt_text_length"),
        Index("idx_prompt_versions_deleted", "deleted_at"),
        Index("idx_prompt_versions_author", "author_id"),
    )

    # Enable optimistic locking
    __mapper_args__ = {"version_id_col": version}

    @validates("name")
    def validate_name(self, key, value):
        """Validate name is 1-255 characters."""
        if not value or not (1 <= len(value) <= 255):
            raise ValueError(f"name must be 1-255 characters, got {len(value) if value else 0}")
        return value

    @validates("prompt_text")
    def validate_prompt_text(self, key, value):
        """Validate prompt_text is <= 10,000 characters."""
        if not value:
            raise ValueError("prompt_text cannot be empty")
        if len(value) > 10000:
            raise ValueError(f"prompt_text must be <= 10,000 characters, got {len(value)}")
        return value

    def __repr__(self):
        status = "deleted" if self.deleted_at else "active"
        return f"<PromptVersion(id='{self.id}', name='{self.name}', author_id='{self.author_id}', status='{status}', version={self.version})>"


# Pydantic schemas for API validation
class PromptVersionBase(BaseModel):
    """Base prompt version schema."""

    name: str = Field(..., description="Unique version name", min_length=1, max_length=255)
    prompt_text: str = Field(..., description="System prompt content", min_length=1, max_length=10000)
    notes: Optional[str] = Field(None, description="Optional description of changes")


class PromptVersionCreate(PromptVersionBase):
    """Schema for creating new prompt version."""

    author_id: uuid.UUID = Field(..., description="User ID who created this version")


class PromptVersionUpdate(BaseModel):
    """Schema for updating existing prompt version (immutable after save, used for restore only)."""

    deleted_at: Optional[datetime] = Field(None, description="Soft-delete timestamp (null to restore)")


class PromptVersionInDB(PromptVersionBase):
    """Schema for prompt version stored in database."""

    id: uuid.UUID
    author_id: uuid.UUID
    created_at: datetime
    deleted_at: Optional[datetime]
    version: int

    class Config:
        orm_mode = True


class PromptVersionResponse(PromptVersionInDB):
    """Schema for prompt version API response with author details."""

    author_name: Optional[str] = Field(None, description="Name of author (from join)")

    class Config:
        orm_mode = True
