"""
Feature 012 - T135: Integration Test - Admin Panel Scenario
FR-AP-001: List users with pagination and filters
FR-AP-002: Assign roles to users
FR-AP-008: Audit log creation for admin actions

Test Scenario:
1. Admin lists all users
2. Admin assigns role to a specific user
3. Verify audit log entry was created
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import uuid

from src.main import app
from src.database import Base, get_db
from src.models.user import User
from src.models.role import Role
from src.models.audit_log import AuditLog


# ============================================================================
# Test Database Setup
# ============================================================================

SQLALCHEMY_DATABASE_URL = "sqlite:///./test_admin_panel.db"

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    """Override database dependency with test database."""
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(scope="module")
def test_db():
    """Create test database and tables."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="module")
def test_client(test_db):
    """Create test client."""
    client = TestClient(app)
    return client


@pytest.fixture(scope="function")
def setup_test_data():
    """Setup test data for each test."""
    db = TestingSessionLocal()

    # Create admin role
    admin_role = Role(
        id=str(uuid.uuid4()),
        name="admin",
        description="Administrator role",
        permissions=["admin:read", "admin:write", "user:manage", "audit:read"],
        created_at=datetime.utcnow(),
    )
    db.add(admin_role)

    # Create viewer role
    viewer_role = Role(
        id=str(uuid.uuid4()),
        name="viewer",
        description="Viewer role",
        permissions=["read:documents"],
        created_at=datetime.utcnow(),
    )
    db.add(viewer_role)

    # Create admin user
    admin_user = User(
        id=str(uuid.uuid4()),
        username="admin_test",
        email="admin@example.com",
        role="admin",
        status="active",
        created_at=datetime.utcnow(),
    )
    db.add(admin_user)

    # Create regular user (to be promoted)
    regular_user = User(
        id=str(uuid.uuid4()),
        username="user_test",
        email="user@example.com",
        role="viewer",
        status="active",
        created_at=datetime.utcnow(),
    )
    db.add(regular_user)

    db.commit()

    user_ids = {
        "admin_id": admin_user.id,
        "user_id": regular_user.id,
    }

    db.close()

    yield user_ids

    # Cleanup
    db = TestingSessionLocal()
    db.query(AuditLog).delete()
    db.query(User).delete()
    db.query(Role).delete()
    db.commit()
    db.close()


# ============================================================================
# T135: Integration Test - Admin Panel Scenario
# ============================================================================


def test_admin_panel_user_role_management_scenario(test_client, setup_test_data):
    """
    Test complete admin panel scenario (FR-AP-001, FR-AP-002, FR-AP-008).

    Steps:
    1. List all users (GET /api/v1/admin/users)
    2. Assign 'caseworker' role to user (PUT /api/v1/admin/users/{id}/role)
    3. Verify audit log was created

    Expected:
    - User list returns 2 users
    - Role assignment succeeds
    - Audit log contains role change with old/new values
    """
    admin_id = setup_test_data["admin_id"]
    user_id = setup_test_data["user_id"]

    # Mock authentication token (in real test, use proper OIDC mock)
    headers = {
        "Authorization": f"Bearer mock_admin_token",
        "X-User-ID": admin_id,
    }

    # ========================================================================
    # Step 1: List users (FR-AP-001)
    # ========================================================================

    response = test_client.get("/api/v1/admin/users", headers=headers)

    assert response.status_code == 200, f"Failed to list users: {response.text}"

    data = response.json()
    assert "users" in data
    assert "pagination" in data
    assert len(data["users"]) == 2, "Expected 2 users (admin + regular user)"

    # Verify pagination metadata
    assert data["pagination"]["page"] == 1
    assert data["pagination"]["total_count"] == 2

    # Find regular user in list
    regular_user = next((u for u in data["users"] if u["username"] == "user_test"), None)
    assert regular_user is not None, "Regular user not found in list"
    assert regular_user["role"] == "viewer", "User should have 'viewer' role"

    # ========================================================================
    # Step 2: Assign role to user (FR-AP-002)
    # ========================================================================

    role_assignment_payload = {
        "role_name": "caseworker",
    }

    response = test_client.put(
        f"/api/v1/admin/users/{user_id}/role",
        json=role_assignment_payload,
        headers=headers,
    )

    assert response.status_code == 200, f"Failed to assign role: {response.text}"

    updated_user = response.json()
    assert updated_user["role"] == "caseworker", "Role should be updated to 'caseworker'"
    assert updated_user["username"] == "user_test"

    # ========================================================================
    # Step 3: Verify audit log (FR-AP-008)
    # ========================================================================

    db = TestingSessionLocal()

    # Query audit logs for role change
    audit_logs = (
        db.query(AuditLog)
        .filter(
            AuditLog.user_id == admin_id,
            AuditLog.action_type == "role_change",
            AuditLog.resource_type == "user",
            AuditLog.resource_id == user_id,
        )
        .all()
    )

    assert len(audit_logs) > 0, "Audit log not created for role change"

    audit_log = audit_logs[0]
    assert audit_log.old_value is not None, "Audit log should contain old value"
    assert audit_log.new_value is not None, "Audit log should contain new value"

    # Verify old/new role values
    assert audit_log.old_value.get("role") == "viewer", "Old role should be 'viewer'"
    assert audit_log.new_value.get("role") == "caseworker", "New role should be 'caseworker'"

    # Verify audit log metadata
    assert audit_log.ip_address is not None, "Audit log should contain IP address"
    assert audit_log.user_agent is not None, "Audit log should contain user agent"

    db.close()

    print("✅ T135: Admin Panel User Role Management scenario PASSED")


def test_admin_cannot_modify_own_account(test_client, setup_test_data):
    """
    Test FR-AP-005: Prevent self-modification.

    Expected:
    - Admin cannot assign role to themselves
    - Returns 403 Forbidden
    """
    admin_id = setup_test_data["admin_id"]

    headers = {
        "Authorization": f"Bearer mock_admin_token",
        "X-User-ID": admin_id,
    }

    role_assignment_payload = {
        "role_name": "viewer",
    }

    response = test_client.put(
        f"/api/v1/admin/users/{admin_id}/role",
        json=role_assignment_payload,
        headers=headers,
    )

    assert response.status_code == 403, "Should reject self-modification"
    assert "Cannot modify your own account" in response.text

    print("✅ T135b: Admin self-modification prevention PASSED")


def test_admin_user_list_filters(test_client, setup_test_data):
    """
    Test FR-AP-001: User list filters (role, status, search).

    Expected:
    - Filter by role returns only matching users
    - Filter by status returns only matching users
    - Search returns matching username/email
    """
    admin_id = setup_test_data["admin_id"]

    headers = {
        "Authorization": f"Bearer mock_admin_token",
        "X-User-ID": admin_id,
    }

    # Filter by role
    response = test_client.get("/api/v1/admin/users?role=admin", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data["users"]) == 1
    assert data["users"][0]["role"] == "admin"

    # Filter by status
    response = test_client.get("/api/v1/admin/users?status=active", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert all(u["status"] == "active" for u in data["users"])

    # Search by username
    response = test_client.get("/api/v1/admin/users?search=user_test", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data["users"]) == 1
    assert data["users"][0]["username"] == "user_test"

    print("✅ T135c: Admin user list filters PASSED")


# ============================================================================
# Pytest Configuration
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
