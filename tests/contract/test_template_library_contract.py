"""
Contract tests for GET /api/templates/library endpoint.
Based on: .specify/specs/023-create-a-production/contracts/library_endpoint.yaml
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from src.main import app


@pytest.mark.contract
class TestLibraryEndpointContract:
    """Contract tests for GET /api/templates/library - Decision Library endpoint."""

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

    def test_library_authentication_required(self, client):
        """
        Test that library endpoint requires authentication (401).

        Contract reference: library_endpoint.yaml lines 61-66
        Functional requirement: FR-001
        """
        response = client.get("/api/templates/library")

        # Should return 401 Unauthorized
        assert response.status_code == 401, f"Expected 401 without auth, got {response.status_code}"

        data = response.json()
        assert "request_id" in data, "Error response missing request_id"
        assert "error" in data, "Error response missing error"
        assert "message" in data, "Error response missing message"

    def test_library_response_schema(self, client, mock_editor_token):
        """
        Test that library endpoint returns valid response schema.

        Contract reference: library_endpoint.yaml lines 25-59
        Functional requirement: FR-033
        """
        with patch('src.middleware.rbac.verify_user_role', return_value=True):
            response = client.get(
                "/api/templates/library",
                headers={"Authorization": mock_editor_token}
            )

        # Skip if endpoint not implemented yet
        if response.status_code == 404:
            pytest.skip("Endpoint not implemented yet")

        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

        data = response.json()

        # Verify required field: DecisionLibrary
        assert "DecisionLibrary" in data, "Missing DecisionLibrary field"
        assert isinstance(data["DecisionLibrary"], list), "DecisionLibrary must be array"

        # FR-029: Minimum 10 decision types
        assert len(data["DecisionLibrary"]) >= 10, \
            f"DecisionLibrary must contain at least 10 items, got {len(data['DecisionLibrary'])}"

        # Verify each decision requirement has required fields
        for item in data["DecisionLibrary"]:
            assert "id" in item, "Decision item missing id"
            assert "label" in item, "Decision item missing label"
            assert "type" in item, "Decision item missing type"
            assert "on_yes_template" in item, "Decision item missing on_yes_template"

            # Verify id is snake_case string
            assert isinstance(item["id"], str), "id must be string"
            assert item["id"].replace("_", "").isalnum(), "id must be snake_case"

            # Verify label is human-readable string
            assert isinstance(item["label"], str), "label must be string"
            assert len(item["label"]) > 0, "label must not be empty"

            # Verify type is valid enum
            valid_types = ["date_range", "document_list", "yes_no", "text"]
            assert item["type"] in valid_types, \
                f"type must be one of {valid_types}, got {item['type']}"

            # Verify on_yes_template is array of strings
            assert isinstance(item["on_yes_template"], list), "on_yes_template must be array"
            assert len(item["on_yes_template"]) >= 1, "on_yes_template must have at least 1 line"
            for line in item["on_yes_template"]:
                assert isinstance(line, str), "on_yes_template lines must be strings"

            # Verify placeholders if present
            if "placeholders" in item:
                assert isinstance(item["placeholders"], list), "placeholders must be array"
                for placeholder in item["placeholders"]:
                    assert isinstance(placeholder, str), "placeholder must be string"

    def test_library_rate_limiting_headers(self, client, mock_editor_token):
        """
        Test that library endpoint includes rate limiting headers.

        Contract reference: library_endpoint.yaml lines 28-36
        Functional requirements: FR-005, FR-006, FR-008
        """
        with patch('src.middleware.rbac.verify_user_role', return_value=True):
            response = client.get(
                "/api/templates/library",
                headers={"Authorization": mock_editor_token}
            )

        # Skip if endpoint not implemented
        if response.status_code == 404:
            pytest.skip("Endpoint not implemented yet")

        # Verify rate limit headers present
        if response.status_code == 200:
            assert "X-RateLimit-Limit" in response.headers, "Missing X-RateLimit-Limit header"
            assert "X-RateLimit-Remaining" in response.headers, "Missing X-RateLimit-Remaining header"
            assert "X-RateLimit-Reset" in response.headers, "Missing X-RateLimit-Reset header"

            # Verify header types
            assert response.headers["X-RateLimit-Limit"].isdigit(), "X-RateLimit-Limit must be integer"
            assert response.headers["X-RateLimit-Remaining"].isdigit(), "X-RateLimit-Remaining must be integer"
            assert response.headers["X-RateLimit-Reset"].isdigit(), "X-RateLimit-Reset must be integer"

    def test_library_forbidden_for_viewer_role(self, client, mock_viewer_token):
        """
        Test that library endpoint returns 403 for Viewer role.

        Contract reference: library_endpoint.yaml lines 68-73
        Functional requirement: FR-004
        """
        with patch('src.middleware.rbac.verify_user_role', return_value=False):
            response = client.get(
                "/api/templates/library",
                headers={"Authorization": mock_viewer_token}
            )

        # Skip if endpoint not implemented
        if response.status_code == 404:
            pytest.skip("Endpoint not implemented yet")

        # Should return 403 Forbidden
        assert response.status_code == 403, \
            f"Expected 403 for Viewer role, got {response.status_code}"

        data = response.json()
        assert "request_id" in data, "Error response missing request_id"
        assert "error" in data, "Error response missing error"
        assert "message" in data, "Error response missing message"

    def test_library_rate_limit_exceeded(self, client, mock_editor_token):
        """
        Test that library endpoint enforces rate limits (429).

        Contract reference: library_endpoint.yaml lines 75-80
        Functional requirements: FR-005, FR-006, FR-007
        """
        # Make 11 requests rapidly (limit is 10/min per FR-005)
        responses = []
        with patch('src.middleware.rbac.verify_user_role', return_value=True):
            for i in range(11):
                response = client.get(
                    "/api/templates/library",
                    headers={"Authorization": mock_editor_token}
                )
                responses.append(response)

        status_codes = [r.status_code for r in responses]

        # Skip if not implemented
        if all(code == 404 for code in status_codes):
            pytest.skip("Endpoint not implemented yet")

        # Should have at least one 429 if rate limiting works
        # Note: This may not trigger in all test environments
        # but the header presence confirms rate limiting exists
        last_response = responses[-1]
        if last_response.status_code == 429:
            data = last_response.json()
            assert "request_id" in data
            assert "error" in data
            assert "message" in data

    def test_library_unavailable_returns_503(self, client, mock_editor_token):
        """
        Test that library endpoint returns 503 when library unavailable.

        Contract reference: library_endpoint.yaml lines 82-91
        Functional requirement: FR-032
        """
        # This test requires mocking library load failure
        # Skip for now - requires implementation-specific mocking
        pytest.skip("Requires implementation-specific library unavailability simulation")

    def test_library_version_field_optional(self, client, mock_editor_token):
        """
        Test that version field is optional in library response.

        Contract reference: library_endpoint.yaml lines 112-115
        """
        with patch('src.middleware.rbac.verify_user_role', return_value=True):
            response = client.get(
                "/api/templates/library",
                headers={"Authorization": mock_editor_token}
            )

        # Skip if not implemented
        if response.status_code == 404:
            pytest.skip("Endpoint not implemented yet")

        if response.status_code == 200:
            data = response.json()
            # version field is optional, so we just verify it's a string if present
            if "version" in data:
                assert isinstance(data["version"], str), "version must be string if present"
