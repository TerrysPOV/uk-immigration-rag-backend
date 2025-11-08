"""
IngestionConfig model for batch processing configuration.

Feature 011: Document Ingestion & Batch Processing
T031: IngestionConfig with chunk_size/workers/retries validation
"""

from sqlalchemy import Column, String, Integer, ForeignKey, TIMESTAMP, Boolean, func, UniqueConstraint
from sqlalchemy.orm import validates

from .base import Base


class IngestionConfig(Base):
    """
    Configuration settings for batch processing.

    Includes chunk size (token count), parallel worker count, retry attempts,
    and optional user-specific overrides. System-wide defaults exist for
    first-time users (FR-057).
    """
    __tablename__ = "ingestion_configs"

    config_id = Column(String(36), primary_key=True)  # UUID
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)  # NULL = system default

    # Batch processing settings
    chunk_size = Column(Integer, nullable=False, default=512)  # Token count for document chunking
    parallel_workers = Column(Integer, nullable=False, default=4)  # 1-10 workers (FR-029)
    retry_attempts = Column(Integer, nullable=False, default=3)  # 0-5 retries (FR-030)

    # System default flag
    is_system_default = Column(Boolean, default=False)

    # Timestamps
    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint('user_id', name='uq_user_config'),  # One config per user
    )

    @validates('chunk_size')
    def validate_chunk_size(self, key, value):
        """Validate chunk_size > 0 (FR-028)"""
        if value <= 0:
            raise ValueError("chunk_size must be greater than 0")
        return value

    @validates('parallel_workers')
    def validate_parallel_workers(self, key, value):
        """Validate parallel_workers in range 1-10 (FR-029)"""
        if not (1 <= value <= 10):
            raise ValueError("parallel_workers must be between 1 and 10")
        return value

    @validates('retry_attempts')
    def validate_retry_attempts(self, key, value):
        """Validate retry_attempts in range 0-5 (FR-030)"""
        if not (0 <= value <= 5):
            raise ValueError("retry_attempts must be between 0 and 5")
        return value

    def __repr__(self):
        return (
            f"<IngestionConfig(config_id={self.config_id}, user_id={self.user_id}, "
            f"chunk_size={self.chunk_size}, workers={self.parallel_workers}, "
            f"retries={self.retry_attempts})>"
        )
