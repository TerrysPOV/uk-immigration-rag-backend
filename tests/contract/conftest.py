"""
Pytest fixtures for contract tests.

Feature 022: Permanent Content-Addressable Translation Caching
Provides test database session and cleanup fixtures.
"""

import pytest
import os
import uuid
from sqlalchemy import create_engine, TypeDecorator, CHAR
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

# Import base model
from src.models.base import Base


# SQLite-compatible UUID type
class GUID(TypeDecorator):
    """
    Platform-independent GUID type.

    Uses PostgreSQL's UUID type when available,
    otherwise uses CHAR(32) for SQLite.
    """
    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            return dialect.type_descriptor(UUID())
        else:
            return dialect.type_descriptor(CHAR(32))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        elif dialect.name == 'postgresql':
            return str(value)
        else:
            if not isinstance(value, uuid.UUID):
                return "%.32x" % uuid.UUID(value).int
            else:
                return "%.32x" % value.int

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        else:
            if not isinstance(value, uuid.UUID):
                value = uuid.UUID(value)
            return value


@pytest.fixture(scope="session")
def test_engine():
    """
    Create test database engine using SQLite in-memory database.

    Scope: session (shared across all tests in the session)
    """
    # Use SQLite in-memory database for testing
    # Note: In production, this will be PostgreSQL on the droplet
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # Create all tables
    Base.metadata.create_all(bind=engine)

    yield engine

    # Cleanup
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture(scope="function")
def db_session(test_engine):
    """
    Create a new database session for each test.

    Scope: function (fresh session for each test)
    Automatically rolls back changes after each test.
    """
    # Create session factory
    TestingSessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=test_engine
    )

    # Create session
    session = TestingSessionLocal()

    yield session

    # Rollback any changes and close session
    session.rollback()
    session.close()


@pytest.fixture(scope="function")
def mock_env_vars(monkeypatch):
    """
    Mock environment variables for testing.

    Sets OPENROUTER_API_KEY and other required env vars.
    """
    monkeypatch.setenv("OPENROUTER_API_KEY", "test_api_key_123")
    monkeypatch.setenv("OPENROUTER_MODEL", "anthropic/claude-3-haiku")
    monkeypatch.setenv("OPENROUTER_REFERER", "https://test.vectorgov.poview.ai")
    monkeypatch.setenv("DEEPINFRA_API_KEY", "test_deepinfra_key")

    yield


@pytest.fixture(scope="function")
def client(db_session):
    """
    Create FastAPI TestClient for API testing.

    Returns TestClient with overridden database dependency.
    """
    from fastapi.testclient import TestClient
    from src.main import app
    from src.database import get_db

    # Override database dependency
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    # Cleanup
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def mock_editor_token():
    """
    Mock JWT token for Editor role.

    Returns a mock token that will be accepted by the RBAC middleware
    in development mode (when AUTHENTIK_PUBLIC_KEY is not set).
    """
    # In development mode, the RBAC middleware accepts tokens without verification
    # The token payload will be extracted but not verified
    import json
    import base64

    # Create mock JWT payload
    payload = {
        "sub": "test-user-123",
        "email": "test@example.com",
        "preferred_username": "testuser",
        "resource_access": {
            "gov-ai-realm": {
                "roles": ["editor"]
            }
        },
        "permissions": ["canManagePipeline"]
    }

    # Create a mock JWT token (just base64 encode the payload for testing)
    # In development mode, signature verification is skipped
    header = base64.urlsafe_b64encode(json.dumps({"alg": "RS256", "typ": "JWT"}).encode()).decode().rstrip("=")
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    signature = "mock_signature"

    return f"{header}.{payload_b64}.{signature}"


@pytest.fixture(scope="function")
def mock_admin_token():
    """
    Mock JWT token for Admin role.
    """
    import json
    import base64

    payload = {
        "sub": "test-admin-456",
        "email": "admin@example.com",
        "preferred_username": "adminuser",
        "resource_access": {
            "gov-ai-realm": {
                "roles": ["admin"]
            }
        },
        "permissions": ["canManagePipeline", "canManageUsers"]
    }

    header = base64.urlsafe_b64encode(json.dumps({"alg": "RS256", "typ": "JWT"}).encode()).decode().rstrip("=")
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    signature = "mock_signature"

    return f"{header}.{payload_b64}.{signature}"


@pytest.fixture(scope="function")
def mock_viewer_token():
    """
    Mock JWT token for Viewer role (lowest permissions).
    """
    import json
    import base64

    payload = {
        "sub": "test-viewer-789",
        "email": "viewer@example.com",
        "preferred_username": "vieweruser",
        "resource_access": {
            "gov-ai-realm": {
                "roles": ["viewer"]
            }
        },
        "permissions": []
    }

    header = base64.urlsafe_b64encode(json.dumps({"alg": "RS256", "typ": "JWT"}).encode()).decode().rstrip("=")
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    signature = "mock_signature"

    return f"{header}.{payload_b64}.{signature}"
