"""
RBAC (Role-Based Access Control) Middleware for Feature 011.

Enforces Admin role + canManagePipeline permission for ingestion endpoints.
Provides JWT authentication, permission checking, and GDPR-compliant audit logging.

Feature 011: Document Ingestion & Batch Processing
T066: Implement RBAC enforcement middleware
"""

import logging
import os
from datetime import datetime
from typing import Dict, Optional
from fastapi import Depends, HTTPException, WebSocket, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from pydantic import BaseModel

# Configure logging
logger = logging.getLogger(__name__)

# OAuth2 scheme for HTTP endpoints
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)

# Google OAuth configuration
GOOGLE_OAUTH_CLIENT_ID = os.getenv(
    "GOOGLE_OAUTH_CLIENT_ID",
    "882263909419-cstfjelmblbmppc29g6asr9m9c8rev73.apps.googleusercontent.com"
)


# ============================================================================
# Models
# ============================================================================


class User(BaseModel):
    """User model from JWT token"""

    user_id: str
    email: str
    username: str
    roles: list[str]
    permissions: list[str]
    realm: str


class AuditLog(BaseModel):
    """Audit log entry for GDPR Article 30 compliance"""

    timestamp: datetime
    user_id: str
    email: str
    roles: list[str]
    permissions: list[str]
    operation: str
    resource_type: str
    resource_id: Optional[str]
    ip_address: Optional[str]
    user_agent: Optional[str]
    success: bool
    failure_reason: Optional[str]


# ============================================================================
# JWT Token Verification
# ============================================================================


def verify_jwt_token(token: str) -> Dict:
    """
    Verify JWT token from Google OAuth.

    Uses Google's public keys from https://www.googleapis.com/oauth2/v3/certs
    to verify the ID token signature.

    Args:
        token: Google ID token (JWT bearer token)

    Returns:
        Decoded JWT payload with user info

    Raises:
        HTTPException: 401 if token invalid or expired
    """
    try:
        from google.oauth2 import id_token
        from google.auth.transport import requests

        # Verify the token using Google's verification
        idinfo = id_token.verify_oauth2_token(
            token,
            requests.Request(),
            GOOGLE_OAUTH_CLIENT_ID
        )

        # Verify the issuer
        if idinfo['iss'] not in ['accounts.google.com', 'https://accounts.google.com']:
            raise ValueError('Wrong issuer')

        logger.info(f"Google OAuth token verified for user: {idinfo.get('email')}")
        return idinfo

    except ValueError as e:
        logger.error(f"Google OAuth token verification failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Google authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception as e:
        logger.error(f"Token verification error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed",
            headers={"WWW-Authenticate": "Bearer"},
        )


def extract_user_from_token(payload: Dict) -> User:
    """
    Extract user information from Google ID token payload.

    Google ID token structure:
    - sub: Google user ID
    - email: user email
    - name: full name
    - picture: profile picture URL
    - email_verified: boolean

    Roles and permissions are mapped based on email domain or specific users.
    This can be extended to use a database mapping in the future.

    Args:
        payload: Decoded Google ID token payload

    Returns:
        User object with roles and permissions
    """
    user_id = payload.get("sub")
    email = payload.get("email", "")
    name = payload.get("name", "")
    username = email.split("@")[0] if email else "unknown"

    # Map roles and permissions based on email
    # TODO: Replace with database-backed role mapping
    roles = ["User"]  # Default role for all authenticated users
    permissions = ["canViewDashboard"]  # Default permission

    # Admin users (customize this list or use environment variable)
    admin_emails = os.getenv("ADMIN_EMAILS", "").split(",")
    if email in admin_emails or email.endswith("@gov.uk"):
        roles.append("Admin")
        permissions.extend(["canManagePipeline", "canManageUsers"])

    # Examiner role for specific domain or users
    examiner_emails = os.getenv("EXAMINER_EMAILS", "").split(",")
    if email in examiner_emails:
        roles.append("examiner")
        permissions.append("canManagePipeline")

    # Editor role
    editor_emails = os.getenv("EDITOR_EMAILS", "").split(",")
    if email in editor_emails:
        roles.append("editor")
        permissions.extend(["canEditTemplates", "canManagePipeline"])

    logger.info(f"Extracted user from Google token: {email} (roles: {roles})")

    return User(
        user_id=user_id,
        email=email,
        username=username,
        roles=roles,
        permissions=permissions,
        realm="google",
    )


# ============================================================================
# HTTP Endpoint Authentication
# ============================================================================


async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    """
    Get current user from JWT token (for HTTP endpoints).

    This is the main authentication dependency for FastAPI routes.

    Args:
        token: JWT bearer token from Authorization header

    Returns:
        User object with roles and permissions

    Raises:
        HTTPException: 401 if authentication fails

    Example:
        @router.get("/protected")
        async def protected_route(user: User = Depends(get_current_user)):
            return {"user": user.username}
    """
    payload = verify_jwt_token(token)
    user = extract_user_from_token(payload)

    logger.info(
        f"Authenticated user: {user.username} (roles: {user.roles}, permissions: {user.permissions})"
    )

    return user


# ============================================================================
# WebSocket Authentication
# ============================================================================


async def get_current_user_websocket(token: str, db: Optional[Session] = None) -> User:
    """
    Authenticate WebSocket connection via JWT token query parameter.

    WebSocket connections cannot use Authorization headers, so token
    is passed as query parameter: ?token=Bearer%20<jwt>

    Args:
        token: JWT token (with or without "Bearer " prefix)
        db: Database session (optional, for audit logging)

    Returns:
        User object with roles and permissions

    Raises:
        HTTPException: 401 if authentication fails

    Example:
        @router.websocket("/ws")
        async def websocket_endpoint(
            websocket: WebSocket,
            token: str = Query(...)
        ):
            user = await get_current_user_websocket(token)
            await websocket.accept()
    """
    # Remove "Bearer " prefix if present
    if token.startswith("Bearer "):
        token = token[7:]

    payload = verify_jwt_token(token)
    user = extract_user_from_token(payload)

    logger.info(f"WebSocket authenticated: {user.username} (roles: {user.roles})")

    return user


# ============================================================================
# Permission Enforcement
# ============================================================================


def require_admin_pipeline_permission(user: User = Depends(get_current_user)) -> User:
    """
    Enforce Admin role + canManagePipeline permission.

    Required for all Feature 011 ingestion and processing endpoints.

    Args:
        user: Authenticated user from get_current_user dependency

    Returns:
        User object if authorized

    Raises:
        HTTPException: 403 if user lacks required role or permission

    Example:
        @router.get("/processing/status")
        async def get_status(
            user: User = Depends(require_admin_pipeline_permission)
        ):
            return {"status": "ok"}
    """
    # Check Admin role
    if "Admin" not in user.roles:
        logger.warning(
            f"Access denied for {user.username}: missing Admin role (has roles: {user.roles})"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required for ingestion operations",
        )

    # Check canManagePipeline permission
    if "canManagePipeline" not in user.permissions:
        logger.warning(
            f"Access denied for {user.username}: missing canManagePipeline permission (has permissions: {user.permissions})"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="canManagePipeline permission required for ingestion operations",
        )

    logger.info(f"Authorization granted for {user.username}: Admin + canManagePipeline")

    return user


def require_ingestion_permission(user: User = Depends(get_current_user)) -> User:
    """
    Enforce general ingestion permission (less strict than admin).

    Use for read-only ingestion endpoints or user-scoped operations.

    Args:
        user: Authenticated user from get_current_user dependency

    Returns:
        User object if authorized

    Raises:
        HTTPException: 403 if user lacks canManagePipeline permission

    Example:
        @router.get("/processing/history")
        async def get_history(
            user: User = Depends(require_ingestion_permission)
        ):
            return {"history": []}
    """
    # Only check canManagePipeline permission (no Admin role required)
    if "canManagePipeline" not in user.permissions:
        logger.warning(f"Access denied for {user.username}: missing canManagePipeline permission")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="canManagePipeline permission required to access ingestion data",
        )

    return user


# ============================================================================
# Audit Logging (GDPR Article 30 Compliance)
# ============================================================================


async def audit_ingestion_access(
    user: User,
    operation: str,
    resource_type: str = "ingestion_job",
    resource_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    success: bool = True,
    failure_reason: Optional[str] = None,
    db: Optional[Session] = None,
):
    """
    Log ingestion access for GDPR Article 30 compliance.

    All access to processing endpoints must be audited with:
    - Timestamp (UTC)
    - User identity (user_id, email)
    - User roles and permissions
    - Operation performed
    - Resource accessed
    - Success/failure status
    - IP address and user agent (optional)

    Logs are written to structured logger and optionally to database.

    Args:
        user: Authenticated user
        operation: Operation name (e.g., "view_status", "start_ingestion")
        resource_type: Type of resource (default: "ingestion_job")
        resource_id: Resource identifier (e.g., job_id)
        ip_address: Client IP address (optional)
        user_agent: Client user agent (optional)
        success: Whether operation succeeded
        failure_reason: Reason for failure if success=False
        db: Database session for persistent audit log (optional)

    Example:
        await audit_ingestion_access(
            user=user,
            operation="start_url_ingestion",
            resource_id="job-123",
            ip_address="203.0.113.42",
            success=True
        )
    """
    audit_entry = AuditLog(
        timestamp=datetime.utcnow(),
        user_id=user.user_id,
        email=user.email,
        roles=user.roles,
        permissions=user.permissions,
        operation=operation,
        resource_type=resource_type,
        resource_id=resource_id,
        ip_address=ip_address,
        user_agent=user_agent,
        success=success,
        failure_reason=failure_reason,
    )

    # Log to structured logger (JSON format for log aggregation)
    logger.info(
        "Ingestion access audit",
        extra={"audit": audit_entry.model_dump(), "compliance": "GDPR Article 30"},
    )

    # Optionally persist to database audit table
    if db:
        # TODO: Implement database audit log table
        # from models.audit_log import IngestionAuditLog
        # db_audit = IngestionAuditLog(**audit_entry.model_dump())
        # db.add(db_audit)
        # db.commit()
        pass


# ============================================================================
# Development/Testing Helpers
# ============================================================================


def get_mock_admin_user() -> User:
    """
    Get mock admin user for development/testing.

    WARNING: Only use in development! Remove in production.

    Returns:
        Mock admin user with full permissions
    """
    return User(
        user_id="dev-admin-123",
        email="admin@dev.local",
        username="dev-admin",
        roles=["Admin", "User"],
        permissions=["canManagePipeline", "canViewDashboard"],
        realm="dev",
    )


def get_mock_user() -> User:
    """
    Get mock standard user for development/testing.

    WARNING: Only use in development! Remove in production.

    Returns:
        Mock user without admin permissions
    """
    return User(
        user_id="dev-user-456",
        email="user@dev.local",
        username="dev-user",
        roles=["User"],
        permissions=["canViewDashboard"],
        realm="dev",
    )


async def get_current_user_optional(token: str = Depends(oauth2_scheme)) -> Optional[User]:
    """
    Get current user from JWT token (optional - returns None if not authenticated).

    This is used for endpoints that support both authenticated and unauthenticated access.

    Args:
        token: JWT bearer token from Authorization header (optional)

    Returns:
        User object if authenticated, None otherwise
    """
    if not token:
        return None
    try:
        return await get_current_user(token)
    except HTTPException:
        return None


def verify_user_role(user: dict, allowed_roles: list[str]) -> None:
    """
    Verify that user has one of the allowed roles.
    Raises HTTPException if user doesn't have required role.

    Args:
        user: User dict with 'roles' key
        allowed_roles: List of allowed role names

    Raises:
        HTTPException: 403 if user doesn't have required role
    """
    from fastapi import HTTPException, status

    user_roles = user.get('roles', [])
    if not any(role in allowed_roles for role in user_roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"User role not authorized. Required roles: {allowed_roles}"
        )


# ============================================================================
# Module Exports
# ============================================================================

__all__ = [
    "User",
    "AuditLog",
    "get_current_user",
    "get_current_user_optional",
    "get_current_user_websocket",
    "require_admin_pipeline_permission",
    "require_ingestion_permission",
    "audit_ingestion_access",
    "get_mock_admin_user",
    "get_mock_user",
    "verify_user_role",
]
