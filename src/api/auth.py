"""
DEPRECATED: This module is deprecated and kept only for backward compatibility.

Use src.middleware.rbac for Google OAuth 2.0 authentication instead.

All authentication functionality has been migrated to:
- src.middleware.rbac.get_current_user()
- src.middleware.rbac.get_current_user_optional()
- src.middleware.rbac.verify_jwt_token()
"""

# Re-export from rbac for backward compatibility
from src.middleware.rbac import (
    get_current_user,
    get_current_user_optional,
    verify_jwt_token,
    extract_user_from_token,
    User
)

__all__ = [
    'get_current_user',
    'get_current_user_optional',
    'verify_jwt_token',
    'extract_user_from_token',
    'User'
]
