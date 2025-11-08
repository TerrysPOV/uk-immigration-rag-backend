"""
T031: WorkflowExecution Model
Database model for historical record of workflow run instances

Entity: WorkflowExecution
Purpose: Historical record of workflow run instance
Table: workflow_executions

Features:
- Real-time execution status tracking
- Step-by-step execution logs (JSONB array)
- Progress percentage calculation
- Execution duration tracking
"""

from datetime import datetime
from typing import Optional
from sqlalchemy import Column, VARCHAR, TIMESTAMP, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship, validates
from pydantic import BaseModel, Field, validator
import uuid

from .base import Base


class WorkflowExecution(Base):
    """
    WorkflowExecution model for workflow run history.

    Attributes:
        execution_id (uuid): Primary key
        workflow_id (uuid): Foreign key to workflows.id
        status (str): Execution status (running/completed/failed/paused)
        started_at (datetime): Execution start timestamp
        completed_at (datetime): Execution end timestamp
        current_step (int): Currently executing step number
        execution_logs (dict): Array of step execution logs (JSONB)
        error_message (str): Error details if failed
        progress_percentage (int): Execution progress (0-100)
        triggered_by (str): Trigger source (manual/automatic/schedule)

    Validation:
        - status must be one of: ['running', 'completed', 'failed', 'paused']
        - completed_at must be after started_at
        - execution_logs must be array of objects with keys: ['step_number', 'status', 'duration_ms', 'output']
        - progress_percentage must be 0-100
        - triggered_by must be one of: ['manual', 'automatic', 'schedule']

    Cascade Behavior:
        - ON DELETE CASCADE (workflow deletion removes execution history)

    Relationships:
        - workflow: Many-to-one with Workflow
    """

    __tablename__ = "workflow_executions"

    # Columns
    execution_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id = Column(
        UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )
    status = Column(VARCHAR(20), nullable=False)
    started_at = Column(TIMESTAMP, nullable=False, default=datetime.utcnow)
    completed_at = Column(TIMESTAMP, nullable=True)
    current_step = Column(Integer, nullable=True)
    execution_logs = Column(JSONB, nullable=False, default=list)
    error_message = Column(TEXT, nullable=True)
    progress_percentage = Column(Integer, nullable=False, default=0)
    triggered_by = Column(VARCHAR(50), nullable=False)

    # Allowed status values
    ALLOWED_STATUSES = ["running", "completed", "failed", "paused"]

    # Allowed trigger sources
    ALLOWED_TRIGGERS = ["manual", "automatic", "schedule"]

    # Relationships (to be defined after all models are created)
    # workflow = relationship("Workflow", back_populates="executions")

    __table_args__ = (
        Index(
            "idx_workflow_executions_workflow",
            "workflow_id",
            "started_at",
            postgresql_ops={"started_at": "DESC"},
        ),
        Index("idx_workflow_executions_status", "status"),
    )

    @validates("status")
    def validate_status(self, key, value):
        """Validate status is in allowed list."""
        if value not in self.ALLOWED_STATUSES:
            raise ValueError(f"status must be one of {self.ALLOWED_STATUSES}, got '{value}'")
        return value

    @validates("triggered_by")
    def validate_triggered_by(self, key, value):
        """Validate triggered_by is in allowed list."""
        if value not in self.ALLOWED_TRIGGERS:
            raise ValueError(f"triggered_by must be one of {self.ALLOWED_TRIGGERS}, got '{value}'")
        return value

    @validates("progress_percentage")
    def validate_progress_percentage(self, key, value):
        """Validate progress_percentage is 0-100."""
        if not (0 <= value <= 100):
            raise ValueError(f"progress_percentage must be 0-100, got {value}")
        return value

    @validates("execution_logs")
    def validate_execution_logs(self, key, value):
        """Validate execution_logs is array of valid log objects."""
        if not isinstance(value, list):
            raise ValueError("execution_logs must be a JSON array")

        for log_entry in value:
            if not isinstance(log_entry, dict):
                raise ValueError("Each execution log entry must be a JSON object")

            required_keys = ["step_number", "status", "duration_ms", "output"]
            missing_keys = set(required_keys) - set(log_entry.keys())
            if missing_keys:
                raise ValueError(f"Execution log entry missing required keys: {missing_keys}")

        return value

    def __repr__(self):
        return f"<WorkflowExecution(id='{self.execution_id}', workflow_id='{self.workflow_id}', status='{self.status}', progress={self.progress_percentage}%)>"


# Pydantic schemas for API validation
from sqlalchemy import TEXT


class ExecutionLogEntry(BaseModel):
    """Schema for single execution log entry."""

    step_number: int = Field(..., description="Step number", ge=1)
    status: str = Field(..., description="Step status (pending/running/completed/failed)")
    duration_ms: int = Field(..., description="Step duration in milliseconds", ge=0)
    output: Optional[dict] = Field(None, description="Step output data")
    error: Optional[str] = Field(None, description="Error message if failed")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Log entry timestamp")


class WorkflowExecutionBase(BaseModel):
    """Base workflow execution schema."""

    status: str = Field(..., description="Execution status (running/completed/failed/paused)")
    current_step: Optional[int] = Field(None, description="Currently executing step number", ge=1)
    progress_percentage: int = Field(
        default=0, description="Execution progress (0-100)", ge=0, le=100
    )
    triggered_by: str = Field(..., description="Trigger source (manual/automatic/schedule)")

    @validator("status")
    def validate_status_value(cls, v):
        if v not in WorkflowExecution.ALLOWED_STATUSES:
            raise ValueError(f"status must be one of {WorkflowExecution.ALLOWED_STATUSES}")
        return v

    @validator("triggered_by")
    def validate_trigger(cls, v):
        if v not in WorkflowExecution.ALLOWED_TRIGGERS:
            raise ValueError(f"triggered_by must be one of {WorkflowExecution.ALLOWED_TRIGGERS}")
        return v


class WorkflowExecutionCreate(WorkflowExecutionBase):
    """Schema for creating new workflow execution."""

    workflow_id: uuid.UUID = Field(..., description="Parent workflow ID")


class WorkflowExecutionUpdate(BaseModel):
    """Schema for updating existing workflow execution (partial update)."""

    status: Optional[str] = None
    current_step: Optional[int] = None
    progress_percentage: Optional[int] = Field(None, ge=0, le=100)
    error_message: Optional[str] = None


class WorkflowExecutionInDB(WorkflowExecutionBase):
    """Schema for workflow execution stored in database."""

    execution_id: uuid.UUID
    workflow_id: uuid.UUID
    started_at: datetime
    completed_at: Optional[datetime]
    execution_logs: list[ExecutionLogEntry] = Field(default_factory=list)
    error_message: Optional[str]

    class Config:
        orm_mode = True


class WorkflowExecutionStatus(WorkflowExecutionInDB):
    """Schema for real-time execution status monitoring."""

    duration_seconds: Optional[int] = Field(None, description="Total execution duration in seconds")
    estimated_completion: Optional[datetime] = Field(None, description="Estimated completion time")
