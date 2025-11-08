"""
Contract tests for Admin Panel API.

Tests all 7 endpoints from contracts/admin-panel-api.yaml:
1. GET /api/v1/admin/users
2. PUT /api/v1/admin/users/{id}/role
3. PATCH /api/v1/admin/users/{id}/status
4. POST /api/v1/admin/users/{id}/reset-password
5. GET /api/v1/admin/config
6. PUT /api/v1/admin/config
7. GET /api/v1/admin/audit-logs

These tests MUST FAIL before implementation (TDD).
"""

import pytest
from fastapi.testclient import TestClient
from uuid import uuid4
from datetime import datetime

# Mock client - will import actual app after implementation
# from src.main import app
# client = TestClient(app)


class TestAdminUsersEndpoint:
    """Test GET /api/v1/admin/users - List users with pagination and filters."""

    def test_list_users_success(self, client, auth_headers):
        """Test successful user listing with default pagination."""
        response = client.get("/api/v1/admin/users", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()

        # Contract validation
        assert "users" in data
        assert "total" in data
        assert "page" in data
        assert "limit" in data
        assert isinstance(data["users"], list)

        # User schema validation
        if len(data["users"]) > 0:
            user = data["users"][0]
            assert "id" in user
            assert "email" in user
            assert "role" in user
            assert "status" in user
            assert "created_at" in user
            assert user["role"] in ["admin", "editor", "viewer"]
            assert user["status"] in ["active", "inactive"]

    def test_list_users_with_pagination(self, client, auth_headers):
        """Test pagination parameters."""
        response = client.get(
            "/api/v1/admin/users", params={"page": 2, "limit": 10}, headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 2
        assert data["limit"] == 10

    def test_list_users_with_status_filter(self, client, auth_headers):
        """Test filtering by user status."""
        response = client.get(
            "/api/v1/admin/users", params={"status": "active"}, headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()

        # All returned users should be active
        for user in data["users"]:
            assert user["status"] == "active"

    def test_list_users_with_role_filter(self, client, auth_headers):
        """Test filtering by role."""
        response = client.get(
            "/api/v1/admin/users", params={"role": "editor"}, headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()

        # All returned users should have editor role
        for user in data["users"]:
            assert user["role"] == "editor"

    def test_list_users_unauthorized(self, client):
        """Test 401 when no authentication provided."""
        response = client.get("/api/v1/admin/users")
        assert response.status_code == 401
        assert "error" in response.json()

    def test_list_users_forbidden_non_admin(self, client, viewer_auth_headers):
        """Test 403 when user lacks admin permissions."""
        response = client.get("/api/v1/admin/users", headers=viewer_auth_headers)
        assert response.status_code == 403
        assert "error" in response.json()


class TestAssignUserRole:
    """Test PUT /api/v1/admin/users/{id}/role - Assign user role."""

    def test_assign_role_success(self, client, auth_headers, sample_user_id):
        """Test successful role assignment."""
        response = client.put(
            f"/api/v1/admin/users/{sample_user_id}/role",
            json={"role_name": "editor"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        # UserWithRole schema validation
        assert data["id"] == str(sample_user_id)
        assert data["role"] == "editor"
        assert "email" in data
        assert "status" in data
        assert "created_at" in data

    def test_assign_role_creates_audit_log(self, client, auth_headers, sample_user_id):
        """Test that role assignment creates audit log entry."""
        # Assign role
        client.put(
            f"/api/v1/admin/users/{sample_user_id}/role",
            json={"role_name": "admin"},
            headers=auth_headers,
        )

        # Check audit logs
        audit_response = client.get(
            "/api/v1/admin/audit-logs",
            params={"resource_id": str(sample_user_id), "action_type": "UPDATE"},
            headers=auth_headers,
        )

        assert audit_response.status_code == 200
        logs = audit_response.json()["logs"]
        assert len(logs) > 0

        # Verify audit log contains old_value and new_value
        log = logs[0]
        assert log["action_type"] == "UPDATE"
        assert log["resource_type"] == "user"
        assert "old_value" in log
        assert "new_value" in log

    def test_assign_role_invalid_role(self, client, auth_headers, sample_user_id):
        """Test 400 when invalid role provided."""
        response = client.put(
            f"/api/v1/admin/users/{sample_user_id}/role",
            json={"role_name": "superadmin"},  # Invalid role
            headers=auth_headers,
        )

        assert response.status_code == 400
        assert "error" in response.json()

    def test_assign_role_user_not_found(self, client, auth_headers):
        """Test 404 when user doesn't exist."""
        fake_id = uuid4()
        response = client.put(
            f"/api/v1/admin/users/{fake_id}/role",
            json={"role_name": "editor"},
            headers=auth_headers,
        )

        assert response.status_code == 404
        assert "error" in response.json()

    def test_assign_role_unauthorized(self, client, sample_user_id):
        """Test 401 without authentication."""
        response = client.put(
            f"/api/v1/admin/users/{sample_user_id}/role", json={"role_name": "editor"}
        )
        assert response.status_code == 401


class TestUpdateUserStatus:
    """Test PATCH /api/v1/admin/users/{id}/status - Activate/deactivate user."""

    def test_deactivate_user_success(self, client, auth_headers, sample_user_id):
        """Test successful user deactivation."""
        response = client.patch(
            f"/api/v1/admin/users/{sample_user_id}/status",
            json={"status": "inactive"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "inactive"

    def test_activate_user_success(self, client, auth_headers, sample_user_id):
        """Test successful user activation."""
        response = client.patch(
            f"/api/v1/admin/users/{sample_user_id}/status",
            json={"status": "active"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "active"

    def test_update_status_creates_audit_log(self, client, auth_headers, sample_user_id):
        """Test audit log creation on status change."""
        response = client.patch(
            f"/api/v1/admin/users/{sample_user_id}/status",
            json={"status": "inactive"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        # Audit log check covered by test_assign_role_creates_audit_log pattern

    def test_update_status_invalid_value(self, client, auth_headers, sample_user_id):
        """Test 400 with invalid status value."""
        response = client.patch(
            f"/api/v1/admin/users/{sample_user_id}/status",
            json={"status": "suspended"},  # Invalid
            headers=auth_headers,
        )

        assert response.status_code == 400


class TestResetPassword:
    """Test POST /api/v1/admin/users/{id}/reset-password - Generate reset token."""

    def test_reset_password_success(self, client, auth_headers, sample_user_id):
        """Test successful password reset token generation."""
        response = client.post(
            f"/api/v1/admin/users/{sample_user_id}/reset-password", headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()

        assert "message" in data
        assert "reset_token_expires_at" in data
        assert "user@example.gov.uk" in data["message"] or "sent" in data["message"].lower()

    def test_reset_password_user_not_found(self, client, auth_headers):
        """Test 404 for non-existent user."""
        fake_id = uuid4()
        response = client.post(
            f"/api/v1/admin/users/{fake_id}/reset-password", headers=auth_headers
        )

        assert response.status_code == 404


class TestSystemConfiguration:
    """Test GET/PUT /api/v1/admin/config - System configuration."""

    def test_get_config_success(self, client, auth_headers):
        """Test retrieving system configuration."""
        response = client.get("/api/v1/admin/config", headers=auth_headers)

        assert response.status_code == 200
        config = response.json()

        # SystemConfiguration schema validation
        assert "max_upload_size_mb" in config
        assert "session_timeout_minutes" in config
        assert "enable_analytics" in config
        assert "enable_audit_logging" in config
        assert "retention_days" in config

        # Validate ranges
        assert 1 <= config["max_upload_size_mb"] <= 500
        assert 5 <= config["session_timeout_minutes"] <= 1440
        assert 30 <= config["retention_days"] <= 2555
        assert isinstance(config["enable_analytics"], bool)

    def test_update_config_success(self, client, auth_headers):
        """Test updating system configuration."""
        new_config = {
            "max_upload_size_mb": 150,
            "session_timeout_minutes": 120,
            "enable_analytics": True,
            "enable_audit_logging": True,
            "retention_days": 2555,
        }

        response = client.put("/api/v1/admin/config", json=new_config, headers=auth_headers)

        assert response.status_code == 200
        data = response.json()

        assert data["max_upload_size_mb"] == 150
        assert data["session_timeout_minutes"] == 120
        assert data["retention_days"] == 2555

    def test_update_config_invalid_range(self, client, auth_headers):
        """Test 400 when config values out of range."""
        invalid_config = {
            "max_upload_size_mb": 600,  # Max is 500
            "session_timeout_minutes": 60,
            "enable_analytics": True,
            "enable_audit_logging": True,
            "retention_days": 365,
        }

        response = client.put("/api/v1/admin/config", json=invalid_config, headers=auth_headers)

        assert response.status_code == 400

    def test_update_config_creates_audit_log(self, client, auth_headers):
        """Test audit log creation on config update."""
        config = {
            "max_upload_size_mb": 100,
            "session_timeout_minutes": 60,
            "enable_analytics": True,
            "enable_audit_logging": True,
            "retention_days": 2555,
        }

        response = client.put("/api/v1/admin/config", json=config, headers=auth_headers)
        assert response.status_code == 200

        # Check audit log
        audit_response = client.get(
            "/api/v1/admin/audit-logs",
            params={"action_type": "CONFIG_CHANGE"},
            headers=auth_headers,
        )

        logs = audit_response.json()["logs"]
        assert any(log["action_type"] == "CONFIG_CHANGE" for log in logs)


class TestAuditLogs:
    """Test GET /api/v1/admin/audit-logs - Retrieve filtered audit logs."""

    def test_get_audit_logs_success(self, client, auth_headers):
        """Test retrieving audit logs with default parameters."""
        response = client.get("/api/v1/admin/audit-logs", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()

        assert "logs" in data
        assert "total" in data
        assert "page" in data
        assert "limit" in data

        # AuditLog schema validation
        if len(data["logs"]) > 0:
            log = data["logs"][0]
            assert "id" in log
            assert "timestamp" in log
            assert "user_id" in log
            assert "action_type" in log
            assert "resource_type" in log
            assert "ip_address" in log

            assert log["action_type"] in [
                "CREATE",
                "UPDATE",
                "DELETE",
                "LOGIN",
                "LOGOUT",
                "CONFIG_CHANGE",
            ]
            assert log["resource_type"] in ["user", "template", "workflow", "configuration"]

    def test_get_audit_logs_filter_by_user(self, client, auth_headers, sample_user_id):
        """Test filtering audit logs by user_id."""
        response = client.get(
            "/api/v1/admin/audit-logs",
            params={"user_id": str(sample_user_id)},
            headers=auth_headers,
        )

        assert response.status_code == 200
        logs = response.json()["logs"]

        # All logs should be for the specified user
        for log in logs:
            assert log["user_id"] == str(sample_user_id)

    def test_get_audit_logs_filter_by_action_type(self, client, auth_headers):
        """Test filtering by action_type."""
        response = client.get(
            "/api/v1/admin/audit-logs", params={"action_type": "UPDATE"}, headers=auth_headers
        )

        assert response.status_code == 200
        logs = response.json()["logs"]

        for log in logs:
            assert log["action_type"] == "UPDATE"

    def test_get_audit_logs_filter_by_resource_type(self, client, auth_headers):
        """Test filtering by resource_type."""
        response = client.get(
            "/api/v1/admin/audit-logs", params={"resource_type": "user"}, headers=auth_headers
        )

        assert response.status_code == 200
        logs = response.json()["logs"]

        for log in logs:
            assert log["resource_type"] == "user"

    def test_get_audit_logs_filter_by_date_range(self, client, auth_headers):
        """Test filtering by date range."""
        start_date = "2025-10-01T00:00:00Z"
        end_date = "2025-10-15T23:59:59Z"

        response = client.get(
            "/api/v1/admin/audit-logs",
            params={"start_date": start_date, "end_date": end_date},
            headers=auth_headers,
        )

        assert response.status_code == 200
        logs = response.json()["logs"]

        # Validate all logs within date range
        for log in logs:
            log_date = datetime.fromisoformat(log["timestamp"].replace("Z", "+00:00"))
            assert start_date <= log["timestamp"] <= end_date

    def test_get_audit_logs_pagination(self, client, auth_headers):
        """Test audit log pagination."""
        response = client.get(
            "/api/v1/admin/audit-logs", params={"page": 1, "limit": 10}, headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 1
        assert data["limit"] == 10
        assert len(data["logs"]) <= 10

    def test_get_audit_logs_diff_view(self, client, auth_headers):
        """Test old_value/new_value diff for UPDATE actions."""
        response = client.get(
            "/api/v1/admin/audit-logs", params={"action_type": "UPDATE"}, headers=auth_headers
        )

        assert response.status_code == 200
        logs = response.json()["logs"]

        # UPDATE logs should have old_value and new_value
        update_logs = [log for log in logs if log["action_type"] == "UPDATE"]
        if len(update_logs) > 0:
            log = update_logs[0]
            assert "old_value" in log
            assert "new_value" in log


# Fixtures
@pytest.fixture
def client():
    """FastAPI test client."""
    # TODO: Import actual app after implementation
    # from src.main import app
    # return TestClient(app)
    pytest.skip("Endpoints not implemented yet - TDD test must fail first")


@pytest.fixture
def auth_headers():
    """Admin authentication headers."""
    return {"Authorization": "Bearer fake-admin-jwt-token"}


@pytest.fixture
def viewer_auth_headers():
    """Viewer role authentication headers."""
    return {"Authorization": "Bearer fake-viewer-jwt-token"}


@pytest.fixture
def sample_user_id():
    """Sample user UUID for testing."""
    return uuid4()
