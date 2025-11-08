"""
T034: RoleService
Business logic layer for role management operations

Service Methods:
- get_all_roles(): Retrieve all roles with permission details
- get_role_permissions(role_name): Get permissions for specific role
- validate_permissions(permissions): Validate permission array format

Role Hierarchy (FR-AP-008):
admin > caseworker > operator > viewer
"""

from typing import List, Optional, Dict
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from ..models.role import Role, RoleCreate, RoleUpdate, RoleInDB, RoleWithUserCount
from ..models.user import User


class RoleService:
    """
    Service layer for role management operations.

    Enforces role hierarchy and permission validation.
    Provides business logic for role-based access control.
    """

    def __init__(self, db: Session):
        """
        Initialize RoleService with database session.

        Args:
            db: SQLAlchemy database session
        """
        self.db = db

    def get_all_roles(self) -> List[RoleWithUserCount]:
        """
        Retrieve all roles with user count.

        Returns:
            List of roles with permission details and user count

        Logs:
            - INFO: Number of roles retrieved
        """
        roles = self.db.query(Role).all()

        role_list = []
        for role in roles:
            # Count users with this role
            user_count = self.db.query(User).filter(User.role == role.role_name).count()

            role_dict = {
                "role_name": role.role_name,
                "permissions": role.permissions,
                "description": role.description,
                "created_at": role.created_at,
                "user_count": user_count,
            }
            role_list.append(RoleWithUserCount(**role_dict))

        print(f"[RoleService] Retrieved {len(role_list)} roles")
        return role_list

    def get_role_permissions(self, role_name: str) -> List[str]:
        """
        Get permissions for specific role.

        Args:
            role_name: Role name to query

        Returns:
            List of permission strings (e.g., ["users:read", "templates:write"])

        Raises:
            ValueError: If role not found

        Logs:
            - INFO: Role name and permission count
            - ERROR: Role not found
        """
        role = self.db.query(Role).filter(Role.role_name == role_name).first()

        if not role:
            print(f"[RoleService] ERROR: Role '{role_name}' not found")
            raise ValueError(f"Role '{role_name}' not found")

        print(f"[RoleService] Retrieved {len(role.permissions)} permissions for role '{role_name}'")
        return role.permissions

    def validate_permissions(self, permissions: List[str]) -> bool:
        """
        Validate permission array format.

        Expected format: ["category:action", ...]
        - Categories: users, config, audit, templates, workflows, analytics, search, a11y
        - Actions: read, write, delete, execute, configure, audit

        Args:
            permissions: List of permission strings to validate

        Returns:
            True if all permissions valid

        Raises:
            ValueError: If any permission invalid

        Logs:
            - INFO: Number of permissions validated
            - ERROR: Invalid permission format with details
        """
        valid_categories = [
            "users",
            "config",
            "audit",
            "templates",
            "workflows",
            "analytics",
            "search",
            "a11y",
        ]
        valid_actions = ["read", "write", "delete", "execute", "configure", "audit"]

        for permission in permissions:
            if ":" not in permission:
                error_msg = f"Invalid permission format '{permission}'. Expected 'category:action'"
                print(f"[RoleService] ERROR: {error_msg}")
                raise ValueError(error_msg)

            category, action = permission.split(":", 1)

            if category not in valid_categories:
                error_msg = f"Invalid category '{category}'. Must be one of {valid_categories}"
                print(f"[RoleService] ERROR: {error_msg}")
                raise ValueError(error_msg)

            if action not in valid_actions:
                error_msg = f"Invalid action '{action}'. Must be one of {valid_actions}"
                print(f"[RoleService] ERROR: {error_msg}")
                raise ValueError(error_msg)

        print(f"[RoleService] Validated {len(permissions)} permissions successfully")
        return True

    def create_role(self, role_data: RoleCreate) -> RoleInDB:
        """
        Create new role with permissions.

        Args:
            role_data: Role creation data

        Returns:
            Created role

        Raises:
            ValueError: If role already exists or permissions invalid

        Logs:
            - INFO: Role created successfully
            - ERROR: Role creation failed
        """
        # Validate permissions first
        self.validate_permissions(role_data.permissions)

        # Check if role already exists
        existing_role = self.db.query(Role).filter(Role.role_name == role_data.role_name).first()

        if existing_role:
            error_msg = f"Role '{role_data.role_name}' already exists"
            print(f"[RoleService] ERROR: {error_msg}")
            raise ValueError(error_msg)

        # Create new role
        new_role = Role(
            role_name=role_data.role_name,
            permissions=role_data.permissions,
            description=role_data.description,
        )

        try:
            self.db.add(new_role)
            self.db.commit()
            self.db.refresh(new_role)

            print(
                f"[RoleService] Created role '{new_role.role_name}' with {len(new_role.permissions)} permissions"
            )
            return RoleInDB.from_orm(new_role)

        except IntegrityError as e:
            self.db.rollback()
            print(f"[RoleService] ERROR: Database integrity error - {str(e)}")
            raise ValueError(f"Failed to create role: {str(e)}")

    def update_role(self, role_name: str, role_data: RoleUpdate) -> RoleInDB:
        """
        Update existing role permissions or description.

        Args:
            role_name: Role to update
            role_data: Update data

        Returns:
            Updated role

        Raises:
            ValueError: If role not found or permissions invalid

        Logs:
            - INFO: Role updated successfully
            - ERROR: Role update failed
        """
        role = self.db.query(Role).filter(Role.role_name == role_name).first()

        if not role:
            error_msg = f"Role '{role_name}' not found"
            print(f"[RoleService] ERROR: {error_msg}")
            raise ValueError(error_msg)

        # Validate new permissions if provided
        if role_data.permissions:
            self.validate_permissions(role_data.permissions)
            role.permissions = role_data.permissions

        if role_data.description is not None:
            role.description = role_data.description

        try:
            self.db.commit()
            self.db.refresh(role)

            print(f"[RoleService] Updated role '{role.role_name}'")
            return RoleInDB.from_orm(role)

        except IntegrityError as e:
            self.db.rollback()
            print(f"[RoleService] ERROR: Database integrity error - {str(e)}")
            raise ValueError(f"Failed to update role: {str(e)}")

    def get_role_hierarchy(self) -> Dict[str, List[str]]:
        """
        Get role hierarchy mapping (FR-AP-008).

        Returns:
            Dict mapping role -> list of inherited roles

        Example:
            {
                'admin': ['admin', 'caseworker', 'operator', 'viewer'],
                'caseworker': ['caseworker', 'operator', 'viewer'],
                ...
            }
        """
        return {
            "admin": ["admin", "caseworker", "operator", "viewer"],
            "caseworker": ["caseworker", "operator", "viewer"],
            "operator": ["operator", "viewer"],
            "viewer": ["viewer"],
        }

    def has_permission(self, user_role: str, required_permission: str) -> bool:
        """
        Check if user role has required permission via hierarchy.

        Args:
            user_role: User's current role
            required_permission: Permission to check

        Returns:
            True if user has permission via role hierarchy

        Logs:
            - INFO: Permission check result
        """
        hierarchy = self.get_role_hierarchy()
        has_perm = required_permission in hierarchy.get(user_role, [])

        print(
            f"[RoleService] Permission check: user_role='{user_role}', permission='{required_permission}', result={has_perm}"
        )
        return has_perm
