"""
Feature 012 - T145a: Session Timeout Manager
FR-AC-011: Session timeout with extend option

Features:
- Default timeout: 20 hours (72000 seconds)
- Session extension: +20 hours on user request
- Auto-logout on timeout
- Token expiry tracking
"""

from typing import Dict, Optional
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# Session Storage (In-Memory)
# ============================================================================


class SessionStore:
    """
    In-memory session storage for tracking active sessions.

    Production Note: Replace with Redis or database-backed storage for
    multi-server deployments.
    """

    def __init__(self):
        # Map: user_id -> session_data
        self._sessions: Dict[str, dict] = {}

    def create_session(self, user_id: str, timeout_seconds: int = 72000) -> dict:
        """
        Create new session for user.

        Args:
            user_id: User UUID
            timeout_seconds: Session timeout in seconds (default: 72000 = 20 hours)

        Returns:
            Session data with expiry timestamp
        """
        now = datetime.utcnow()
        expiry = now + timedelta(seconds=timeout_seconds)

        session_data = {
            "user_id": user_id,
            "created_at": now.isoformat(),
            "last_activity_at": now.isoformat(),
            "expires_at": expiry.isoformat(),
            "timeout_seconds": timeout_seconds,
            "extension_count": 0,
        }

        self._sessions[user_id] = session_data

        logger.info(f"Session created for user {user_id}, expires at {expiry.isoformat()}")

        return session_data

    def get_session(self, user_id: str) -> Optional[dict]:
        """Get session data for user."""
        return self._sessions.get(user_id)

    def update_activity(self, user_id: str) -> Optional[dict]:
        """Update last activity timestamp for session."""
        session = self._sessions.get(user_id)

        if session:
            session["last_activity_at"] = datetime.utcnow().isoformat()
            return session

        return None

    def extend_session(self, user_id: str, extension_seconds: int = 72000) -> Optional[dict]:
        """
        Extend session by adding time to expiry.

        Args:
            user_id: User UUID
            extension_seconds: Time to add (default: 72000 = 20 hours)

        Returns:
            Updated session data with new expiry time
        """
        session = self._sessions.get(user_id)

        if not session:
            return None

        # Parse current expiry
        current_expiry = datetime.fromisoformat(session["expires_at"])

        # Add extension time
        new_expiry = current_expiry + timedelta(seconds=extension_seconds)

        session["expires_at"] = new_expiry.isoformat()
        session["extension_count"] = session.get("extension_count", 0) + 1
        session["last_activity_at"] = datetime.utcnow().isoformat()

        logger.info(f"Session extended for user {user_id}, new expiry: {new_expiry.isoformat()}")

        return session

    def is_session_expired(self, user_id: str) -> bool:
        """Check if session has expired."""
        session = self._sessions.get(user_id)

        if not session:
            return True

        expiry = datetime.fromisoformat(session["expires_at"])
        return datetime.utcnow() > expiry

    def delete_session(self, user_id: str) -> None:
        """Delete session (logout)."""
        if user_id in self._sessions:
            del self._sessions[user_id]
            logger.info(f"Session deleted for user {user_id}")

    def get_time_remaining(self, user_id: str) -> Optional[int]:
        """
        Get seconds remaining until session expiry.

        Returns:
            Seconds remaining, or None if session doesn't exist
        """
        session = self._sessions.get(user_id)

        if not session:
            return None

        expiry = datetime.fromisoformat(session["expires_at"])
        now = datetime.utcnow()

        remaining_seconds = int((expiry - now).total_seconds())

        return max(0, remaining_seconds)  # Return 0 if negative


# Global session store instance
session_store = SessionStore()


# ============================================================================
# Session Management Functions
# ============================================================================


def create_user_session(user_id: str) -> dict:
    """
    Create session for authenticated user.

    Call this after successful login/OIDC authentication.

    Args:
        user_id: User UUID

    Returns:
        Session data with expiry timestamp
    """
    return session_store.create_session(user_id, timeout_seconds=72000)


def extend_user_session(user_id: str) -> Optional[dict]:
    """
    Extend user session by 20 hours.

    Call this when user clicks "Extend Session" button.

    Args:
        user_id: User UUID

    Returns:
        Updated session data, or None if session doesn't exist
    """
    return session_store.extend_session(user_id, extension_seconds=72000)


def check_session_expiry(user_id: str) -> tuple[bool, Optional[int]]:
    """
    Check if session is expired and get time remaining.

    Args:
        user_id: User UUID

    Returns:
        Tuple of (is_expired: bool, time_remaining_seconds: int)
    """
    is_expired = session_store.is_session_expired(user_id)
    time_remaining = session_store.get_time_remaining(user_id)

    return is_expired, time_remaining


def logout_user_session(user_id: str) -> None:
    """
    Delete user session (logout).

    Args:
        user_id: User UUID
    """
    session_store.delete_session(user_id)


# ============================================================================
# FastAPI Dependency for Session Validation
# ============================================================================


def require_valid_session(user_id: str) -> dict:
    """
    Dependency for validating session expiry in FastAPI routes.

    Raises HTTPException if session is expired.

    Usage:
        @router.get("/protected")
        def protected_route(
            current_user=Depends(get_current_user_with_role("viewer")),
            session=Depends(require_valid_session)
        ):
            # Session is valid
            pass
    """
    from fastapi import HTTPException, status

    is_expired, time_remaining = check_session_expiry(user_id)

    if is_expired:
        logout_user_session(user_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired. Please log in again.",
        )

    return session_store.get_session(user_id)


# ============================================================================
# Session Extension API Endpoint (Add to main.py)
# ============================================================================

"""
# Add this to main.py or create sessions.py API router:

from fastapi import APIRouter, Depends
from src.middleware.session_manager import extend_user_session, check_session_expiry
from src.middleware.rbac import get_current_user_with_role

router = APIRouter(prefix="/api/v1/session", tags=["session"])

@router.post("/extend")
async def extend_session(
    current_user=Depends(get_current_user_with_role("viewer"))
):
    '''
    Extend user session by 20 hours (T145a, FR-AC-011).

    Returns:
        Updated session data with new expiry time
    '''
    session_data = extend_user_session(current_user.id)

    if not session_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )

    return {
        "message": "Session extended successfully",
        "expires_at": session_data["expires_at"],
        "extension_count": session_data["extension_count"],
    }

@router.get("/status")
async def get_session_status(
    current_user=Depends(get_current_user_with_role("viewer"))
):
    '''
    Get session status with time remaining.

    Returns:
        Session status with seconds remaining until expiry
    '''
    is_expired, time_remaining = check_session_expiry(current_user.id)

    return {
        "user_id": current_user.id,
        "is_expired": is_expired,
        "time_remaining_seconds": time_remaining,
        "warning_threshold_seconds": 300,  # 5 minutes
        "should_show_warning": time_remaining is not None and time_remaining <= 300,
    }
"""


# ============================================================================
# Module Exports
# ============================================================================

__all__ = [
    "session_store",
    "create_user_session",
    "extend_user_session",
    "check_session_expiry",
    "logout_user_session",
    "require_valid_session",
]
