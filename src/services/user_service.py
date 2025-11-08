"""
T035: UserService
Business logic layer for user management operations

Service Methods:
- assign_role(user_id, role_name, assigned_by): Assign role to user with audit log
- update_status(user_id, status, updated_by): Activate/deactivate user with audit log
- get_users_by_role(role_name): Retrieve all users with specific role
- reset_password(user_id, performed_by): Generate password reset token
- get_user_by_id(user_id): Retrieve single user by ID
- get_users(filters): List users with pagination and filters
- update_user(user_id, data, updated_by): Update user with audit log
- update_last_login(user_id): Update last login timestamp

Authentication Notes:
- Password hashing uses bcrypt (handled by auth service)
- Reset tokens expire after 24 hours
- Audit logs created for all role/status changes (FR-AP-008)
"""

from typing import List, Optional, Dict
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_
import uuid
import secrets

from ..models.user import User, UserCreate, UserUpdate, UserWithRole, UserInDB
from ..models.audit_log import AuditLog


class UserService:
    """
    Service layer for user management operations.

    Handles user CRUD, role assignment, status updates, and password resets.
    Creates audit logs for all sensitive operations.
    """

    def __init__(self, db: Session):
        """
        Initialize UserService with database session.

        Args:
            db: SQLAlchemy database session
        """
        self.db = db

    def get_user_by_id(self, user_id: str) -> Optional[UserInDB]:
        """
        Retrieve single user by ID.

        Args:
            user_id: User UUID

        Returns:
            User object or None if not found

        Logs:
            - INFO: User retrieved successfully
            - ERROR: User not found
        """
        user = self.db.query(User).filter(User.id == user_id).first()

        if not user:
            print(f"[UserService] ERROR: User with ID '{user_id}' not found")
            return None

        print(f"[UserService] Retrieved user '{user.username}' (id={user_id})")
        return UserInDB.from_orm(user)

    def get_users(
        self,
        role: Optional[str] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
        page: int = 1,
        limit: int = 50,
    ) -> tuple[List[UserWithRole], int]:
        """
        List users with pagination and filters.

        Args:
            role: Filter by role (optional)
            status: Filter by status (optional)
            search: Search username or email (optional)
            page: Page number (1-indexed)
            limit: Results per page

        Returns:
            Tuple of (user list, total count)

        Logs:
            - INFO: Number of users retrieved with filter details
        """
        query = self.db.query(User)

        # Apply filters
        if role:
            query = query.filter(User.role == role)
        if status:
            query = query.filter(User.status == status)
        if search:
            search_pattern = f"%{search}%"
            query = query.filter(
                or_(User.username.ilike(search_pattern), User.email.ilike(search_pattern))
            )

        # Get total count
        total_count = query.count()

        # Apply pagination
        offset = (page - 1) * limit
        users = query.offset(offset).limit(limit).all()

        user_list = [UserWithRole.from_orm(user) for user in users]

        print(
            f"[UserService] Retrieved {len(user_list)} users (page={page}, limit={limit}, role={role}, status={status}, search={search})"
        )
        print(f"[UserService] Total users matching criteria: {total_count}")

        return user_list, total_count

    def get_users_by_role(self, role_name: str) -> List[UserWithRole]:
        """
        Retrieve all users with specific role.

        Args:
            role_name: Role name to filter by

        Returns:
            List of users with matching role

        Logs:
            - INFO: Number of users with role
        """
        users = self.db.query(User).filter(User.role == role_name).all()
        user_list = [UserWithRole.from_orm(user) for user in users]

        print(f"[UserService] Found {len(user_list)} users with role '{role_name}'")
        return user_list

    def assign_role(
        self,
        user_id: str,
        role_name: str,
        assigned_by: str,
        ip_address: str,
        user_agent: Optional[str] = None,
    ) -> UserInDB:
        """
        Assign role to user with audit log.

        Args:
            user_id: User UUID to update
            role_name: New role name
            assigned_by: User ID performing the assignment (for audit log)
            ip_address: Client IP address
            user_agent: Client user agent (optional)

        Returns:
            Updated user

        Raises:
            ValueError: If user not found or role invalid

        Logs:
            - INFO: Role assigned successfully
            - ERROR: User not found or role assignment failed
        """
        user = self.db.query(User).filter(User.id == user_id).first()

        if not user:
            error_msg = f"User with ID '{user_id}' not found"
            print(f"[UserService] ERROR: {error_msg}")
            raise ValueError(error_msg)

        # Store old role for audit log
        old_role = user.role

        # Update role
        user.role = role_name

        try:
            self.db.commit()
            self.db.refresh(user)

            # Create audit log entry
            audit_log = AuditLog(
                user_id=assigned_by,
                action_type="role_change",
                resource_type="user",
                resource_id=user_id,
                old_value={"role": old_role},
                new_value={"role": role_name},
                ip_address=ip_address,
                user_agent=user_agent,
            )
            self.db.add(audit_log)
            self.db.commit()

            print(
                f"[UserService] Assigned role '{role_name}' to user '{user.username}' (old_role='{old_role}')"
            )
            print(
                f"[UserService] Audit log created: action=role_change, performed_by={assigned_by}"
            )

            return UserInDB.from_orm(user)

        except IntegrityError as e:
            self.db.rollback()
            error_msg = f"Failed to assign role: {str(e)}"
            print(f"[UserService] ERROR: {error_msg}")
            raise ValueError(error_msg)

    def update_status(
        self,
        user_id: str,
        status: str,
        updated_by: str,
        ip_address: str,
        user_agent: Optional[str] = None,
    ) -> UserInDB:
        """
        Update user status (active/inactive) with audit log.

        Args:
            user_id: User UUID to update
            status: New status ('active' or 'inactive')
            updated_by: User ID performing the update (for audit log)
            ip_address: Client IP address
            user_agent: Client user agent (optional)

        Returns:
            Updated user

        Raises:
            ValueError: If user not found or status invalid

        Logs:
            - INFO: Status updated successfully
            - ERROR: User not found or status update failed
        """
        user = self.db.query(User).filter(User.id == user_id).first()

        if not user:
            error_msg = f"User with ID '{user_id}' not found"
            print(f"[UserService] ERROR: {error_msg}")
            raise ValueError(error_msg)

        if status not in User.ALLOWED_STATUSES:
            error_msg = f"Invalid status '{status}'. Must be one of {User.ALLOWED_STATUSES}"
            print(f"[UserService] ERROR: {error_msg}")
            raise ValueError(error_msg)

        # Store old status for audit log
        old_status = user.status

        # Update status
        user.status = status

        try:
            self.db.commit()
            self.db.refresh(user)

            # Create audit log entry
            audit_log = AuditLog(
                user_id=updated_by,
                action_type="update",
                resource_type="user",
                resource_id=user_id,
                old_value={"status": old_status},
                new_value={"status": status},
                ip_address=ip_address,
                user_agent=user_agent,
            )
            self.db.add(audit_log)
            self.db.commit()

            print(
                f"[UserService] Updated status for user '{user.username}' from '{old_status}' to '{status}'"
            )
            print(f"[UserService] Audit log created: action=update, performed_by={updated_by}")

            return UserInDB.from_orm(user)

        except IntegrityError as e:
            self.db.rollback()
            error_msg = f"Failed to update status: {str(e)}"
            print(f"[UserService] ERROR: {error_msg}")
            raise ValueError(error_msg)

    def reset_password(
        self, user_id: str, performed_by: str, ip_address: str, user_agent: Optional[str] = None
    ) -> Dict[str, str]:
        """
        Generate password reset token for user.

        Args:
            user_id: User UUID
            performed_by: User ID performing the reset (for audit log)
            ip_address: Client IP address
            user_agent: Client user agent (optional)

        Returns:
            Dict with reset_token and expiry_timestamp

        Raises:
            ValueError: If user not found

        Logs:
            - INFO: Reset token generated
            - ERROR: User not found

        Note:
            Token expires after 24 hours
            Email sending is mocked for now (FR-AP-003)
        """
        user = self.db.query(User).filter(User.id == user_id).first()

        if not user:
            error_msg = f"User with ID '{user_id}' not found"
            print(f"[UserService] ERROR: {error_msg}")
            raise ValueError(error_msg)

        # Generate secure random token (32 bytes = 64 hex characters)
        reset_token = secrets.token_urlsafe(32)
        expiry = datetime.utcnow() + timedelta(hours=24)

        # Create audit log entry
        audit_log = AuditLog(
            user_id=performed_by,
            action_type="update",
            resource_type="user",
            resource_id=user_id,
            old_value=None,
            new_value={"action": "password_reset_initiated"},
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self.db.add(audit_log)
        self.db.commit()

        print(
            f"[UserService] Generated password reset token for user '{user.username}' (expires: {expiry})"
        )
        print(
            f"[UserService] Audit log created: action=update (password_reset), performed_by={performed_by}"
        )

        # TODO: Send email with reset token (mocked for now)
        print(f"[UserService] MOCK EMAIL: Send reset token to {user.email}")

        return {
            "reset_token": reset_token,
            "expiry_timestamp": expiry.isoformat(),
            "user_email": user.email,
        }

    def update_user(
        self,
        user_id: str,
        user_data: UserUpdate,
        updated_by: str,
        ip_address: str,
        user_agent: Optional[str] = None,
    ) -> UserInDB:
        """
        Update user with audit log.

        Args:
            user_id: User UUID to update
            user_data: Update data (partial)
            updated_by: User ID performing the update (for audit log)
            ip_address: Client IP address
            user_agent: Client user agent (optional)

        Returns:
            Updated user

        Raises:
            ValueError: If user not found or update invalid

        Logs:
            - INFO: User updated successfully
            - ERROR: User not found or update failed
        """
        user = self.db.query(User).filter(User.id == user_id).first()

        if not user:
            error_msg = f"User with ID '{user_id}' not found"
            print(f"[UserService] ERROR: {error_msg}")
            raise ValueError(error_msg)

        # Store old values for audit log
        old_values = {}
        new_values = {}

        if user_data.email is not None and user_data.email != user.email:
            old_values["email"] = user.email
            new_values["email"] = user_data.email
            user.email = user_data.email

        if user_data.role is not None and user_data.role != user.role:
            old_values["role"] = user.role
            new_values["role"] = user_data.role
            user.role = user_data.role

        if user_data.status is not None and user_data.status != user.status:
            old_values["status"] = user.status
            new_values["status"] = user_data.status
            user.status = user_data.status

        if not old_values:
            print(f"[UserService] No changes detected for user '{user.username}'")
            return UserInDB.from_orm(user)

        try:
            self.db.commit()
            self.db.refresh(user)

            # Create audit log entry
            audit_log = AuditLog(
                user_id=updated_by,
                action_type="update",
                resource_type="user",
                resource_id=user_id,
                old_value=old_values,
                new_value=new_values,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            self.db.add(audit_log)
            self.db.commit()

            print(f"[UserService] Updated user '{user.username}': {list(new_values.keys())}")
            print(f"[UserService] Audit log created: action=update, performed_by={updated_by}")

            return UserInDB.from_orm(user)

        except IntegrityError as e:
            self.db.rollback()
            error_msg = f"Failed to update user: {str(e)}"
            print(f"[UserService] ERROR: {error_msg}")
            raise ValueError(error_msg)

    def update_last_login(self, user_id: str) -> None:
        """
        Update user's last login timestamp.

        Args:
            user_id: User UUID

        Logs:
            - INFO: Last login updated
            - ERROR: User not found

        Note:
            Does not create audit log (login events are tracked separately)
        """
        user = self.db.query(User).filter(User.id == user_id).first()

        if not user:
            print(f"[UserService] ERROR: User with ID '{user_id}' not found")
            return

        user.last_login_at = datetime.utcnow()

        try:
            self.db.commit()
            print(f"[UserService] Updated last_login_at for user '{user.username}'")

        except IntegrityError as e:
            self.db.rollback()
            print(f"[UserService] ERROR: Failed to update last_login_at: {str(e)}")

    def create_user(
        self,
        user_data: UserCreate,
        created_by: str,
        ip_address: str,
        user_agent: Optional[str] = None,
    ) -> UserInDB:
        """
        Create new user with audit log.

        Args:
            user_data: User creation data
            created_by: User ID performing the creation (for audit log)
            ip_address: Client IP address
            user_agent: Client user agent (optional)

        Returns:
            Created user

        Raises:
            ValueError: If username/email already exists

        Logs:
            - INFO: User created successfully
            - ERROR: User creation failed

        Note:
            Password hashing should be handled before calling this method
        """
        # Check if username already exists
        existing_user = (
            self.db.query(User)
            .filter(or_(User.username == user_data.username, User.email == user_data.email))
            .first()
        )

        if existing_user:
            if existing_user.username == user_data.username:
                error_msg = f"Username '{user_data.username}' already exists"
            else:
                error_msg = f"Email '{user_data.email}' already exists"
            print(f"[UserService] ERROR: {error_msg}")
            raise ValueError(error_msg)

        # Hash password (mock for now - should use bcrypt)
        # TODO: Integrate with auth service for proper password hashing
        hashed_password = f"hashed_{user_data.password}"

        new_user = User(
            id=str(uuid.uuid4()),
            username=user_data.username,
            email=user_data.email,
            hashed_password=hashed_password,
            role=user_data.role,
            status="active",
        )

        try:
            self.db.add(new_user)
            self.db.commit()
            self.db.refresh(new_user)

            # Create audit log entry
            audit_log = AuditLog(
                user_id=created_by,
                action_type="create",
                resource_type="user",
                resource_id=new_user.id,
                old_value=None,
                new_value={
                    "username": new_user.username,
                    "email": new_user.email,
                    "role": new_user.role,
                    "status": new_user.status,
                },
                ip_address=ip_address,
                user_agent=user_agent,
            )
            self.db.add(audit_log)
            self.db.commit()

            print(f"[UserService] Created user '{new_user.username}' with role '{new_user.role}'")
            print(f"[UserService] Audit log created: action=create, performed_by={created_by}")

            return UserInDB.from_orm(new_user)

        except IntegrityError as e:
            self.db.rollback()
            error_msg = f"Failed to create user: {str(e)}"
            print(f"[UserService] ERROR: {error_msg}")
            raise ValueError(error_msg)
