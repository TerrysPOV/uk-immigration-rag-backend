"""
T030: WorkflowStep Model
Database model for individual actions within a workflow process

Entity: WorkflowStep
Purpose: Individual action within a workflow process
Table: workflow_steps

Features:
- Step types: transform, api, notify, condition
- JSONB parameters for step-specific configuration
- Retry config with 4 strategies (FR-WM-011):
  - immediate (3 attempts, 0s delay)
  - exponential (5 attempts, 2x backoff with jitter)
  - manual (no retry, pause workflow)
  - circuit_breaker (open after 5 failures, 60s cooldown)
"""

from datetime import datetime
from typing import Optional
from sqlalchemy import Column, Integer, VARCHAR, ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship, validates
from pydantic import BaseModel, Field, validator
import uuid

from .base import Base


class WorkflowStep(Base):
    """
    WorkflowStep model for workflow process actions.

    Attributes:
        id (uuid): Primary key
        workflow_id (uuid): Foreign key to workflows.id
        step_number (int): Execution order (1, 2, 3...)
        step_type (str): Step type (transform/api/notify/condition)
        parameters (dict): Step-specific parameters (JSONB)
        input_source (str): Data source for this step
        output_destination (str): Where to send output
        retry_config (dict): Retry policy configuration (JSONB)
        created_at (datetime): Creation timestamp

    Validation:
        - step_type must be one of: ['transform', 'api', 'notify', 'condition']
        - parameters must be valid JSON
        - UNIQUE constraint on (workflow_id, step_number)
        - retry_config must have keys: ['strategy', 'max_attempts', 'backoff_multiplier']
        - strategy must be one of: ['immediate', 'exponential', 'manual', 'circuit_breaker']

    Cascade Behavior:
        - ON DELETE CASCADE (workflow deletion removes all steps)

    Relationships:
        - workflow: Many-to-one with Workflow
    """

    __tablename__ = "workflow_steps"

    # Columns
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id = Column(
        UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )
    step_number = Column(Integer, nullable=False)
    step_type = Column(VARCHAR(50), nullable=False)
    parameters = Column(JSONB, nullable=False)
    input_source = Column(VARCHAR(100), nullable=True)
    output_destination = Column(VARCHAR(100), nullable=True)
    retry_config = Column(JSONB, nullable=True)
    created_at = Column(TIMESTAMP, nullable=False, default=datetime.utcnow)

    # Allowed step types
    ALLOWED_STEP_TYPES = ["transform", "api", "notify", "condition"]

    # Allowed retry strategies
    ALLOWED_RETRY_STRATEGIES = ["immediate", "exponential", "manual", "circuit_breaker"]

    # Relationships (to be defined after all models are created)
    # workflow = relationship("Workflow", back_populates="steps")

    __table_args__ = (
        UniqueConstraint("workflow_id", "step_number", name="uq_workflow_step_order"),
        Index("idx_workflow_steps_workflow", "workflow_id"),
    )

    @validates("step_type")
    def validate_step_type(self, key, value):
        """Validate step_type is in allowed list."""
        if value not in self.ALLOWED_STEP_TYPES:
            raise ValueError(f"step_type must be one of {self.ALLOWED_STEP_TYPES}, got '{value}'")
        return value

    @validates("step_number")
    def validate_step_number(self, key, value):
        """Validate step_number is positive."""
        if value < 1:
            raise ValueError(f"step_number must be >= 1, got {value}")
        return value

    @validates("retry_config")
    def validate_retry_config(self, key, value):
        """Validate retry_config has required keys and valid strategy."""
        if value is None:
            return value

        if not isinstance(value, dict):
            raise ValueError("retry_config must be a JSON object")

        required_keys = ["strategy", "max_attempts", "backoff_multiplier"]
        missing_keys = set(required_keys) - set(value.keys())
        if missing_keys:
            raise ValueError(f"retry_config missing required keys: {missing_keys}")

        strategy = value.get("strategy")
        if strategy not in self.ALLOWED_RETRY_STRATEGIES:
            raise ValueError(
                f"retry_config strategy must be one of {self.ALLOWED_RETRY_STRATEGIES}, got '{strategy}'"
            )

        return value

    def __repr__(self):
        return f"<WorkflowStep(id='{self.id}', workflow_id='{self.workflow_id}', step_number={self.step_number}, type='{self.step_type}')>"


# Pydantic schemas for API validation
class RetryConfig(BaseModel):
    """Schema for retry configuration."""

    strategy: str = Field(
        ..., description="Retry strategy (immediate/exponential/manual/circuit_breaker)"
    )
    max_attempts: int = Field(..., description="Maximum retry attempts", ge=1)
    initial_delay_ms: Optional[int] = Field(None, description="Initial delay in milliseconds", ge=0)
    backoff_multiplier: float = Field(
        ..., description="Backoff multiplier (for exponential)", ge=1.0
    )
    max_delay_ms: Optional[int] = Field(None, description="Maximum delay in milliseconds", ge=0)
    jitter_percentage: Optional[int] = Field(
        None, description="Jitter percentage (0-100)", ge=0, le=100
    )

    @validator("strategy")
    def validate_strategy(cls, v):
        if v not in WorkflowStep.ALLOWED_RETRY_STRATEGIES:
            raise ValueError(f"strategy must be one of {WorkflowStep.ALLOWED_RETRY_STRATEGIES}")
        return v


class WorkflowStepBase(BaseModel):
    """Base workflow step schema."""

    step_number: int = Field(..., description="Execution order", ge=1)
    step_type: str = Field(..., description="Step type (transform/api/notify/condition)")
    parameters: dict = Field(..., description="Step-specific parameters")
    input_source: Optional[str] = Field(None, description="Data source", max_length=100)
    output_destination: Optional[str] = Field(
        None, description="Output destination", max_length=100
    )
    retry_config: Optional[RetryConfig] = Field(None, description="Retry policy configuration")

    @validator("step_type")
    def validate_type(cls, v):
        if v not in WorkflowStep.ALLOWED_STEP_TYPES:
            raise ValueError(f"step_type must be one of {WorkflowStep.ALLOWED_STEP_TYPES}")
        return v


class WorkflowStepCreate(WorkflowStepBase):
    """Schema for creating new workflow step."""

    workflow_id: uuid.UUID = Field(..., description="Parent workflow ID")


class WorkflowStepUpdate(BaseModel):
    """Schema for updating existing workflow step (partial update)."""

    step_type: Optional[str] = None
    parameters: Optional[dict] = None
    input_source: Optional[str] = None
    output_destination: Optional[str] = None
    retry_config: Optional[RetryConfig] = None


class WorkflowStepInDB(WorkflowStepBase):
    """Schema for workflow step stored in database."""

    id: uuid.UUID
    workflow_id: uuid.UUID
    created_at: datetime

    class Config:
        orm_mode = True
