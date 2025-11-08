"""
Document model for UK Government guidance documents.

Feature 011: Document Ingestion & Batch Processing
Feature 019: Process All Cross-Government Guidance Documents (Chrome tracking)
"""

from datetime import datetime
from sqlalchemy import Column, String, Text, Boolean, TIMESTAMP, func
from sqlalchemy.dialects.postgresql import JSONB

from .base import Base


class Document(Base):
    """
    Represents a scraped or uploaded UK Government guidance document.

    Tracks document content, processing status, chrome removal statistics,
    and reprocessing timestamp.

    Feature 019 additions:
    - chrome_removed: Flag indicating chrome was stripped
    - chrome_removal_stats: JSONB with removal statistics
    - reprocessed_at: Timestamp when document was reprocessed
    """

    __tablename__ = "documents"

    id = Column(String(36), primary_key=True)  # UUID
    url = Column(Text, nullable=False, unique=True, index=True)
    title = Column(Text, nullable=False)
    content = Column(Text, nullable=True)  # Raw HTML or text content

    # Processing status
    processing_success = Column(Boolean, nullable=True, index=True)
    processing_error = Column(Text, nullable=True)

    # Feature 019: Chrome tracking
    chrome_removed = Column(Boolean, nullable=False, server_default='false', default=False)
    chrome_removal_stats = Column(JSONB, nullable=True)
    reprocessed_at = Column(TIMESTAMP, nullable=True)

    # Metadata
    source = Column(String(50), nullable=True)  # 'url', 'upload', 'cloud'
    content_type = Column(String(100), nullable=True)
    file_size_bytes = Column(String, nullable=True)

    # Timestamps
    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self):
        return (
            f"<Document(id={self.id}, url={self.url[:50]}..., "
            f"processing_success={self.processing_success}, "
            f"chrome_removed={self.chrome_removed})>"
        )
