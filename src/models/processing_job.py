"""
ProcessingJob model for individual document processing tasks.

Feature 011: Document Ingestion & Batch Processing
T033: ProcessingJob with progress tracking, retry count, and ETA calculation
"""

from datetime import datetime, timedelta
from enum import Enum
from sqlalchemy import Column, String, Integer, Float, ForeignKey, TIMESTAMP, Enum as SQLEnum, func
from sqlalchemy.orm import validates

from .base import Base


class ProcessingStatus(str, Enum):
    """Processing job status"""
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ProcessingJob(Base):
    """
    Individual document processing task.

    Tracks document ID, ingestion job ID, worker ID, status, progress percentage,
    error message (if failed), timing, and retry count.
    """
    __tablename__ = "processing_jobs"

    processing_job_id = Column(String(36), primary_key=True)  # UUID
    ingestion_job_id = Column(String(36), ForeignKey("ingestion_jobs.job_id"), nullable=False, index=True)
    document_id = Column(String(36), nullable=False)

    # Worker assignment
    worker_id = Column(String(36), nullable=True, index=True)

    # Status and progress
    status = Column(SQLEnum(ProcessingStatus), nullable=False, default=ProcessingStatus.QUEUED, index=True)
    progress = Column(Float, nullable=False, default=0.0)  # 0-100 percentage

    # Error handling
    error_message = Column(String, nullable=True)
    retry_count = Column(Integer, nullable=False, default=0)

    # Timing
    start_time = Column(TIMESTAMP, nullable=True)
    end_time = Column(TIMESTAMP, nullable=True)

    # Timestamps
    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now(), nullable=False)

    @validates('progress')
    def validate_progress(self, key, value):
        """Validate progress is between 0-100"""
        if not (0 <= value <= 100):
            raise ValueError("progress must be between 0 and 100")
        return value

    @validates('status')
    def validate_status_transition(self, key, new_status):
        """Validate status transitions"""
        if not hasattr(self, 'status') or self.status is None:
            return new_status

        current_status = self.status
        valid_transitions = {
            ProcessingStatus.QUEUED: [ProcessingStatus.PROCESSING, ProcessingStatus.FAILED],
            ProcessingStatus.PROCESSING: [ProcessingStatus.COMPLETED, ProcessingStatus.FAILED],
            ProcessingStatus.COMPLETED: [],  # Final state
            ProcessingStatus.FAILED: [ProcessingStatus.QUEUED]  # Can retry
        }

        if new_status not in valid_transitions.get(current_status, []):
            raise ValueError(
                f"Invalid status transition from {current_status} to {new_status}"
            )

        return new_status

    @property
    def processing_time_seconds(self) -> int:
        """Calculate processing time in seconds"""
        if not self.start_time:
            return 0

        end = self.end_time or datetime.utcnow()
        return int((end - self.start_time).total_seconds())

    @property
    def eta_seconds(self) -> int:
        """
        Calculate estimated time remaining (ETA) in seconds.

        Uses current progress and elapsed time to estimate completion time.
        """
        if self.status != ProcessingStatus.PROCESSING or self.progress == 0:
            return 0

        elapsed = self.processing_time_seconds
        if elapsed == 0:
            return 0

        # Calculate rate: progress_percentage / elapsed_seconds
        rate = self.progress / elapsed

        # Calculate remaining progress
        remaining_progress = 100 - self.progress

        # Estimate remaining time
        if rate > 0:
            return int(remaining_progress / rate)

        return 0

    @property
    def eta_formatted(self) -> str:
        """Format ETA as human-readable string"""
        eta_secs = self.eta_seconds
        if eta_secs == 0:
            return "N/A"

        if eta_secs < 60:
            return f"{eta_secs} seconds"
        elif eta_secs < 3600:
            return f"{eta_secs // 60} minutes"
        else:
            return f"{eta_secs // 3600} hours"

    def __repr__(self):
        return (
            f"<ProcessingJob(processing_job_id={self.processing_job_id}, "
            f"status={self.status}, progress={self.progress:.1f}%, "
            f"retry_count={self.retry_count})>"
        )
