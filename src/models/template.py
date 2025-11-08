"""
T027: Template Model
Database model for reusable document structures with placeholder variables

Entity: Template
Purpose: Reusable document structure with placeholder variables
Table: templates

Features:
- JSONB content_structure for flexible layout
- Automatic versioning on update (creates TemplateVersion)
- Permission levels (public/private/shared)
- Placeholder validation (double-brace pattern {{variable_name}})
"""

from datetime import datetime
from typing import List, Optional
from sqlalchemy import Column, String, VARCHAR, TEXT, TIMESTAMP, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from sqlalchemy.orm import relationship, validates
from pydantic import BaseModel, Field, validator
import uuid
import re

from .base import Base


class Template(Base):
    """
    Template model for reusable document structures.

    Attributes:
        id (uuid): Primary key
        template_name (str): Template name (1-200 characters)
        description (str): Template purpose description
        content_structure (dict): JSON representation of template layout
        placeholders (list): Array of placeholder variable names
        permission_level (str): Visibility (public/private/shared)
        created_by (uuid): Foreign key to users.id
        created_at (datetime): Creation timestamp
        updated_at (datetime): Last update timestamp

    Validation:
        - template_name must be 1-200 characters
        - content_structure must be valid JSON with keys: ['header', 'body', 'footer']
        - placeholders must match double-brace pattern {{variable_name}}
        - permission_level must be one of: ['public', 'private', 'shared']
        - Each update creates new TemplateVersion entry (FR-TG-005)

    Relationships:
        - creator: Many-to-one with User
        - versions: One-to-many with TemplateVersion (cascade on delete)
    """

    __tablename__ = "templates"

    # Columns
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_name = Column(VARCHAR(200), nullable=False)
    description = Column(TEXT, nullable=True)
    content_structure = Column(JSONB, nullable=False)
    placeholders = Column(ARRAY(TEXT), nullable=False, default=list)
    permission_level = Column(VARCHAR(20), nullable=False, default="private")
    created_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at = Column(TIMESTAMP, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        TIMESTAMP, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Allowed permission levels
    ALLOWED_PERMISSION_LEVELS = ["public", "private", "shared"]

    # Placeholder pattern
    PLACEHOLDER_PATTERN = re.compile(r"\{\{([a-zA-Z0-9_]+)\}\}")

    # Relationships (to be defined after all models are created)
    # creator = relationship("User", back_populates="templates")
    # versions = relationship("TemplateVersion", back_populates="template", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_templates_created_by", "created_by"),
        Index("idx_templates_permission", "permission_level"),
    )

    @validates("template_name")
    def validate_template_name(self, key, value):
        """Validate template_name is 1-200 characters."""
        if not (1 <= len(value) <= 200):
            raise ValueError(f"template_name must be 1-200 characters, got {len(value)}")
        return value

    @validates("content_structure")
    def validate_content_structure(self, key, value):
        """Validate content_structure has required keys."""
        required_keys = ["header", "body", "footer"]
        if not isinstance(value, dict):
            raise ValueError("content_structure must be a JSON object")

        missing_keys = set(required_keys) - set(value.keys())
        if missing_keys:
            raise ValueError(f"content_structure missing required keys: {missing_keys}")

        return value

    @validates("placeholders")
    def validate_placeholders(self, key, value):
        """Validate placeholders match double-brace pattern."""
        for placeholder in value:
            if not self.PLACEHOLDER_PATTERN.match(f"{{{{{placeholder}}}}}"):
                raise ValueError(
                    f"Placeholder must match pattern {{{{variable_name}}}}, got: {placeholder}"
                )
        return value

    @validates("permission_level")
    def validate_permission_level(self, key, value):
        """Validate permission_level is in allowed list."""
        if value not in self.ALLOWED_PERMISSION_LEVELS:
            raise ValueError(
                f"permission_level must be one of {self.ALLOWED_PERMISSION_LEVELS}, got '{value}'"
            )
        return value

    def __repr__(self):
        return f"<Template(id='{self.id}', name='{self.template_name}', permission='{self.permission_level}')>"


# Pydantic schemas for API validation
class TemplateBase(BaseModel):
    """Base template schema."""

    template_name: str = Field(..., description="Template name", min_length=1, max_length=200)
    description: Optional[str] = Field(None, description="Template purpose description")
    content_structure: dict = Field(..., description="JSON template layout")
    placeholders: List[str] = Field(default_factory=list, description="Placeholder variable names")
    permission_level: str = Field(
        default="private", description="Visibility (public/private/shared)"
    )

    @validator("content_structure")
    def validate_structure_keys(cls, v):
        required_keys = ["header", "body", "footer"]
        missing = set(required_keys) - set(v.keys())
        if missing:
            raise ValueError(f"content_structure missing required keys: {missing}")
        return v

    @validator("permission_level")
    def validate_permission(cls, v):
        if v not in Template.ALLOWED_PERMISSION_LEVELS:
            raise ValueError(
                f"permission_level must be one of {Template.ALLOWED_PERMISSION_LEVELS}"
            )
        return v


class TemplateCreate(TemplateBase):
    """Schema for creating new template."""

    pass


class TemplateUpdate(BaseModel):
    """Schema for updating existing template (partial update)."""

    template_name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    content_structure: Optional[dict] = None
    placeholders: Optional[List[str]] = None
    permission_level: Optional[str] = None


class TemplateInDB(TemplateBase):
    """Schema for template stored in database."""

    id: uuid.UUID
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True


class TemplateWithVersions(TemplateInDB):
    """Schema for template with version count."""

    version_count: int = Field(..., description="Number of versions")
    current_version: Optional[int] = Field(None, description="Current version number")
