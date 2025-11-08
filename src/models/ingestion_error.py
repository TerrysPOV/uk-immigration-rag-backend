"""
IngestionError model for processing failure tracking.

Feature 011: Document Ingestion & Batch Processing
T035: IngestionError with CSV export method (FR-050)
"""

from enum import Enum
from sqlalchemy import Column, String, ForeignKey, TIMESTAMP, Enum as SQLEnum, Boolean, func, Text

from .base import Base


class ErrorType(str, Enum):
    """Error type classification"""
    NETWORK = "network"
    VALIDATION = "validation"
    PARSING = "parsing"
    AUTHENTICATION = "authentication"
    UNKNOWN = "unknown"


class IngestionError(Base):
    """
    Record of processing failures.

    Contains document name, ingestion job ID, error type, error message,
    stack trace (for logs), timestamp, and resolved status (true if
    successfully retried).

    Supports CSV export with FR-050 columns:
    - Timestamp
    - Document Name
    - Error Type
    - Error Message
    - User ID
    - Job ID
    """
    __tablename__ = "ingestion_errors"

    error_id = Column(String(36), primary_key=True)  # UUID
    ingestion_job_id = Column(String(36), ForeignKey("ingestion_jobs.job_id"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)

    # Document details
    document_name = Column(String, nullable=False)

    # Error details
    error_type = Column(SQLEnum(ErrorType), nullable=False, index=True)
    error_message = Column(String, nullable=False)
    stack_trace = Column(Text, nullable=True)  # For logs (not exposed in UI)

    # Resolution tracking
    resolved = Column(Boolean, default=False)  # True if successfully retried

    # Timestamps
    timestamp = Column(TIMESTAMP, server_default=func.now(), nullable=False, index=True)
    resolved_at = Column(TIMESTAMP, nullable=True)

    # Timestamps
    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now(), nullable=False)

    def to_csv_row(self) -> dict:
        """
        Export error as CSV row with FR-050 columns.

        Returns dict with keys:
        - Timestamp
        - Document Name
        - Error Type
        - Error Message
        - User ID
        - Job ID
        """
        return {
            "Timestamp": self.timestamp.isoformat(),
            "Document Name": self.document_name,
            "Error Type": self.error_type.value,
            "Error Message": self.error_message,
            "User ID": self.user_id,
            "Job ID": self.ingestion_job_id
        }

    @staticmethod
    def csv_headers() -> list:
        """Return CSV headers matching FR-050 specification"""
        return [
            "Timestamp",
            "Document Name",
            "Error Type",
            "Error Message",
            "User ID",
            "Job ID"
        ]

    def __repr__(self):
        return (
            f"<IngestionError(error_id={self.error_id}, document={self.document_name}, "
            f"type={self.error_type}, resolved={self.resolved})>"
        )
