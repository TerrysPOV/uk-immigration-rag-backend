"""
CloudDriveConnection model for OAuth credentials storage.

Feature 011: Document Ingestion & Batch Processing
T034: CloudDriveConnection with encrypted tokens via pgcrypto
"""

from datetime import datetime
from enum import Enum
from sqlalchemy import Column, String, ForeignKey, TIMESTAMP, Enum as SQLEnum, func, UniqueConstraint, text

from .base import Base


class CloudProvider(str, Enum):
    """Supported cloud drive providers"""
    GOOGLE_DRIVE = "google_drive"
    ONEDRIVE = "onedrive"
    SHAREPOINT = "sharepoint"


class CloudDriveConnection(Base):
    """
    OAuth credentials and connection details for cloud drive providers.

    Stores provider type, OAuth tokens (encrypted at rest using pgcrypto),
    token expiry, user ID, and selected folder path.

    Security (FR-022): OAuth tokens stored encrypted with user-specific keys
    using PBKDF2 (100k iterations) via pgcrypto.
    """
    __tablename__ = "cloud_drive_connections"

    connection_id = Column(String(36), primary_key=True)  # UUID
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)

    # Provider details
    provider = Column(SQLEnum(CloudProvider), nullable=False, index=True)
    folder_path = Column(String, nullable=False)  # Selected folder path

    # OAuth tokens (stored encrypted - see backend/src/utils/oauth_encryption.py)
    # Note: These columns store encrypted bytes as text (base64 encoded)
    access_token_encrypted = Column(String, nullable=False)
    refresh_token_encrypted = Column(String, nullable=False)

    # Token expiry
    token_expiry = Column(TIMESTAMP, nullable=False)

    # Timestamps
    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint('user_id', 'provider', name='uq_user_provider'),  # One connection per user+provider
    )

    @property
    def is_token_expired(self) -> bool:
        """Check if OAuth token has expired"""
        return datetime.utcnow() >= self.token_expiry

    @property
    def expires_in_seconds(self) -> int:
        """Calculate seconds until token expiry"""
        if self.is_token_expired:
            return 0

        delta = self.token_expiry - datetime.utcnow()
        return int(delta.total_seconds())

    @property
    def expires_soon(self) -> bool:
        """Check if token expires within 5 minutes (proactive refresh)"""
        return self.expires_in_seconds < 300  # 5 minutes

    def __repr__(self):
        return (
            f"<CloudDriveConnection(connection_id={self.connection_id}, "
            f"user_id={self.user_id}, provider={self.provider}, "
            f"folder={self.folder_path}, expired={self.is_token_expired})>"
        )
