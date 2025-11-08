"""
T023: ProductionPrompt Model
Database model for the active production system prompt (singleton table)

Entity: ProductionPrompt
Purpose: Metadata about currently active production prompt
Table: production_prompt

Features:
- Singleton table (always exactly 1 row with id=1)
- Optimistic locking via version column (prevents concurrent promotions)
- Backup path to S3/Spaces for previous prompt
- Promoter tracking (user who last promoted)
"""

from datetime import datetime
from typing import Optional
from sqlalchemy import Column, Integer, TEXT, VARCHAR, TIMESTAMP, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship, validates
from pydantic import BaseModel, Field
import uuid

from .base import Base


class ProductionPrompt(Base):
    """
    ProductionPrompt model for active production prompt (singleton).

    Attributes:
        id (int): Primary key (always 1 - enforced by application logic)
        prompt_text (str): Current production prompt content
        promoted_at (datetime): When last promotion occurred
        promoted_by (uuid): User who performed promotion
        previous_backup_path (str): S3/Spaces path to previous version backup
        version (int): Optimistic locking version (for concurrent promotions)

    Singleton Enforcement:
        - Only ONE row in table (id=1)
        - Application logic prevents multiple rows
        - Unique index on id enforces constraint

    Optimistic Locking:
        - version column auto-increments on update
        - SQLAlchemy uses version_id_col for compare-and-swap
        - Prevents Race Condition: Two users promoting simultaneously

    Cascade Behavior:
        - ON DELETE RESTRICT when promoter deleted (preserve audit trail)

    Relationships:
        - promoter: Many-to-one with User
    """

    __tablename__ = "production_prompt"

    # Columns
    id = Column(Integer, primary_key=True, autoincrement=False)  # Always 1
    prompt_text = Column(TEXT, nullable=False)
    promoted_at = Column(TIMESTAMP, nullable=False, default=datetime.utcnow)
    promoted_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    previous_backup_path = Column(VARCHAR(500), nullable=True)
    version = Column(Integer, nullable=False, default=1)

    # Relationships (to be defined after all models are created)
    # promoter = relationship("User", back_populates="promoted_prompts")

    __table_args__ = (
        Index("idx_production_prompt_singleton", "id", unique=True),
    )

    # Enable optimistic locking
    __mapper_args__ = {"version_id_col": version}

    @validates("id")
    def validate_id(self, key, value):
        """Validate id is always 1 (singleton constraint)."""
        if value != 1:
            raise ValueError(f"ProductionPrompt id must be 1 (singleton table), got {value}")
        return value

    @validates("prompt_text")
    def validate_prompt_text(self, key, value):
        """Validate prompt_text is not empty."""
        if not value:
            raise ValueError("prompt_text cannot be empty")
        return value

    def __repr__(self):
        return f"<ProductionPrompt(id={self.id}, promoted_at='{self.promoted_at}', promoted_by='{self.promoted_by}', version={self.version})>"


# Pydantic schemas for API validation
class ProductionPromptBase(BaseModel):
    """Base production prompt schema."""

    prompt_text: str = Field(..., description="Current production prompt content", min_length=1)


class ProductionPromptUpdate(ProductionPromptBase):
    """Schema for updating production prompt (via promotion)."""

    promoted_by: uuid.UUID = Field(..., description="User who performed promotion")
    previous_backup_path: Optional[str] = Field(None, description="S3/Spaces path to previous backup", max_length=500)


class ProductionPromptInDB(ProductionPromptBase):
    """Schema for production prompt stored in database."""

    id: int
    promoted_at: datetime
    promoted_by: uuid.UUID
    previous_backup_path: Optional[str]
    version: int

    class Config:
        orm_mode = True


class ProductionPromptResponse(ProductionPromptInDB):
    """Schema for production prompt API response with promoter details."""

    promoter_name: Optional[str] = Field(None, description="Name of promoter (from join)")

    class Config:
        orm_mode = True


class PromotionResult(BaseModel):
    """Schema for promotion operation result."""

    success: bool = Field(..., description="Whether promotion succeeded")
    production_prompt: ProductionPromptInDB = Field(..., description="Updated production prompt")
    backup_path: str = Field(..., description="S3/Spaces path to backup of previous prompt")
    audit_log_id: int = Field(..., description="ID of audit log entry created")
    quality_metrics: Optional[dict] = Field(None, description="Optional quality comparison metrics")

    class Config:
        orm_mode = True
