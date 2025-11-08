"""
ProcessingQueue model for document queue management.

Feature 011: Document Ingestion & Batch Processing
T032: ProcessingQueue with priority ordering and worker assignment
"""

from datetime import datetime
from enum import Enum
from sqlalchemy import Column, String, Integer, ForeignKey, TIMESTAMP, Enum as SQLEnum, func, Index

from .base import Base


class QueuePriority(str, Enum):
    """Queue priority levels"""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class ProcessingQueue(Base):
    """
    Queue of documents awaiting ingestion processing.

    Each entry has document identifier, source (URL/file/cloud), priority,
    queued timestamp, and assigned worker ID. Supports priority-based ordering.
    """
    __tablename__ = "processing_queue"

    queue_id = Column(String(36), primary_key=True)  # UUID
    ingestion_job_id = Column(String(36), ForeignKey("ingestion_jobs.job_id"), nullable=False, index=True)

    # Document details
    document_identifier = Column(String, nullable=False)  # URL, filename, or cloud file ID
    source_type = Column(String, nullable=False)  # 'url', 'file', 'cloud'

    # Queue management
    priority = Column(SQLEnum(QueuePriority), nullable=False, default=QueuePriority.NORMAL, index=True)
    worker_id = Column(String(36), nullable=True, index=True)  # Assigned worker (NULL = unassigned)

    # Timing
    queued_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    assigned_at = Column(TIMESTAMP, nullable=True)  # When worker was assigned

    # Timestamps
    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        # Index for priority queue ordering
        Index('idx_priority_queue', 'priority', 'queued_at'),
        # Index for worker assignment lookup
        Index('idx_worker_assignment', 'worker_id', 'assigned_at'),
    )

    @property
    def is_assigned(self) -> bool:
        """Check if queue entry is assigned to a worker"""
        return self.worker_id is not None

    @property
    def queue_time_seconds(self) -> int:
        """Calculate time in queue (seconds)"""
        if self.assigned_at:
            return int((self.assigned_at - self.queued_at).total_seconds())
        return int((datetime.utcnow() - self.queued_at).total_seconds())

    def __repr__(self):
        return (
            f"<ProcessingQueue(queue_id={self.queue_id}, document={self.document_identifier}, "
            f"priority={self.priority}, worker={self.worker_id})>"
        )
