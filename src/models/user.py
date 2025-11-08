"""
T025: User Model (Extended)
Database model for system users with authentication and role-based access

Entity: User
Purpose: System user account with authentication credentials and role-based permissions
Table: users (extends existing table with role, status, last_login_at)

WCAG 2.1 AAA Compliance Note:
User model supports accessibility preferences storage in future metadata field.

Data Sovereignty: All user data stored on UK droplet (161.35.44.166)
"""

from datetime import datetime
from typing import Optional
from sqlalchemy import Column, String, VARCHAR, TIMESTAMP, ForeignKey
from sqlalchemy.orm import relationship, validates
from pydantic import BaseModel, Field, validator
import uuid

from .base import Base


class User(Base):
    """
    User model with role-based access control.

    Attributes:
        id (uuid): Primary key
        username (str): Login username (3-50 alphanumeric + underscore/hyphen)
        email (str): Email address (RFC 5322 format)
        hashed_password (str): Bcrypt hashed password
        role (str): Foreign key to roles.role_name
        status (str): Account status (active/inactive)
        created_at (datetime): Account creation timestamp
        last_login_at (datetime): Last successful login timestamp

    Validation:
        - email must match RFC 5322 format
        - username must be 3-50 alphanumeric characters
        - role must exist in roles table
        - status must be 'active' or 'inactive'
        - Administrators cannot delete their own account (FR-AP-005)

    Relationships:
        - role_obj: Many-to-one with Role
        - templates: One-to-many with Template (created templates)
        - workflows: One-to-many with Workflow (created workflows)
        - saved_queries: One-to-many with SavedQuery
        - audit_logs: One-to-many with AuditLog
    """

    __tablename__ = "users"

    # Columns
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username = Column(VARCHAR(100), unique=True, nullable=False)
    email = Column(VARCHAR(255), unique=True, nullable=False)
    hashed_password = Column(VARCHAR(255), nullable=False)
    role = Column(
        VARCHAR(50),
        ForeignKey("roles.role_name", ondelete="RESTRICT", onupdate="CASCADE"),
        nullable=False,
    )
    status = Column(VARCHAR(20), nullable=False, default="active")
    created_at = Column(TIMESTAMP, nullable=False, default=datetime.utcnow)
    last_login_at = Column(TIMESTAMP, nullable=True)

    # Relationships (to be defined after all models are created)
    # role_obj = relationship("Role", back_populates="users")

    # Allowed status values
    ALLOWED_STATUSES = ["active", "inactive"]

    @validates("email")
    def validate_email(self, key, value):
        """Validate email matches RFC 5322 format."""
        import re

        email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        if not re.match(email_pattern, value):
            raise ValueError(f"Invalid email format: {value}")
        return value

    @validates("username")
    def validate_username(self, key, value):
        """Validate username is 3-50 alphanumeric characters (a-z, 0-9, underscore, hyphen)."""
        import re

        if not (3 <= len(value) <= 50):
            raise ValueError(f"Username must be 3-50 characters, got {len(value)}")

        username_pattern = r"^[a-zA-Z0-9_-]+$"
        if not re.match(username_pattern, value):
            raise ValueError(
                f"Username must contain only alphanumeric characters, underscore, or hyphen: {value}"
            )
        return value

    @validates("status")
    def validate_status(self, key, value):
        """Validate status is 'active' or 'inactive'."""
        if value not in self.ALLOWED_STATUSES:
            raise ValueError(f"status must be one of {self.ALLOWED_STATUSES}, got '{value}'")
        return value

    def __repr__(self):
        return f"<User(id='{self.id}', username='{self.username}', role='{self.role}', status='{self.status}')>"


# Pydantic schemas for API validation
class UserBase(BaseModel):
    """Base user schema for API requests/responses."""

    username: str = Field(
        ..., description="Login username (3-50 characters)", min_length=3, max_length=50
    )
    email: str = Field(..., description="Email address (RFC 5322 format)")

    @validator("email")
    def validate_email_format(cls, v):
        import re

        email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        if not re.match(email_pattern, v):
            raise ValueError(f"Invalid email format: {v}")
        return v


class UserCreate(UserBase):
    """Schema for creating new user."""

    password: str = Field(..., description="Plain text password (will be hashed)", min_length=8)
    role: str = Field(..., description="User role (admin/caseworker/operator/viewer)")

    @validator("password")
    def validate_password_strength(cls, v):
        """Ensure password meets minimum security requirements."""
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v


class UserUpdate(BaseModel):
    """Schema for updating existing user (partial update)."""

    email: Optional[str] = None
    role: Optional[str] = None
    status: Optional[str] = None

    @validator("status")
    def validate_status_value(cls, v):
        if v is not None and v not in User.ALLOWED_STATUSES:
            raise ValueError(f"status must be one of {User.ALLOWED_STATUSES}")
        return v


class UserWithRole(UserBase):
    """Schema for user with role information (for admin panel)."""

    id: str
    role: str
    status: str
    last_login_at: Optional[datetime]
    created_at: datetime

    class Config:
        orm_mode = True


class UserInDB(UserBase):
    """Schema for user stored in database."""

    id: str
    hashed_password: str
    role: str
    status: str
    created_at: datetime
    last_login_at: Optional[datetime]

    class Config:
        orm_mode = True
