"""
T024: PlaygroundAuditLog Model
Database model for immutable compliance trail of playground operations

Entity: PlaygroundAuditLog
Purpose: Audit trail for all playground operations
Table: playground_audit_logs

Features:
- Immutable records (never updated or deleted)
- JSONB context for flexible metadata storage
- Event type enum validation
- Outcome tracking (success/failure)
- Timestamp indexing for fast recent activity queries
"""

from datetime import datetime
from typing import Optional
from sqlalchemy import Column, BigInteger, VARCHAR, TIMESTAMP, ForeignKey, Index, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship, validates
from pydantic import BaseModel, Field
from enum import Enum
import uuid

from .base import Base


class AuditEventType(str, Enum):
    """Enum for playground audit event types."""

    TEST_ANALYSIS = "test_analysis"
    SAVE_VERSION = "save_version"
    PROMOTE = "promote"
    DELETE_VERSION = "delete_version"


class AuditOutcome(str, Enum):
    """Enum for audit log outcomes."""

    SUCCESS = "success"
    FAILURE = "failure"


class PlaygroundAuditLog(Base):
    """
    PlaygroundAuditLog model for compliance tracking.

    Attributes:
        id (int): Primary key (auto-increment)
        event_type (str): Enum: 'test_analysis', 'save_version', 'promote', 'delete_version'
        user_id (uuid): Foreign key to users.id
        prompt_version_id (uuid): Foreign key to prompt_versions.id (nullable for test_analysis)
        outcome (str): Enum: 'success', 'failure'
        context (dict): JSONB metadata (document_url, match counts, etc.)
        timestamp (datetime): When event occurred (indexed DESC)

    Validation:
        - event_type must be from AuditEventType enum
        - outcome must be from AuditOutcome enum
        - user_id must reference existing user
        - prompt_version_id can be null (for test_analysis events)

    Context JSONB Examples:
        test_analysis:
            {
                "document_url": "https://www.gov.uk/guidance/...",
                "production_matches": 5,
                "playground_matches": 7,
                "analysis_duration_ms": 12450
            }

        save_version:
            {
                "version_name": "improved-confidence-v2",
                "prompt_length": 2847
            }

        promote:
            {
                "version_id": "uuid-here",
                "backup_path": "s3://gov-ai-vectorization/prompt-backups/2025-11-02T14:30:00.md",
                "previous_promoter": "user-uuid"
            }

        delete_version:
            {
                "version_name": "test-prompt-1",
                "soft_delete": true,
                "retention_days": 30
            }

    Cascade Behavior:
        - ON DELETE RESTRICT when user deleted (preserve audit trail)
        - ON DELETE SET NULL when prompt_version deleted (preserve log)

    Relationships:
        - user: Many-to-one with User
        - prompt_version: Many-to-one with PromptVersion (nullable)

    Retention Policy:
        - NEVER deleted (permanent compliance trail)
        - Archival after 2 years to separate table (for performance)
    """

    __tablename__ = "playground_audit_logs"

    # Columns
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    event_type = Column(VARCHAR(50), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    prompt_version_id = Column(UUID(as_uuid=True), ForeignKey("prompt_versions.id", ondelete="SET NULL"), nullable=True)
    outcome = Column(VARCHAR(20), nullable=False)
    context = Column(JSONB, nullable=True)
    timestamp = Column(TIMESTAMP, nullable=False, default=datetime.utcnow)

    # Relationships (to be defined after all models are created)
    # user = relationship("User", back_populates="playground_audit_logs")
    # prompt_version = relationship("PromptVersion", back_populates="audit_logs")

    __table_args__ = (
        CheckConstraint(
            "event_type IN ('test_analysis', 'save_version', 'promote', 'delete_version')",
            name="ck_audit_log_event_type"
        ),
        CheckConstraint(
            "outcome IN ('success', 'failure')",
            name="ck_audit_log_outcome"
        ),
        Index("idx_playground_audit_logs_timestamp", "timestamp", postgresql_ops={"timestamp": "DESC"}),
        Index("idx_playground_audit_logs_user", "user_id"),
        Index("idx_playground_audit_logs_event_type", "event_type"),
    )

    @validates("event_type")
    def validate_event_type(self, key, value):
        """Validate event_type is from enum."""
        allowed = [e.value for e in AuditEventType]
        if value not in allowed:
            raise ValueError(f"event_type must be one of {allowed}, got '{value}'")
        return value

    @validates("outcome")
    def validate_outcome(self, key, value):
        """Validate outcome is from enum."""
        allowed = [e.value for e in AuditOutcome]
        if value not in allowed:
            raise ValueError(f"outcome must be one of {allowed}, got '{value}'")
        return value

    def __repr__(self):
        return f"<PlaygroundAuditLog(id={self.id}, event='{self.event_type}', user_id='{self.user_id}', outcome='{self.outcome}', timestamp='{self.timestamp}')>"


# Pydantic schemas for API validation
class PlaygroundAuditLogBase(BaseModel):
    """Base audit log schema."""

    event_type: AuditEventType = Field(..., description="Type of playground operation")
    outcome: AuditOutcome = Field(..., description="Operation outcome")
    context: Optional[dict] = Field(None, description="Additional metadata")


class PlaygroundAuditLogCreate(PlaygroundAuditLogBase):
    """Schema for creating new audit log entry."""

    user_id: uuid.UUID = Field(..., description="User who performed operation")
    prompt_version_id: Optional[uuid.UUID] = Field(None, description="Prompt version involved (if applicable)")


class PlaygroundAuditLogInDB(PlaygroundAuditLogBase):
    """Schema for audit log stored in database."""

    id: int
    user_id: uuid.UUID
    prompt_version_id: Optional[uuid.UUID]
    timestamp: datetime

    class Config:
        orm_mode = True


class PlaygroundAuditLogResponse(PlaygroundAuditLogInDB):
    """Schema for audit log API response with user details."""

    user_name: Optional[str] = Field(None, description="Name of user (from join)")
    version_name: Optional[str] = Field(None, description="Name of prompt version (from join)")

    class Config:
        orm_mode = True
