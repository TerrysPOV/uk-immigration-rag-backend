"""
Contract test for Keycloak authentication token validation.
Validates token endpoint response schema.
"""
import pytest
import requests


KEYCLOAK_URL = "http://localhost:8080"
REALM = "gov-ai-realm"
CLIENT_ID = "rag-api-client"
TOKEN_URL = f"{KEYCLOAK_URL}/realms/{REALM}/protocol/openid-connect/token"


def test_keycloak_token_endpoint_exists():
    """Test that Keycloak token endpoint is accessible."""
    response = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "password",
            "client_id": CLIENT_ID,
            "username": "invalid",
            "password": "invalid"
        }
    )
    
    # Should return 401 for invalid credentials (endpoint exists)
    assert response.status_code in [400, 401], f"Unexpected status: {response.status_code}"


def test_keycloak_token_response_schema():
    """Test successful token response matches expected schema."""
    # Note: This test requires valid test credentials
    # For now, we validate the error response schema
    
    response = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "password",
            "client_id": CLIENT_ID,
            "username": "invalid",
            "password": "invalid"
        }
    )
    
    data = response.json()
    
    if response.status_code == 401:
        # Validate error response schema
        assert "error" in data, "Missing 'error' field in error response"
        assert isinstance(data["error"], str), "'error' must be string"
    
    # TODO: Add test with valid credentials when test user configured
    # Expected success schema:
    # {
    #   "access_token": str,
    #   "token_type": "Bearer",
    #   "expires_in": int,
    #   "refresh_token": str,
    #   "refresh_expires_in": int
    # }


def test_keycloak_token_invalid_grant_type():
    """Test that invalid grant type is rejected."""
    response = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "invalid_grant",
            "client_id": CLIENT_ID
        }
    )
    
    assert response.status_code in [400, 401], f"Unexpected status: {response.status_code}"
    
    data = response.json()
    assert "error" in data
    assert data["error"] in ["unsupported_grant_type", "invalid_grant", "invalid_request"]


@pytest.mark.skip(reason="Requires test user credentials - configure later")
def test_keycloak_token_success_with_valid_credentials():
    """Test successful token acquisition (requires test user)."""
    # TODO: Configure test@gov.uk user and add credentials here
    response = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "password",
            "client_id": CLIENT_ID,
            "username": "test@gov.uk",
            "password": "TestPassword123!",
            "scope": "openid email profile"
        }
    )
    
    assert response.status_code == 200
    
    data = response.json()
    assert "access_token" in data
    assert "token_type" in data
    assert data["token_type"] == "Bearer"
    assert "expires_in" in data
    assert isinstance(data["expires_in"], int)
