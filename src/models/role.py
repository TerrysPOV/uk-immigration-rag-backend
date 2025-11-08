"""
T024: Role Model
Database model for user roles and permissions

Entity: Role
Purpose: Permission level defining user capabilities within the system
Table: roles

WCAG 2.1 AAA Compliance Note:
Permissions include accessibility-related actions:
- 'a11y:configure' - Configure accessibility settings
- 'a11y:audit' - View accessibility audit results

Role Hierarchy (FR-AP-008):
admin > caseworker > operator > viewer
"""

from datetime import datetime
from typing import List, Optional
from sqlalchemy import Column, String, TIMESTAMP, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import validates
from pydantic import BaseModel, Field, validator

from .base import Base


class Role(Base):
    """
    Role model with permissions JSONB field.

    Attributes:
        role_name (str): Primary key, one of ['admin', 'caseworker', 'operator', 'viewer']
        permissions (dict): JSONB array of allowed actions
        description (str): Human-readable role description
        created_at (datetime): Role creation timestamp

    Validation:
        - role_name must be in allowed list
        - permissions must be valid JSON array
        - Permission hierarchy enforced

    Cascade:
        - ON DELETE RESTRICT (prevent deletion if users assigned)
        - ON UPDATE CASCADE (role name changes propagate)
    """

    __tablename__ = "roles"

    # Columns
    role_name = Column(String(50), primary_key=True, nullable=False)
    permissions = Column(JSONB, nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP, nullable=False, default=datetime.utcnow)

    # Allowed role names (enforced hierarchy)
    ALLOWED_ROLES = ["admin", "caseworker", "operator", "viewer"]

    # Permission categories
    PERMISSION_CATEGORIES = [
        "users",  # User management (read, write, delete)
        "config",  # Configuration management
        "audit",  # Audit log access
        "templates",  # Template operations
        "workflows",  # Workflow management
        "analytics",  # Analytics access
        "search",  # Search operations
        "a11y",  # Accessibility configuration/audit
    ]

    @validates("role_name")
    def validate_role_name(self, key, value):
        """Validate role_name is in allowed list."""
        if value not in self.ALLOWED_ROLES:
            raise ValueError(f"role_name must be one of {self.ALLOWED_ROLES}, got '{value}'")
        return value

    @validates("permissions")
    def validate_permissions(self, key, value):
        """
        Validate permissions is a valid JSONB array.

        Expected format:
        ["users:read", "users:write", "templates:read", ...]

        Pattern: "{category}:{action}"
        Actions: read, write, delete, execute, configure, audit
        """
        if not isinstance(value, list):
            raise ValueError("permissions must be a JSON array")

        for permission in value:
            if not isinstance(permission, str):
                raise ValueError(f"Permission must be string, got {type(permission)}")

            # Validate permission format: "category:action"
            if ":" not in permission:
                raise ValueError(f"Permission must be 'category:action' format, got '{permission}'")

            category, action = permission.split(":", 1)

            if category not in self.PERMISSION_CATEGORIES:
                raise ValueError(
                    f"Invalid category '{category}', must be one of {self.PERMISSION_CATEGORIES}"
                )

            # Valid actions
            valid_actions = ["read", "write", "delete", "execute", "configure", "audit"]
            if action not in valid_actions:
                raise ValueError(f"Invalid action '{action}', must be one of {valid_actions}")

        return value

    @classmethod
    def get_permission_hierarchy(cls):
        """
        Return permission hierarchy mapping.

        Returns:
            dict: Role -> inherited roles mapping
        """
        return {
            "admin": ["admin", "caseworker", "operator", "viewer"],
            "caseworker": ["caseworker", "operator", "viewer"],
            "operator": ["operator", "viewer"],
            "viewer": ["viewer"],
        }

    @classmethod
    def has_permission(cls, user_role: str, required_permission: str) -> bool:
        """
        Check if user role has required permission based on hierarchy.

        Args:
            user_role: User's current role
            required_permission: Permission to check

        Returns:
            bool: True if user has permission via role hierarchy
        """
        hierarchy = cls.get_permission_hierarchy()
        return required_permission in hierarchy.get(user_role, [])

    def __repr__(self):
        return f"<Role(role_name='{self.role_name}', permissions={len(self.permissions)})>"


# Pydantic schemas for API validation
class RoleBase(BaseModel):
    """Base role schema for API requests/responses."""

    role_name: str = Field(..., description="Role name (admin/caseworker/operator/viewer)")
    permissions: List[str] = Field(..., description="Array of permission strings")
    description: Optional[str] = Field(None, description="Human-readable description")

    @validator("role_name")
    def validate_role_name(cls, v):
        if v not in Role.ALLOWED_ROLES:
            raise ValueError(f"role_name must be one of {Role.ALLOWED_ROLES}")
        return v

    @validator("permissions")
    def validate_permissions_format(cls, v):
        for permission in v:
            if ":" not in permission:
                raise ValueError(f"Permission must be 'category:action' format: {permission}")
        return v


class RoleCreate(RoleBase):
    """Schema for creating new role."""

    pass


class RoleUpdate(BaseModel):
    """Schema for updating existing role (partial update)."""

    permissions: Optional[List[str]] = None
    description: Optional[str] = None


class RoleInDB(RoleBase):
    """Schema for role stored in database."""

    created_at: datetime

    class Config:
        orm_mode = True


class RoleWithUserCount(RoleInDB):
    """Schema for role with user count."""

    user_count: int = Field(..., description="Number of users with this role")
