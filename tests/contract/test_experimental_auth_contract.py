"""
Contract test for Google OAuth role enforcement on experimental endpoint.
Tests that Editor and Admin roles can access, Viewer cannot.

CRITICAL: This test is expected to FAIL until T012 + auth integration is implemented.
This is part of TDD workflow - write failing tests first.
"""

import pytest
from fastapi.testclient import TestClient


# These tests will fail until implementation exists
pytestmark = pytest.mark.xfail(
    reason="Experimental endpoint auth not yet implemented (T012 pending)",
    strict=True
)


@pytest.fixture
def api_client():
    """Create test client - will fail until main app includes experimental endpoint."""
    try:
        from backend_source.main import app
        return TestClient(app)
    except ImportError:
        pytest.skip("Backend app not available")


@pytest.fixture
def editor_token():
    """Mock Google OAuth token for Editor role."""
    # In reality, this would be a JWT from Google OAuth
    # For contract testing, we mock the role extraction
    return "Bearer mock_google_oauth_editor_jwt"


@pytest.fixture
def admin_token():
    """Mock Google OAuth token for Admin role."""
    return "Bearer mock_google_oauth_admin_jwt"


@pytest.fixture
def viewer_token():
    """Mock Google OAuth token for Viewer role."""
    return "Bearer mock_google_oauth_viewer_jwt"


def test_editor_role_can_access_endpoint(api_client, editor_token):
    """Assert Editor role can access /api/v1/templates/experimental/generate."""
    response = api_client.post(
        "/api/v1/templates/experimental/generate",
        headers={"Authorization": editor_token},
        data={"custom_system_prompt": "Test prompt for editor"}
    )

    # Should NOT return 403 (forbidden)
    assert response.status_code != 403, "Editor should have access"
    # May return 200 (success) or other errors, but not permission denied
    assert response.status_code in [200, 400, 500], \
        f"Expected success/validation/error, got {response.status_code}"


def test_admin_role_can_access_endpoint(api_client, admin_token):
    """Assert Admin role can access /api/v1/templates/experimental/generate."""
    response = api_client.post(
        "/api/v1/templates/experimental/generate",
        headers={"Authorization": admin_token},
        data={"custom_system_prompt": "Test prompt for admin"}
    )

    # Should NOT return 403 (forbidden)
    assert response.status_code != 403, "Admin should have access"
    assert response.status_code in [200, 400, 500], \
        f"Expected success/validation/error, got {response.status_code}"


def test_viewer_role_returns_403(api_client, viewer_token):
    """Assert Viewer role returns 403 Forbidden."""
    response = api_client.post(
        "/api/v1/templates/experimental/generate",
        headers={"Authorization": viewer_token},
        data={"custom_system_prompt": "Test prompt for viewer"}
    )

    assert response.status_code == 403, "Viewer should be denied access"
    data = response.json()
    assert "error" in data
    assert data["error"] == "insufficient_permissions"
    assert "Editor" in data["message"] or "Admin" in data["message"]
    assert "Viewer" not in data.get("allowed_roles", [])


def test_unauthenticated_request_returns_401(api_client):
    """Assert unauthenticated request returns 401."""
    response = api_client.post(
        "/api/v1/templates/experimental/generate",
        data={"custom_system_prompt": "Test prompt"}
        # No Authorization header
    )

    assert response.status_code == 401, "Should require authentication"
    data = response.json()
    assert "error" in data
    assert data["error"] in ["invalid_token", "missing_token", "unauthenticated"]


def test_invalid_token_returns_401(api_client):
    """Assert invalid Google OAuth token returns 401."""
    response = api_client.post(
        "/api/v1/templates/experimental/generate",
        headers={"Authorization": "Bearer invalid_malformed_token"},
        data={"custom_system_prompt": "Test prompt"}
    )

    assert response.status_code == 401, "Invalid token should be rejected"
    data = response.json()
    assert "error" in data
    assert "token" in data["message"].lower() or "invalid" in data["message"].lower()


def test_expired_token_returns_401(api_client):
    """Assert expired Google OAuth token returns 401."""
    # This would require a real expired JWT in production
    # For contract test, we use a mock expired token
    expired_token = "Bearer mock_google_oauth_expired_jwt"

    response = api_client.post(
        "/api/v1/templates/experimental/generate",
        headers={"Authorization": expired_token},
        data={"custom_system_prompt": "Test prompt"}
    )

    assert response.status_code == 401, "Expired token should be rejected"
    data = response.json()
    assert "error" in data
    assert "expired" in data["message"].lower() or "invalid" in data["message"].lower()


def test_wrong_oauth_provider_returns_401(api_client):
    """Assert token from wrong OAuth provider is rejected."""
    # Token from Microsoft/GitHub/etc instead of Google
    wrong_provider_token = "Bearer mock_microsoft_oauth_jwt"

    response = api_client.post(
        "/api/v1/templates/experimental/generate",
        headers={"Authorization": wrong_provider_token},
        data={"custom_system_prompt": "Test prompt"}
    )

    assert response.status_code == 401, "Non-Google token should be rejected"
    data = response.json()
    assert "error" in data
