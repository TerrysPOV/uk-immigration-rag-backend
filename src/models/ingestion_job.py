"""
IngestionJob model for document ingestion tracking.

Feature 011: Document Ingestion & Batch Processing
T030: IngestionJob model with status transitions and validation
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from sqlalchemy import Column, String, Integer, ForeignKey, TIMESTAMP, Enum as SQLEnum, func
from sqlalchemy.orm import validates

from .base import Base


class IngestionMethod(str, Enum):
    """Ingestion method types"""
    URL = "url"
    UPLOAD = "upload"
    CLOUD = "cloud"


class IngestionStatus(str, Enum):
    """Ingestion job status"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"
    CANCELLED = "cancelled"


class IngestionJob(Base):
    """
    Represents a single ingestion operation initiated by administrator.

    Tracks ingestion method (URL/upload/cloud), source details, status,
    timing, document counts, and creator user ID.

    Status transitions:
    - PENDING → IN_PROGRESS
    - IN_PROGRESS → COMPLETED | FAILED | PAUSED | CANCELLED
    - PAUSED → IN_PROGRESS | CANCELLED
    - FAILED/COMPLETED/CANCELLED → final states
    """
    __tablename__ = "ingestion_jobs"

    job_id = Column(String(36), primary_key=True)  # UUID
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)

    method = Column(SQLEnum(IngestionMethod), nullable=False, index=True)
    status = Column(SQLEnum(IngestionStatus), nullable=False, default=IngestionStatus.PENDING, index=True)

    # Source details (JSON stored as string)
    source_details = Column(String, nullable=False)  # URLs, file names, or cloud folder path

    # Document counts
    total_documents = Column(Integer, default=0)
    processed_documents = Column(Integer, default=0)
    failed_documents = Column(Integer, default=0)

    # Timing
    start_time = Column(TIMESTAMP, nullable=True)
    end_time = Column(TIMESTAMP, nullable=True)

    # Timestamps
    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now(), nullable=False)

    @validates('total_documents', 'processed_documents', 'failed_documents')
    def validate_document_counts(self, key, value):
        """Validate document counts are non-negative"""
        if value < 0:
            raise ValueError(f"{key} must be non-negative")
        return value

    @validates('status')
    def validate_status_transition(self, key, new_status):
        """Validate status transitions follow allowed paths"""
        if not hasattr(self, 'status') or self.status is None:
            # Initial state, allow any status
            return new_status

        current_status = self.status
        valid_transitions = {
            IngestionStatus.PENDING: [IngestionStatus.IN_PROGRESS, IngestionStatus.CANCELLED],
            IngestionStatus.IN_PROGRESS: [
                IngestionStatus.COMPLETED,
                IngestionStatus.FAILED,
                IngestionStatus.PAUSED,
                IngestionStatus.CANCELLED
            ],
            IngestionStatus.PAUSED: [IngestionStatus.IN_PROGRESS, IngestionStatus.CANCELLED],
            IngestionStatus.COMPLETED: [],  # Final state
            IngestionStatus.FAILED: [],  # Final state
            IngestionStatus.CANCELLED: []  # Final state
        }

        if new_status not in valid_transitions.get(current_status, []):
            raise ValueError(
                f"Invalid status transition from {current_status} to {new_status}"
            )

        return new_status

    @property
    def progress_percentage(self) -> float:
        """Calculate progress percentage"""
        if self.total_documents == 0:
            return 0.0
        return (self.processed_documents / self.total_documents) * 100

    @property
    def is_active(self) -> bool:
        """Check if job is currently active"""
        return self.status in [IngestionStatus.PENDING, IngestionStatus.IN_PROGRESS, IngestionStatus.PAUSED]

    @property
    def is_complete(self) -> bool:
        """Check if job has completed (success or failure)"""
        return self.status in [IngestionStatus.COMPLETED, IngestionStatus.FAILED, IngestionStatus.CANCELLED]

    def __repr__(self):
        return (
            f"<IngestionJob(job_id={self.job_id}, method={self.method}, "
            f"status={self.status}, progress={self.progress_percentage:.1f}%)>"
        )
