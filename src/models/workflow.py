"""
T029: Workflow Model
Database model for automated process definitions with trigger conditions

Entity: Workflow
Purpose: Automated process definition with trigger conditions and execution steps
Table: workflows

Features:
- JSONB trigger_conditions for flexible automation
- Status (active/inactive)
- Circular dependency detection on save (FR-WM-005)
- One-to-many relationships with WorkflowStep and WorkflowExecution
"""

from datetime import datetime
from typing import Optional
from sqlalchemy import Column, VARCHAR, TEXT, TIMESTAMP, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship, validates
from pydantic import BaseModel, Field, validator
import uuid

from .base import Base


class Workflow(Base):
    """
    Workflow model for automated process definitions.

    Attributes:
        id (uuid): Primary key
        workflow_name (str): Workflow name (1-200 characters)
        description (str): Workflow purpose
        trigger_conditions (dict): Conditions for automatic execution (JSONB)
        status (str): Workflow status (active/inactive)
        created_by (uuid): Foreign key to users.id
        created_at (datetime): Creation timestamp
        updated_at (datetime): Last update timestamp

    Validation:
        - workflow_name must be 1-200 characters
        - trigger_conditions must be valid JSON with keys: ['event_type', 'filters', 'schedule']
        - status must be one of: ['active', 'inactive']
        - Circular dependency detection on save (FR-WM-005)

    Relationships:
        - creator: Many-to-one with User
        - steps: One-to-many with WorkflowStep (cascade on delete)
        - executions: One-to-many with WorkflowExecution (cascade on delete)
    """

    __tablename__ = "workflows"

    # Columns
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_name = Column(VARCHAR(200), nullable=False)
    description = Column(TEXT, nullable=True)
    trigger_conditions = Column(JSONB, nullable=False)
    status = Column(VARCHAR(20), nullable=False, default="inactive")
    created_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at = Column(TIMESTAMP, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        TIMESTAMP, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Allowed status values
    ALLOWED_STATUSES = ["active", "inactive"]

    # Relationships (to be defined after all models are created)
    # creator = relationship("User", back_populates="workflows")
    # steps = relationship("WorkflowStep", back_populates="workflow", cascade="all, delete-orphan", order_by="WorkflowStep.step_number")
    # executions = relationship("WorkflowExecution", back_populates="workflow", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_workflows_status", "status"),
        Index("idx_workflows_created_by", "created_by"),
    )

    @validates("workflow_name")
    def validate_workflow_name(self, key, value):
        """Validate workflow_name is 1-200 characters."""
        if not (1 <= len(value) <= 200):
            raise ValueError(f"workflow_name must be 1-200 characters, got {len(value)}")
        return value

    @validates("trigger_conditions")
    def validate_trigger_conditions(self, key, value):
        """Validate trigger_conditions has required keys."""
        required_keys = ["event_type", "filters", "schedule"]
        if not isinstance(value, dict):
            raise ValueError("trigger_conditions must be a JSON object")

        missing_keys = set(required_keys) - set(value.keys())
        if missing_keys:
            raise ValueError(f"trigger_conditions missing required keys: {missing_keys}")

        return value

    @validates("status")
    def validate_status(self, key, value):
        """Validate status is in allowed list."""
        if value not in self.ALLOWED_STATUSES:
            raise ValueError(f"status must be one of {self.ALLOWED_STATUSES}, got '{value}'")
        return value

    def __repr__(self):
        return f"<Workflow(id='{self.id}', name='{self.workflow_name}', status='{self.status}')>"


# Pydantic schemas for API validation
class WorkflowBase(BaseModel):
    """Base workflow schema."""

    workflow_name: str = Field(..., description="Workflow name", min_length=1, max_length=200)
    description: Optional[str] = Field(None, description="Workflow purpose")
    trigger_conditions: dict = Field(..., description="Conditions for automatic execution")
    status: str = Field(default="inactive", description="Workflow status (active/inactive)")

    @validator("trigger_conditions")
    def validate_trigger_structure(cls, v):
        required_keys = ["event_type", "filters", "schedule"]
        missing = set(required_keys) - set(v.keys())
        if missing:
            raise ValueError(f"trigger_conditions missing required keys: {missing}")
        return v

    @validator("status")
    def validate_status_value(cls, v):
        if v not in Workflow.ALLOWED_STATUSES:
            raise ValueError(f"status must be one of {Workflow.ALLOWED_STATUSES}")
        return v


class WorkflowCreate(WorkflowBase):
    """Schema for creating new workflow."""

    pass


class WorkflowUpdate(BaseModel):
    """Schema for updating existing workflow (partial update)."""

    workflow_name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    trigger_conditions: Optional[dict] = None
    status: Optional[str] = None


class WorkflowInDB(WorkflowBase):
    """Schema for workflow stored in database."""

    id: uuid.UUID
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True


class WorkflowWithSteps(WorkflowInDB):
    """Schema for workflow with step count."""

    step_count: int = Field(..., description="Number of workflow steps")
    execution_count: int = Field(default=0, description="Total executions")
