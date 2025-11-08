"""
Contract tests for Admin Reprocessing Endpoints (Feature 019).

These tests verify the Admin API contracts defined in:
- .specify/specs/019-process-all-7/contracts/admin_reprocess_endpoint.md
- .specify/specs/019-process-all-7/contracts/admin_status_endpoint.md

According to TDD, these tests MUST FAIL initially because the admin endpoints
have not been implemented yet. They will pass after T014 and T015 implementation.
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch
import json

# These imports will fail initially (TDD approach)
# They will succeed after T014-T015: Implement admin endpoints
from src.main import app


@pytest.mark.contract
@pytest.mark.slow
class TestReprocessEndpointContract:
    """Contract tests for POST /api/admin/reprocess-failed-documents."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)

    @pytest.fixture
    def admin_token(self):
        """Mock Keycloak admin token."""
        return "Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.mock_admin_token"

    @pytest.fixture
    def user_token(self):
        """Mock Keycloak user token (non-admin)."""
        return "Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.mock_user_token"

    def test_reprocess_endpoint_returns_202(self, client, admin_token):
        """
        Verify POST /api/admin/reprocess-failed-documents returns 202 with batch info.

        Contract reference: admin_reprocess_endpoint.md lines 22-36
        """
        # Arrange
        headers = {"Authorization": admin_token}

        # Act
        with patch('src.api.routes.admin.verify_admin_role', return_value=True):
            response = client.post(
                "/api/admin/reprocess-failed-documents",
                headers=headers,
                json={}
            )

        # Assert - Status code
        assert response.status_code == 202, \
            "Endpoint must return 202 Accepted"

        # Assert - Response structure
        data = response.json()
        required_fields = ["batch_id", "queued_documents", "estimated_duration_seconds", "status_url"]
        for field in required_fields:
            assert field in data, f"Response must contain '{field}' field"

        # Assert - Field types
        assert isinstance(data["batch_id"], str), \
            "batch_id must be string"
        assert isinstance(data["queued_documents"], int), \
            "queued_documents must be integer"
        assert isinstance(data["estimated_duration_seconds"], int), \
            "estimated_duration_seconds must be integer"
        assert isinstance(data["status_url"], str), \
            "status_url must be string"

        # Assert - Batch ID format (reprocess-YYYYMMDD-HHMMSS)
        assert data["batch_id"].startswith("reprocess-"), \
            "batch_id must start with 'reprocess-'"

        # Assert - Status URL format
        assert data["status_url"].startswith("/api/admin/reprocessing-status/"), \
            "status_url must be valid endpoint path"
        assert data["batch_id"] in data["status_url"], \
            "status_url must contain batch_id"

    def test_reprocess_endpoint_requires_auth(self, client):
        """
        Verify endpoint returns 401 without authentication.

        Contract reference: admin_reprocess_endpoint.md lines 40-46
        """
        # Act
        response = client.post(
            "/api/admin/reprocess-failed-documents",
            json={}
        )

        # Assert
        assert response.status_code == 401, \
            "Endpoint must return 401 without auth token"

        data = response.json()
        assert "detail" in data, \
            "401 response must contain 'detail' field"

    def test_reprocess_endpoint_requires_admin_role(self, client, user_token):
        """
        Verify endpoint returns 403 for non-admin users.

        Contract reference: admin_reprocess_endpoint.md lines 48-54
        """
        # Arrange
        headers = {"Authorization": user_token}

        # Act
        with patch('src.api.routes.admin.verify_admin_role', return_value=False):
            response = client.post(
                "/api/admin/reprocess-failed-documents",
                headers=headers,
                json={}
            )

        # Assert
        assert response.status_code == 403, \
            "Endpoint must return 403 for non-admin users"

        data = response.json()
        assert "detail" in data, \
            "403 response must contain 'detail' field"
        assert "admin" in data["detail"].lower(), \
            "403 detail must mention admin role requirement"

    def test_reprocess_endpoint_rejects_duplicate_batch(self, client, admin_token):
        """
        Verify endpoint returns 409 if batch already in progress.

        Contract reference: admin_reprocess_endpoint.md lines 56-63
        """
        # Arrange
        headers = {"Authorization": admin_token}

        # Act - First request succeeds
        with patch('src.api.routes.admin.verify_admin_role', return_value=True):
            with patch('src.api.routes.admin.check_active_batch', return_value=None):
                response1 = client.post(
                    "/api/admin/reprocess-failed-documents",
                    headers=headers,
                    json={}
                )
        assert response1.status_code == 202, "First request should succeed"

        # Act - Second request while first is in progress
        with patch('src.api.routes.admin.verify_admin_role', return_value=True):
            with patch('src.api.routes.admin.check_active_batch', return_value="reprocess-20251020-140000"):
                response2 = client.post(
                    "/api/admin/reprocess-failed-documents",
                    headers=headers,
                    json={}
                )

        # Assert
        assert response2.status_code == 409, \
            "Endpoint must return 409 for duplicate batch"

        data = response2.json()
        assert "detail" in data, \
            "409 response must contain 'detail' field"
        assert "active_batch_id" in data, \
            "409 response must contain 'active_batch_id' field"


@pytest.mark.contract
@pytest.mark.slow
class TestStatusEndpointContract:
    """Contract tests for GET /api/admin/reprocessing-status/{batch_id}."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)

    @pytest.fixture
    def admin_token(self):
        """Mock Keycloak admin token."""
        return "Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.mock_admin_token"

    def test_status_endpoint_returns_json(self, client, admin_token):
        """
        Verify GET /api/admin/reprocessing-status/{batch_id} returns JSON status.

        Contract reference: admin_status_endpoint.md lines 27-68
        """
        # Arrange
        batch_id = "reprocess-20251020-143022"
        headers = {"Authorization": admin_token}

        # Act
        with patch('src.api.routes.admin.verify_admin_role', return_value=True):
            with patch('src.api.routes.admin.get_batch_status', return_value={
                "batch_id": batch_id,
                "status": "in_progress",
                "documents_queued": 6234,
                "documents_processing": 45,
                "documents_completed": 1684,
                "documents_failed": 0,
                "success_rate": 100.0,
                "estimated_time_remaining_seconds": 12468
            }):
                response = client.get(
                    f"/api/admin/reprocessing-status/{batch_id}",
                    headers=headers
                )

        # Assert - Status code
        assert response.status_code == 200, \
            "Status endpoint must return 200 OK"

        # Assert - Response structure
        data = response.json()
        required_fields = [
            "batch_id",
            "status",
            "documents_queued",
            "documents_processing",
            "documents_completed",
            "documents_failed",
            "success_rate",
            "estimated_time_remaining_seconds"
        ]
        for field in required_fields:
            assert field in data, f"Response must contain '{field}' field"

        # Assert - Field types
        assert isinstance(data["batch_id"], str)
        assert isinstance(data["status"], str)
        assert isinstance(data["documents_queued"], int)
        assert isinstance(data["documents_processing"], int)
        assert isinstance(data["documents_completed"], int)
        assert isinstance(data["documents_failed"], int)
        assert isinstance(data["success_rate"], float)
        assert isinstance(data["estimated_time_remaining_seconds"], int)

        # Assert - Status enum
        valid_statuses = ["queued", "in_progress", "completed", "failed"]
        assert data["status"] in valid_statuses, \
            f"status must be one of {valid_statuses}"

    def test_status_endpoint_sse_streams(self, client, admin_token):
        """
        Verify GET /api/admin/reprocessing-status/{batch_id}/stream returns SSE.

        Contract reference: admin_status_endpoint.md lines 74-113
        """
        # Arrange
        batch_id = "reprocess-20251020-143022"
        headers = {"Authorization": admin_token, "Accept": "text/event-stream"}

        # Act
        with patch('src.api.routes.admin.verify_admin_role', return_value=True):
            response = client.get(
                f"/api/admin/reprocessing-status/{batch_id}/stream",
                headers=headers
            )

        # Assert - Status code
        assert response.status_code == 200, \
            "SSE endpoint must return 200 OK"

        # Assert - Content type
        assert response.headers["content-type"] == "text/event-stream", \
            "SSE endpoint must return text/event-stream content type"

    def test_status_endpoint_requires_auth(self, client):
        """
        Verify status endpoint returns 401 without authentication.

        Contract reference: admin_status_endpoint.md lines 115-126
        """
        # Act
        response = client.get(
            "/api/admin/reprocessing-status/reprocess-20251020-143022"
        )

        # Assert
        assert response.status_code == 401, \
            "Status endpoint must return 401 without auth"

    def test_status_endpoint_handles_missing_batch(self, client, admin_token):
        """
        Verify status endpoint returns 404 for non-existent batch.

        Contract reference: admin_status_endpoint.md lines 128-139
        """
        # Arrange
        batch_id = "reprocess-99999999-999999"
        headers = {"Authorization": admin_token}

        # Act
        with patch('src.api.routes.admin.verify_admin_role', return_value=True):
            with patch('src.api.routes.admin.get_batch_status', return_value=None):
                response = client.get(
                    f"/api/admin/reprocessing-status/{batch_id}",
                    headers=headers
                )

        # Assert
        assert response.status_code == 404, \
            "Status endpoint must return 404 for missing batch"

        data = response.json()
        assert "detail" in data, \
            "404 response must contain 'detail' field"
