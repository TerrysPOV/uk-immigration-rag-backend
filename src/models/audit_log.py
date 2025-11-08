"""
T033: AuditLog Model
Database model for immutable system change records (compliance and security)

Entity: AuditLog
Purpose: Immutable record of system changes for compliance and security
Table: audit_logs

Features:
- INSERT-only table (no UPDATE or DELETE operations)
- Monthly partitioning for query performance
- 7-year retention (UK government compliance requirement)
- IP address tracking (INET type)
- Old/new value diff tracking (JSONB)

CRITICAL: This table is immutable. No UPDATE or DELETE operations allowed.
"""

from datetime import datetime
from typing import Optional
from sqlalchemy import Column, BigInteger, VARCHAR, TIMESTAMP, ForeignKey, Index
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import relationship, validates
from pydantic import BaseModel, Field, validator
import ipaddress

from .base import Base


class AuditLog(Base):
    """
    AuditLog model for immutable system change records.

    CRITICAL: INSERT-ONLY MODEL
    - No UPDATE operations allowed
    - No DELETE operations allowed
    - Supports compliance audits and security forensics

    Attributes:
        id (int): Primary key (BIGSERIAL)
        timestamp (datetime): Action timestamp
        user_id (uuid): Foreign key to users.id
        action_type (str): Action type (create/update/delete/login/logout/config_change/role_change)
        resource_type (str): Resource affected (user/role/template/workflow/config/session)
        resource_id (str): ID of affected resource
        old_value (dict): State before change (JSONB)
        new_value (dict): State after change (JSONB)
        ip_address (str): Client IP address (INET)
        user_agent (str): Client user agent

    Validation:
        - action_type must be in allowed list
        - resource_type must be in allowed list
        - ip_address must be valid IPv4 or IPv6
        - Table is INSERT-only (enforced at service layer)

    Cascade Behavior:
        - ON DELETE RESTRICT for user_id (cannot delete users with audit logs)
        - Exception: Deleted users marked as "DELETED" but audit logs preserved

    Retention Policy:
        - 7 years (UK government compliance)
        - Monthly partitioning for performance
    """

    __tablename__ = "audit_logs"

    # Columns
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    timestamp = Column(TIMESTAMP, nullable=False, default=datetime.utcnow)
    user_id = Column(VARCHAR(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    action_type = Column(VARCHAR(50), nullable=False)
    resource_type = Column(VARCHAR(50), nullable=False)
    resource_id = Column(VARCHAR(100), nullable=True)
    old_value = Column(JSONB, nullable=True)
    new_value = Column(JSONB, nullable=True)
    ip_address = Column(INET, nullable=False)
    user_agent = Column(TEXT, nullable=True)

    # Allowed action types
    ALLOWED_ACTION_TYPES = [
        "create",
        "update",
        "delete",
        "login",
        "logout",
        "config_change",
        "role_change",
    ]

    # Allowed resource types
    ALLOWED_RESOURCE_TYPES = ["user", "role", "template", "workflow", "config", "session"]

    # Relationships (to be defined after all models are created)
    # user = relationship("User", back_populates="audit_logs")

    __table_args__ = (
        Index("idx_audit_logs_timestamp", "timestamp", postgresql_ops={"timestamp": "DESC"}),
        Index("idx_audit_logs_user", "user_id", "timestamp", postgresql_ops={"timestamp": "DESC"}),
        Index("idx_audit_logs_resource", "resource_type", "resource_id"),
        Index(
            "idx_audit_logs_action",
            "action_type",
            "timestamp",
            postgresql_ops={"timestamp": "DESC"},
        ),
    )

    @validates("action_type")
    def validate_action_type(self, key, value):
        """Validate action_type is in allowed list."""
        if value not in self.ALLOWED_ACTION_TYPES:
            raise ValueError(
                f"action_type must be one of {self.ALLOWED_ACTION_TYPES}, got '{value}'"
            )
        return value

    @validates("resource_type")
    def validate_resource_type(self, key, value):
        """Validate resource_type is in allowed list."""
        if value not in self.ALLOWED_RESOURCE_TYPES:
            raise ValueError(
                f"resource_type must be one of {self.ALLOWED_RESOURCE_TYPES}, got '{value}'"
            )
        return value

    @validates("ip_address")
    def validate_ip_address(self, key, value):
        """Validate ip_address is valid IPv4 or IPv6."""
        try:
            ipaddress.ip_address(value)
        except ValueError:
            raise ValueError(f"Invalid IP address: {value}")
        return value

    def __repr__(self):
        return f"<AuditLog(id={self.id}, user_id='{self.user_id}', action='{self.action_type}', resource='{self.resource_type}')>"


# Pydantic schemas for API validation
from sqlalchemy import TEXT


class AuditLogBase(BaseModel):
    """Base audit log schema."""

    action_type: str = Field(
        ..., description="Action type (create/update/delete/login/logout/config_change/role_change)"
    )
    resource_type: str = Field(
        ..., description="Resource affected (user/role/template/workflow/config/session)"
    )
    resource_id: Optional[str] = Field(None, description="ID of affected resource", max_length=100)
    old_value: Optional[dict] = Field(None, description="State before change")
    new_value: Optional[dict] = Field(None, description="State after change")
    ip_address: str = Field(..., description="Client IP address")
    user_agent: Optional[str] = Field(None, description="Client user agent")

    @validator("action_type")
    def validate_action(cls, v):
        if v not in AuditLog.ALLOWED_ACTION_TYPES:
            raise ValueError(f"action_type must be one of {AuditLog.ALLOWED_ACTION_TYPES}")
        return v

    @validator("resource_type")
    def validate_resource(cls, v):
        if v not in AuditLog.ALLOWED_RESOURCE_TYPES:
            raise ValueError(f"resource_type must be one of {AuditLog.ALLOWED_RESOURCE_TYPES}")
        return v

    @validator("ip_address")
    def validate_ip(cls, v):
        try:
            ipaddress.ip_address(v)
        except ValueError:
            raise ValueError(f"Invalid IP address: {v}")
        return v


class AuditLogCreate(AuditLogBase):
    """Schema for creating new audit log entry."""

    user_id: str = Field(..., description="User ID who performed action")


class AuditLogInDB(AuditLogBase):
    """Schema for audit log stored in database."""

    id: int
    timestamp: datetime
    user_id: str

    class Config:
        orm_mode = True


class AuditLogFilter(BaseModel):
    """Schema for filtering audit logs."""

    user_id: Optional[str] = Field(None, description="Filter by user ID")
    action_type: Optional[str] = Field(None, description="Filter by action type")
    resource_type: Optional[str] = Field(None, description="Filter by resource type")
    start_date: Optional[datetime] = Field(None, description="Filter from this date")
    end_date: Optional[datetime] = Field(None, description="Filter until this date")
    page: int = Field(default=1, description="Page number", ge=1)
    limit: int = Field(default=50, description="Results per page", ge=1, le=100)


class AuditLogDiff(BaseModel):
    """Schema for audit log value diff."""

    field: str = Field(..., description="Changed field name")
    old_value: Optional[str] = Field(None, description="Previous value")
    new_value: Optional[str] = Field(None, description="New value")
    change_type: str = Field(..., description="Type of change (added/modified/deleted)")
