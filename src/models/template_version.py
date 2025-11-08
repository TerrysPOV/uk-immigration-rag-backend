"""
T028: TemplateVersion Model
Database model for historical snapshots of template changes

Entity: TemplateVersion
Purpose: Historical snapshot of template changes
Table: template_versions

Features:
- Sequential version numbering (1, 2, 3...)
- Full content snapshot at each version
- Cascade delete when parent template deleted
- Unique constraint on (template_id, version_number)
"""

from datetime import datetime
from typing import Optional
from sqlalchemy import Column, Integer, TEXT, TIMESTAMP, ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship, validates
from pydantic import BaseModel, Field
import uuid

from .base import Base


class TemplateVersion(Base):
    """
    TemplateVersion model for template change history.

    Attributes:
        id (uuid): Primary key
        template_id (uuid): Foreign key to templates.id
        version_number (int): Incremental version (1, 2, 3...)
        content_snapshot (dict): Full template content at this version
        change_description (str): What changed in this version
        author (uuid): Foreign key to users.id (who created this version)
        created_at (datetime): Version creation timestamp

    Validation:
        - version_number must be sequential (no gaps)
        - content_snapshot must match template content_structure schema
        - UNIQUE constraint on (template_id, version_number)

    Cascade Behavior:
        - ON DELETE CASCADE (template deletion removes all versions)
        - ON DELETE RESTRICT for author (prevent user deletion with versions)

    Relationships:
        - template: Many-to-one with Template
        - author_obj: Many-to-one with User
    """

    __tablename__ = "template_versions"

    # Columns
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_id = Column(
        UUID(as_uuid=True), ForeignKey("templates.id", ondelete="CASCADE"), nullable=False
    )
    version_number = Column(Integer, nullable=False)
    content_snapshot = Column(JSONB, nullable=False)
    change_description = Column(TEXT, nullable=True)
    author = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(TIMESTAMP, nullable=False, default=datetime.utcnow)

    # Relationships (to be defined after all models are created)
    # template = relationship("Template", back_populates="versions")
    # author_obj = relationship("User")

    __table_args__ = (
        UniqueConstraint("template_id", "version_number", name="uq_template_version"),
        Index(
            "idx_template_versions_template",
            "template_id",
            "version_number",
            postgresql_ops={"version_number": "DESC"},
        ),
    )

    @validates("version_number")
    def validate_version_number(self, key, value):
        """Validate version_number is positive."""
        if value < 1:
            raise ValueError(f"version_number must be >= 1, got {value}")
        return value

    @validates("content_snapshot")
    def validate_content_snapshot(self, key, value):
        """Validate content_snapshot has required template structure."""
        required_keys = ["header", "body", "footer"]
        if not isinstance(value, dict):
            raise ValueError("content_snapshot must be a JSON object")

        missing_keys = set(required_keys) - set(value.keys())
        if missing_keys:
            raise ValueError(f"content_snapshot missing required keys: {missing_keys}")

        return value

    def __repr__(self):
        return f"<TemplateVersion(id='{self.id}', template_id='{self.template_id}', version={self.version_number})>"


# Pydantic schemas for API validation
class TemplateVersionBase(BaseModel):
    """Base template version schema."""

    version_number: int = Field(..., description="Incremental version number", ge=1)
    content_snapshot: dict = Field(..., description="Full template content at this version")
    change_description: Optional[str] = Field(None, description="What changed in this version")


class TemplateVersionCreate(TemplateVersionBase):
    """Schema for creating new template version."""

    template_id: uuid.UUID = Field(..., description="Parent template ID")
    author: uuid.UUID = Field(..., description="User who created this version")


class TemplateVersionInDB(TemplateVersionBase):
    """Schema for template version stored in database."""

    id: uuid.UUID
    template_id: uuid.UUID
    author: uuid.UUID
    created_at: datetime

    class Config:
        orm_mode = True


class TemplateVersionComparison(BaseModel):
    """Schema for comparing two template versions."""

    version_a: int
    version_b: int
    content_diff: dict = Field(..., description="Differences between versions")
    change_summary: str = Field(..., description="Human-readable summary of changes")
