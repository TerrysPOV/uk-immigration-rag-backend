"""
Authentication contract tests for Template Workflow API.

Tests that all endpoints enforce proper authentication and authorization:
- FR-001: Only Editor/Admin roles can access protected endpoints
- FR-002: Google OAuth tokens required
- FR-003: 401 for missing/invalid tokens
- FR-004: 403 for insufficient roles
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from src.main import app


@pytest.mark.contract
class TestTemplateAuthContract:
    """Authentication and authorization contract tests."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)

    @pytest.fixture
    def mock_editor_token(self):
        """Mock Keycloak Editor token."""
        return "Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.mock_editor_token"

    @pytest.fixture
    def mock_viewer_token(self):
        """Mock Keycloak Viewer token (insufficient permissions)."""
        return "Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.mock_viewer_token"

    @pytest.fixture
    def invalid_token(self):
        """Invalid/expired token."""
        return "Bearer invalid_token_xyz"

    # ==================== 401 Tests: No Token ====================

    def test_analyze_requires_auth(self, client):
        """
        Test POST /api/templates/analyze returns 401 without token.

        Functional requirement: FR-003
        """
        response = client.post(
            "/api/templates/analyze",
            json={"document_url": "https://www.gov.uk/guidance/test"}
        )

        assert response.status_code == 401, \
            f"analyze endpoint must return 401 without auth, got {response.status_code}"

        data = response.json()
        assert "request_id" in data
        assert "error" in data
        assert "message" in data

    def test_render_requires_auth(self, client):
        """
        Test POST /api/templates/render returns 401 without token.

        Functional requirement: FR-003
        """
        response = client.post(
            "/api/templates/render",
            json={
                "requirements": [
                    {"decision_id": "send_specific_documents", "values": {}}
                ]
            }
        )

        assert response.status_code == 401, \
            f"render endpoint must return 401 without auth, got {response.status_code}"

        data = response.json()
        assert "request_id" in data
        assert "error" in data
        assert "message" in data

    def test_library_requires_auth(self, client):
        """
        Test GET /api/templates/library returns 401 without token.

        Functional requirement: FR-003
        """
        response = client.get("/api/templates/library")

        assert response.status_code == 401, \
            f"library endpoint must return 401 without auth, got {response.status_code}"

        data = response.json()
        assert "request_id" in data
        assert "error" in data
        assert "message" in data

    def test_health_does_not_require_auth(self, client):
        """
        Test GET /api/templates/health works without authentication.

        Functional requirement: FR-045 (public endpoint)
        """
        response = client.get("/api/templates/health")

        # Skip if endpoint not implemented yet
        if response.status_code == 404:
            pytest.skip("Endpoint not implemented yet")

        # Should NOT return 401
        assert response.status_code in [200, 503], \
            f"health endpoint should not require auth, got {response.status_code}"

    # ==================== 403 Tests: Insufficient Role ====================

    def test_analyze_forbidden_for_viewer(self, client, mock_viewer_token):
        """
        Test POST /api/templates/analyze returns 403 for Viewer role.

        Functional requirement: FR-004 (Editor/Admin only)
        """
        with patch('src.middleware.rbac.verify_user_role', return_value=False):
            response = client.post(
                "/api/templates/analyze",
                headers={"Authorization": mock_viewer_token},
                json={"document_url": "https://www.gov.uk/guidance/test"}
            )

        # Skip if endpoint not implemented yet
        if response.status_code == 404:
            pytest.skip("Endpoint not implemented yet")

        assert response.status_code == 403, \
            f"analyze must return 403 for Viewer role, got {response.status_code}"

        data = response.json()
        assert "request_id" in data
        assert "error" in data
        assert "message" in data
        assert "editor" in data["message"].lower() or "admin" in data["message"].lower() or "permission" in data["message"].lower()

    def test_render_forbidden_for_viewer(self, client, mock_viewer_token):
        """
        Test POST /api/templates/render returns 403 for Viewer role.

        Functional requirement: FR-004 (Editor/Admin only)
        """
        with patch('src.middleware.rbac.verify_user_role', return_value=False):
            response = client.post(
                "/api/templates/render",
                headers={"Authorization": mock_viewer_token},
                json={
                    "requirements": [
                        {"decision_id": "send_specific_documents", "values": {}}
                    ]
                }
            )

        # Skip if endpoint not implemented yet
        if response.status_code == 404:
            pytest.skip("Endpoint not implemented yet")

        assert response.status_code == 403, \
            f"render must return 403 for Viewer role, got {response.status_code}"

        data = response.json()
        assert "request_id" in data
        assert "error" in data
        assert "message" in data

    def test_library_forbidden_for_viewer(self, client, mock_viewer_token):
        """
        Test GET /api/templates/library returns 403 for Viewer role.

        Functional requirement: FR-004 (Editor/Admin only)
        """
        with patch('src.middleware.rbac.verify_user_role', return_value=False):
            response = client.get(
                "/api/templates/library",
                headers={"Authorization": mock_viewer_token}
            )

        # Skip if endpoint not implemented yet
        if response.status_code == 404:
            pytest.skip("Endpoint not implemented yet")

        assert response.status_code == 403, \
            f"library must return 403 for Viewer role, got {response.status_code}"

        data = response.json()
        assert "request_id" in data
        assert "error" in data
        assert "message" in data

    # ==================== 200 Tests: Valid Editor/Admin ====================

    def test_analyze_accepts_editor_token(self, client, mock_editor_token):
        """
        Test POST /api/templates/analyze accepts Editor role.

        Functional requirement: FR-001 (Editor/Admin can access)
        """
        with patch('src.middleware.rbac.verify_user_role', return_value=True):
            response = client.post(
                "/api/templates/analyze",
                headers={"Authorization": mock_editor_token},
                json={"document_url": "https://www.gov.uk/guidance/test"}
            )

        # Skip if endpoint not implemented yet
        if response.status_code == 404:
            pytest.skip("Endpoint not implemented yet")

        # Should NOT return 401 or 403
        assert response.status_code not in [401, 403], \
            f"analyze should accept Editor token, got {response.status_code}"

    def test_render_accepts_editor_token(self, client, mock_editor_token):
        """
        Test POST /api/templates/render accepts Editor role.

        Functional requirement: FR-001 (Editor/Admin can access)
        """
        with patch('src.middleware.rbac.verify_user_role', return_value=True):
            response = client.post(
                "/api/templates/render",
                headers={"Authorization": mock_editor_token},
                json={
                    "requirements": [
                        {"decision_id": "send_specific_documents", "values": {}}
                    ]
                }
            )

        # Skip if endpoint not implemented yet
        if response.status_code == 404:
            pytest.skip("Endpoint not implemented yet")

        # Should NOT return 401 or 403
        assert response.status_code not in [401, 403], \
            f"render should accept Editor token, got {response.status_code}"

    def test_library_accepts_editor_token(self, client, mock_editor_token):
        """
        Test GET /api/templates/library accepts Editor role.

        Functional requirement: FR-001 (Editor/Admin can access)
        """
        with patch('src.middleware.rbac.verify_user_role', return_value=True):
            response = client.get(
                "/api/templates/library",
                headers={"Authorization": mock_editor_token}
            )

        # Skip if endpoint not implemented yet
        if response.status_code == 404:
            pytest.skip("Endpoint not implemented yet")

        # Should NOT return 401 or 403
        assert response.status_code not in [401, 403], \
            f"library should accept Editor token, got {response.status_code}"

    # ==================== Error Response Schema Tests ====================

    def test_auth_error_response_schema(self, client):
        """
        Test that authentication errors return proper error schema.

        All errors must include: request_id, error, message
        """
        # Test 401 error schema
        response = client.post(
            "/api/templates/analyze",
            json={"document_url": "https://www.gov.uk/guidance/test"}
        )

        assert response.status_code == 401
        data = response.json()

        # Verify error response structure
        required_fields = ["request_id", "error", "message"]
        for field in required_fields:
            assert field in data, f"Error response missing {field}"

        # Verify types
        assert isinstance(data["request_id"], str), "request_id must be string"
        assert isinstance(data["error"], str), "error must be string"
        assert isinstance(data["message"], str), "message must be string"
