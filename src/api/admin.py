"""
Feature 012: Admin Panel API
T046-T052: Admin Panel API endpoints

Endpoints:
- GET /api/v1/admin/users - List users with pagination and filters
- PUT /api/v1/admin/users/{id}/role - Assign role to user
- PATCH /api/v1/admin/users/{id}/status - Update user status (active/inactive)
- POST /api/v1/admin/users/{id}/reset-password - Generate password reset token
- GET /api/v1/admin/config - Get system configuration
- PUT /api/v1/admin/config - Update system configuration
- GET /api/v1/admin/audit-logs - Get audit logs with filters

Authentication: Requires Admin role
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, Field

from ..database import get_db
from ..models.user import UserWithRole
from ..models.audit_log import AuditLogInDB, AuditLogFilter
from ..services.user_service import UserService
from ..services.audit_service import AuditService
from ..middleware.rbac import get_current_user_with_role


router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


# ============================================================================
# Request/Response Models
# ============================================================================


class RoleAssignmentRequest(BaseModel):
    """Request schema for role assignment."""

    role_name: str = Field(..., description="Role to assign (admin/caseworker/operator/viewer)")


class StatusUpdateRequest(BaseModel):
    """Request schema for status update."""

    status: str = Field(..., description="New status (active/inactive)")


class PasswordResetResponse(BaseModel):
    """Response schema for password reset."""

    reset_token: str
    expiry_timestamp: str
    user_email: str


class SystemConfiguration(BaseModel):
    """System configuration schema."""

    max_upload_size_mb: int = Field(
        ..., ge=1, le=1000, description="Maximum file upload size in MB"
    )
    session_timeout_minutes: int = Field(
        ..., ge=15, le=1440, description="Session timeout in minutes"
    )
    enable_analytics: bool = Field(..., description="Enable analytics tracking")
    retention_days: int = Field(
        ..., ge=30, le=2555, description="Data retention in days (7 years = 2555 days)"
    )


# ============================================================================
# T046: GET /api/v1/admin/users
# ============================================================================


@router.get("/users", response_model=dict)
async def list_users(
    request: Request,
    role: Optional[str] = Query(None, description="Filter by role"),
    status: Optional[str] = Query(None, description="Filter by status (active/inactive)"),
    search: Optional[str] = Query(None, description="Search username or email"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(50, ge=1, le=100, description="Results per page"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_with_role("admin")),
):
    """
    List users with pagination and filters (T046).

    Requires: Admin role

    Filters:
    - role: Filter by user role
    - status: Filter by account status
    - search: Search username or email (case-insensitive)

    Returns:
        Dict with users array and pagination metadata
    """
    try:
        user_service = UserService(db)
        users, total_count = user_service.get_users(
            role=role, status=status, search=search, page=page, limit=limit
        )

        return {
            "users": [UserWithRole.from_orm(user).dict() for user in users],
            "pagination": {
                "page": page,
                "limit": limit,
                "total_count": total_count,
                "total_pages": (total_count + limit - 1) // limit,
            },
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list users: {str(e)}",
        )


# ============================================================================
# T047: PUT /api/v1/admin/users/{id}/role
# ============================================================================


@router.put("/users/{user_id}/role", response_model=UserWithRole)
async def assign_user_role(
    request: Request,
    user_id: str,
    role_data: RoleAssignmentRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_with_role("admin")),
):
    """
    Assign role to user (T047).

    Requires: Admin role

    Creates audit log entry with old/new role values.

    Args:
        user_id: User UUID
        role_data: Role assignment data

    Returns:
        Updated user object
    """
    # T047a: Prevent self-modification (FR-AP-005)
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot modify your own account",
        )

    try:
        user_service = UserService(db)

        # Get client IP and user agent
        ip_address = request.client.host
        user_agent = request.headers.get("user-agent")

        updated_user = user_service.assign_role(
            user_id=user_id,
            role_name=role_data.role_name,
            assigned_by=current_user.id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        return updated_user

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to assign role: {str(e)}",
        )


# ============================================================================
# T048: PATCH /api/v1/admin/users/{id}/status
# ============================================================================


@router.patch("/users/{user_id}/status", response_model=UserWithRole)
async def update_user_status(
    request: Request,
    user_id: str,
    status_data: StatusUpdateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_with_role("admin")),
):
    """
    Update user account status (T048).

    Requires: Admin role

    Creates audit log entry with old/new status values.

    Args:
        user_id: User UUID
        status_data: Status update data (active/inactive)

    Returns:
        Updated user object
    """
    # T047a: Prevent self-modification (FR-AP-005)
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot modify your own account",
        )

    try:
        user_service = UserService(db)

        # Get client IP and user agent
        ip_address = request.client.host
        user_agent = request.headers.get("user-agent")

        updated_user = user_service.update_status(
            user_id=user_id,
            status=status_data.status,
            updated_by=current_user.id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        return updated_user

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update status: {str(e)}",
        )


# ============================================================================
# T049: POST /api/v1/admin/users/{id}/reset-password
# ============================================================================


@router.post("/users/{user_id}/reset-password", response_model=PasswordResetResponse)
async def reset_user_password(
    request: Request,
    user_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_with_role("admin")),
):
    """
    Generate password reset token for user (T049).

    Requires: Admin role

    Creates audit log entry.
    Sends email to user with reset link (mocked for now).

    Args:
        user_id: User UUID

    Returns:
        Password reset token and expiry timestamp
    """
    try:
        user_service = UserService(db)

        # Get client IP and user agent
        ip_address = request.client.host
        user_agent = request.headers.get("user-agent")

        reset_data = user_service.reset_password(
            user_id=user_id,
            performed_by=current_user.id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        return PasswordResetResponse(**reset_data)

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reset password: {str(e)}",
        )


# ============================================================================
# T050: GET /api/v1/admin/config
# ============================================================================


@router.get("/config", response_model=SystemConfiguration)
async def get_system_configuration(
    db: Session = Depends(get_db), current_user=Depends(get_current_user_with_role("admin"))
):
    """
    Get system configuration (T050).

    Requires: Admin role

    Returns:
        System configuration object
    """
    # TODO: Store config in database instead of hardcoding
    config = SystemConfiguration(
        max_upload_size_mb=100,
        session_timeout_minutes=60,
        enable_analytics=True,
        retention_days=2555,  # 7 years
    )

    return config


# ============================================================================
# T051: PUT /api/v1/admin/config
# ============================================================================


@router.put("/config", response_model=SystemConfiguration)
async def update_system_configuration(
    request: Request,
    config: SystemConfiguration,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_with_role("admin")),
):
    """
    Update system configuration (T051).

    Requires: Admin role

    Creates audit log entry with old/new configuration.
    Validates configuration ranges.

    Args:
        config: System configuration data

    Returns:
        Updated configuration object
    """
    try:
        audit_service = AuditService(db)

        # Get client IP and user agent
        ip_address = request.client.host
        user_agent = request.headers.get("user-agent")

        # TODO: Store config in database and get old values
        old_config = {
            "max_upload_size_mb": 100,
            "session_timeout_minutes": 60,
            "enable_analytics": True,
            "retention_days": 2555,
        }

        # Create audit log
        audit_service.log_action(
            user_id=current_user.id,
            action_type="config_change",
            resource_type="config",
            resource_id="system_config",
            old_value=old_config,
            new_value=config.dict(),
            ip_address=ip_address,
            user_agent=user_agent,
        )

        # TODO: Save config to database
        print(f"[AdminAPI] System configuration updated by {current_user.username}")

        return config

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update configuration: {str(e)}",
        )


# ============================================================================
# T052: GET /api/v1/admin/audit-logs
# ============================================================================


@router.get("/audit-logs", response_model=dict)
async def get_audit_logs(
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    action_type: Optional[str] = Query(None, description="Filter by action type"),
    resource_type: Optional[str] = Query(None, description="Filter by resource type"),
    start_date: Optional[datetime] = Query(None, description="Filter from this date"),
    end_date: Optional[datetime] = Query(None, description="Filter until this date"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(50, ge=1, le=100, description="Results per page"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_with_role("admin")),
):
    """
    Get audit logs with filters (T052).

    Requires: Admin role

    Filters:
    - user_id: Filter by user who performed action
    - action_type: Filter by action (create/update/delete/login/logout/config_change/role_change)
    - resource_type: Filter by resource (user/role/template/workflow/config/session)
    - start_date: Filter from this date
    - end_date: Filter until this date

    Returns:
        Dict with audit logs array and pagination metadata
    """
    try:
        audit_service = AuditService(db)

        filters = AuditLogFilter(
            user_id=user_id,
            action_type=action_type,
            resource_type=resource_type,
            start_date=start_date,
            end_date=end_date,
            page=page,
            limit=limit,
        )

        logs, total_count = audit_service.get_audit_logs(filters)

        return {
            "audit_logs": [AuditLogInDB.from_orm(log).dict() for log in logs],
            "pagination": {
                "page": page,
                "limit": limit,
                "total_count": total_count,
                "total_pages": (total_count + limit - 1) // limit,
            },
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve audit logs: {str(e)}",
        )


# ============================================================================
# T052a: GET /api/v1/admin/users/{id}/profile
# ============================================================================


class LoginHistoryEntry(BaseModel):
    """Login history entry schema."""

    timestamp: datetime
    ip_address: str
    user_agent: str
    success: bool


class UserProfile(BaseModel):
    """User profile response schema (FR-AP-006)."""

    user_id: str
    username: str
    email: str
    role: str
    status: str
    created_at: datetime
    last_modified_at: datetime
    assigned_permissions: List[str]
    activity_history: List[dict]  # Recent audit log entries
    login_history: List[LoginHistoryEntry]  # Last 10 logins


@router.get("/users/{user_id}/profile", response_model=UserProfile)
async def get_user_profile(
    user_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_with_role("admin")),
):
    """
    Get user profile with permissions, activity, and login history (T052a, FR-AP-006).

    Requires: Admin role

    Returns:
        UserProfile with full details including:
        - created_at, last_modified_at
        - assigned_permissions (from role)
        - activity_history (recent audit log entries)
        - login_history (last 10 logins with timestamps and IP addresses)
    """
    try:
        user_service = UserService(db)
        audit_service = AuditService(db)

        # Get user basic info
        user = user_service.get_user_by_id(user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User {user_id} not found",
            )

        # Get user's role permissions
        role_permissions = []
        if user.role:
            from ..services.role_service import RoleService

            role_service = RoleService(db)
            role_permissions = role_service.get_role_permissions(user.role)

        # Get recent activity (last 20 audit log entries)
        activity_filter = AuditLogFilter(
            user_id=user_id,
            page=1,
            limit=20,
        )
        activity_logs, _ = audit_service.get_audit_logs(activity_filter)

        # Get login history (last 10 logins)
        login_filter = AuditLogFilter(
            user_id=user_id,
            action_type="login",
            page=1,
            limit=10,
        )
        login_logs, _ = audit_service.get_audit_logs(login_filter)

        login_history = [
            LoginHistoryEntry(
                timestamp=log.timestamp,
                ip_address=log.ip_address or "Unknown",
                user_agent=log.user_agent or "Unknown",
                success=True,  # Assuming successful if logged
            )
            for log in login_logs
        ]

        profile = UserProfile(
            user_id=user.id,
            username=user.username,
            email=user.email,
            role=user.role or "viewer",
            status=user.status or "active",
            created_at=user.created_at,
            last_modified_at=user.updated_at or user.created_at,
            assigned_permissions=role_permissions,
            activity_history=[AuditLogInDB.from_orm(log).dict() for log in activity_logs],
            login_history=login_history,
        )

        return profile

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve user profile: {str(e)}",
        )
