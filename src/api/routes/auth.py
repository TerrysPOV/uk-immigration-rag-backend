"""
Authentication endpoints - DEPRECATED

Google OAuth 2.0 authentication is handled client-side with Google Sign-In button.
The frontend sends Google ID tokens in Authorization header, verified by backend.

This token endpoint is no longer used. Google OAuth flow:
1. Frontend: User clicks "Sign in with Google" button
2. Frontend: Google OAuth popup, user authenticates
3. Frontend: Receives Google ID token
4. Frontend: Sends ID token in Authorization: Bearer <token> header
5. Backend: Verifies token with Google's public JWKS (src.middleware.rbac)
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

router = APIRouter(prefix='/auth', tags=['authentication'])

class InfoResponse(BaseModel):
    message: str
    auth_method: str
    instructions: str

@router.get('/info', response_model=InfoResponse)
async def auth_info():
    """
    Get authentication method information.

    This endpoint replaced the old /token endpoint.
    Google OAuth is now handled entirely client-side.
    """
    return InfoResponse(
        message="Authentication uses Google OAuth 2.0",
        auth_method="Google OAuth 2.0 (client-side flow)",
        instructions="Frontend obtains Google ID token, backend verifies it with Google's JWKS"
    )

@router.post('/token')
async def deprecated_token_endpoint():
    """
    DEPRECATED: Token endpoint no longer supported.

    Use Google OAuth 2.0 client-side flow instead.
    """
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail={
            "error": "endpoint_deprecated",
            "message": "Password grant flow deprecated. Use Google OAuth 2.0.",
            "auth_method": "Google Sign-In button (client-side)",
            "documentation": "https://developers.google.com/identity/gsi/web/guides/overview"
        }
    )
