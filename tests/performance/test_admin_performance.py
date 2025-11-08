"""
Feature 012 - T141: Performance Test - Admin Operations
SLA: Admin operations must complete in <500ms (FR-AP-004)

Test Scenario:
1. GET /api/v1/admin/users - List users (<500ms)
2. PUT /api/v1/admin/users/{id}/role - Assign role (<500ms)
3. GET /api/v1/admin/audit-logs - Get audit logs (<500ms)

Performance Requirements:
- p95 response time: <500ms for all admin operations
- Target: <300ms for optimal UX
"""

import pytest
import time
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import uuid
import statistics

from src.main import app
from src.database import Base, get_db
from src.models.user import User
from src.models.role import Role


# ============================================================================
# Test Database Setup
# ============================================================================

SQLALCHEMY_DATABASE_URL = "sqlite:///./test_admin_performance.db"

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
def setup_test_users():
    """Setup 100 test users for performance testing."""
    db = TestingSessionLocal()

    # Create roles
    roles = [
        Role(id=str(uuid.uuid4()), name="admin", description="Admin", permissions=["admin:write"]),
        Role(
            id=str(uuid.uuid4()),
            name="viewer",
            description="Viewer",
            permissions=["read:documents"],
        ),
    ]
    for role in roles:
        db.add(role)

    # Create 100 users
    users = []
    for i in range(100):
        user = User(
            id=str(uuid.uuid4()),
            username=f"testuser{i}",
            email=f"testuser{i}@example.com",
            role="viewer",
            status="active",
            created_at=datetime.utcnow(),
        )
        users.append(user)
        db.add(user)

    # Create admin user
    admin_user = User(
        id=str(uuid.uuid4()),
        username="admin_perf_test",
        email="admin@example.com",
        role="admin",
        status="active",
        created_at=datetime.utcnow(),
    )
    db.add(admin_user)

    db.commit()

    user_ids = {
        "admin_id": admin_user.id,
        "test_user_id": users[0].id,
    }

    db.close()

    yield user_ids

    # Cleanup
    db = TestingSessionLocal()
    db.query(User).delete()
    db.query(Role).delete()
    db.commit()
    db.close()


# ============================================================================
# T141: Performance Test - Admin Operations <500ms
# ============================================================================


def test_admin_list_users_performance(test_client, setup_test_users):
    """
    Test GET /api/v1/admin/users performance (FR-AP-004).

    Expected:
    - p95 response time: <500ms
    - Target: <300ms

    Runs 20 requests and calculates p95.
    """
    admin_id = setup_test_users["admin_id"]

    headers = {
        "Authorization": "Bearer mock_admin_token",
        "X-User-ID": admin_id,
    }

    response_times = []

    # Warm-up request
    test_client.get("/api/v1/admin/users", headers=headers)

    # Run 20 performance tests
    for i in range(20):
        start_time = time.time()

        response = test_client.get("/api/v1/admin/users?page=1&limit=50", headers=headers)

        end_time = time.time()
        response_time_ms = (end_time - start_time) * 1000

        assert response.status_code == 200, f"Request {i + 1} failed: {response.text}"

        response_times.append(response_time_ms)
        print(f"Request {i + 1}: {response_time_ms:.2f}ms")

    # Calculate statistics
    p50 = statistics.median(response_times)
    p95 = statistics.quantiles(response_times, n=20)[18]  # 95th percentile
    avg = statistics.mean(response_times)
    max_time = max(response_times)

    print("\n=== GET /api/v1/admin/users Performance ===")
    print(f"Average: {avg:.2f}ms")
    print(f"p50 (median): {p50:.2f}ms")
    print(f"p95: {p95:.2f}ms")
    print(f"Max: {max_time:.2f}ms")

    # Assert p95 <500ms SLA
    assert p95 < 500, f"p95 response time {p95:.2f}ms exceeds 500ms SLA"

    # Warn if not meeting target
    if p95 > 300:
        print(f"⚠️  WARNING: p95 {p95:.2f}ms exceeds 300ms target (still within 500ms SLA)")
    else:
        print(f"✅ p95 {p95:.2f}ms meets 300ms target")

    print("✅ T141a: Admin list users performance PASSED")


def test_admin_assign_role_performance(test_client, setup_test_users):
    """
    Test PUT /api/v1/admin/users/{id}/role performance (FR-AP-004).

    Expected:
    - p95 response time: <500ms
    - Target: <300ms

    Runs 20 role assignment requests.
    """
    admin_id = setup_test_users["admin_id"]
    test_user_id = setup_test_users["test_user_id"]

    headers = {
        "Authorization": "Bearer mock_admin_token",
        "X-User-ID": admin_id,
    }

    response_times = []

    # Warm-up request
    payload = {"role_name": "caseworker"}
    test_client.put(f"/api/v1/admin/users/{test_user_id}/role", json=payload, headers=headers)

    # Run 20 performance tests (alternating roles)
    for i in range(20):
        role_name = "caseworker" if i % 2 == 0 else "viewer"
        payload = {"role_name": role_name}

        start_time = time.time()

        response = test_client.put(
            f"/api/v1/admin/users/{test_user_id}/role",
            json=payload,
            headers=headers,
        )

        end_time = time.time()
        response_time_ms = (end_time - start_time) * 1000

        assert response.status_code == 200, f"Request {i + 1} failed: {response.text}"

        response_times.append(response_time_ms)
        print(f"Request {i + 1}: {response_time_ms:.2f}ms (role: {role_name})")

    # Calculate statistics
    p50 = statistics.median(response_times)
    p95 = statistics.quantiles(response_times, n=20)[18]
    avg = statistics.mean(response_times)
    max_time = max(response_times)

    print("\n=== PUT /api/v1/admin/users/{id}/role Performance ===")
    print(f"Average: {avg:.2f}ms")
    print(f"p50 (median): {p50:.2f}ms")
    print(f"p95: {p95:.2f}ms")
    print(f"Max: {max_time:.2f}ms")

    # Assert p95 <500ms SLA
    assert p95 < 500, f"p95 response time {p95:.2f}ms exceeds 500ms SLA"

    if p95 > 300:
        print(f"⚠️  WARNING: p95 {p95:.2f}ms exceeds 300ms target")
    else:
        print(f"✅ p95 {p95:.2f}ms meets 300ms target")

    print("✅ T141b: Admin assign role performance PASSED")


def test_admin_get_audit_logs_performance(test_client, setup_test_users):
    """
    Test GET /api/v1/admin/audit-logs performance (FR-AP-004).

    Expected:
    - p95 response time: <500ms
    - Target: <300ms

    Runs 20 audit log retrieval requests.
    """
    admin_id = setup_test_users["admin_id"]

    headers = {
        "Authorization": "Bearer mock_admin_token",
        "X-User-ID": admin_id,
    }

    response_times = []

    # Warm-up request
    test_client.get("/api/v1/admin/audit-logs", headers=headers)

    # Run 20 performance tests
    for i in range(20):
        start_time = time.time()

        response = test_client.get(
            "/api/v1/admin/audit-logs?page=1&limit=50",
            headers=headers,
        )

        end_time = time.time()
        response_time_ms = (end_time - start_time) * 1000

        assert response.status_code == 200, f"Request {i + 1} failed: {response.text}"

        response_times.append(response_time_ms)
        print(f"Request {i + 1}: {response_time_ms:.2f}ms")

    # Calculate statistics
    p50 = statistics.median(response_times)
    p95 = statistics.quantiles(response_times, n=20)[18]
    avg = statistics.mean(response_times)
    max_time = max(response_times)

    print("\n=== GET /api/v1/admin/audit-logs Performance ===")
    print(f"Average: {avg:.2f}ms")
    print(f"p50 (median): {p50:.2f}ms")
    print(f"p95: {p95:.2f}ms")
    print(f"Max: {max_time:.2f}ms")

    # Assert p95 <500ms SLA
    assert p95 < 500, f"p95 response time {p95:.2f}ms exceeds 500ms SLA"

    if p95 > 300:
        print(f"⚠️  WARNING: p95 {p95:.2f}ms exceeds 300ms target")
    else:
        print(f"✅ p95 {p95:.2f}ms meets 300ms target")

    print("✅ T141c: Admin get audit logs performance PASSED")


# ============================================================================
# Pytest Configuration
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
