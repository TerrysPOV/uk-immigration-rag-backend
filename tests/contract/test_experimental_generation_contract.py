"""
Contract test for POST /api/v1/templates/experimental/generate endpoint.
Tests request validation, response schema, and error handling.

CRITICAL: This test is expected to FAIL until T012-T015 are implemented.
This is part of TDD workflow - write failing tests first.
"""

import pytest
from fastapi.testclient import TestClient
import io
import json


# These tests will fail until implementation exists
pytestmark = pytest.mark.xfail(
    reason="Experimental endpoint not yet implemented (T012-T015 pending)",
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
def mock_auth_header():
    """Mock Google OAuth authorization header."""
    return {"Authorization": "Bearer mock_google_oauth_token_editor_role"}


def test_endpoint_requires_custom_system_prompt(api_client, mock_auth_header):
    """Assert custom_system_prompt is required field."""
    response = api_client.post(
        "/api/v1/templates/experimental/generate",
        headers=mock_auth_header,
        data={
            "model_preference": "gpt-4"
        }
    )

    assert response.status_code == 400
    assert "custom_system_prompt" in response.text.lower()


def test_endpoint_validates_prompt_max_length(api_client, mock_auth_header):
    """Assert custom_system_prompt max 5000 chars."""
    long_prompt = "x" * 5001  # Exceeds 5000 char limit

    response = api_client.post(
        "/api/v1/templates/experimental/generate",
        headers=mock_auth_header,
        data={
            "custom_system_prompt": long_prompt
        }
    )

    assert response.status_code == 400
    data = response.json()
    assert data["error"] == "prompt_too_long"
    assert "5000" in data["message"]


def test_endpoint_validates_file_count(api_client, mock_auth_header):
    """Assert max 5 files allowed."""
    files = [
        ("artifacts", ("file1.txt", io.BytesIO(b"content1"), "text/plain")),
        ("artifacts", ("file2.txt", io.BytesIO(b"content2"), "text/plain")),
        ("artifacts", ("file3.txt", io.BytesIO(b"content3"), "text/plain")),
        ("artifacts", ("file4.txt", io.BytesIO(b"content4"), "text/plain")),
        ("artifacts", ("file5.txt", io.BytesIO(b"content5"), "text/plain")),
        ("artifacts", ("file6.txt", io.BytesIO(b"content6"), "text/plain")),  # 6th file
    ]

    response = api_client.post(
        "/api/v1/templates/experimental/generate",
        headers=mock_auth_header,
        data={"custom_system_prompt": "Test prompt"},
        files=files
    )

    assert response.status_code == 400
    data = response.json()
    assert data["error"] == "too_many_files"
    assert "5" in data["message"]


def test_endpoint_validates_file_size(api_client, mock_auth_header):
    """Assert max 10MB per file."""
    large_file_content = b"x" * (10 * 1024 * 1024 + 1)  # 10MB + 1 byte

    files = [
        ("artifacts", ("large.txt", io.BytesIO(large_file_content), "text/plain"))
    ]

    response = api_client.post(
        "/api/v1/templates/experimental/generate",
        headers=mock_auth_header,
        data={"custom_system_prompt": "Test prompt"},
        files=files
    )

    assert response.status_code == 400
    data = response.json()
    assert data["error"] == "file_too_large"
    assert "10MB" in data["message"]


def test_endpoint_validates_file_types(api_client, mock_auth_header):
    """Assert only .txt/.md/.json/.html allowed."""
    files = [
        ("artifacts", ("document.pdf", io.BytesIO(b"fake pdf"), "application/pdf"))
    ]

    response = api_client.post(
        "/api/v1/templates/experimental/generate",
        headers=mock_auth_header,
        data={"custom_system_prompt": "Test prompt"},
        files=files
    )

    assert response.status_code == 400
    data = response.json()
    assert data["error"] == "invalid_file_type"
    assert ".txt" in data["message"] or ".md" in data["message"]


def test_successful_response_schema(api_client, mock_auth_header):
    """Assert response schema matches OpenAPI specification."""
    response = api_client.post(
        "/api/v1/templates/experimental/generate",
        headers=mock_auth_header,
        data={"custom_system_prompt": "Convert to plain English"}
    )

    assert response.status_code == 200
    data = response.json()

    # Required fields from OpenAPI schema
    assert "generated_content" in data
    assert isinstance(data["generated_content"], str)

    assert "readability_metrics" in data
    metrics = data["readability_metrics"]
    assert "flesch_score" in metrics
    assert isinstance(metrics["flesch_score"], (int, float))
    assert 0 <= metrics["flesch_score"] <= 100

    assert "grade_level" in metrics
    assert isinstance(metrics["grade_level"], (int, float))

    assert "reading_age" in metrics
    assert isinstance(metrics["reading_age"], (int, float))

    assert "model_used" in data
    assert isinstance(data["model_used"], str)

    assert "render_time_ms" in data
    assert isinstance(data["render_time_ms"], (int, float))

    assert "artifacts_processed" in data
    assert isinstance(data["artifacts_processed"], list)


def test_unauthenticated_request_returns_401(api_client):
    """Assert 401 when no auth token provided."""
    response = api_client.post(
        "/api/v1/templates/experimental/generate",
        data={"custom_system_prompt": "Test"}
    )

    assert response.status_code == 401
    data = response.json()
    assert "error" in data
    assert "token" in data["message"].lower() or "auth" in data["message"].lower()


def test_insufficient_permissions_returns_403(api_client):
    """Assert 403 when user has Viewer role."""
    viewer_header = {"Authorization": "Bearer mock_google_oauth_token_viewer_role"}

    response = api_client.post(
        "/api/v1/templates/experimental/generate",
        headers=viewer_header,
        data={"custom_system_prompt": "Test"}
    )

    assert response.status_code == 403
    data = response.json()
    assert data["error"] == "insufficient_permissions"
    assert "Editor" in data["message"] or "Admin" in data["message"]


def test_rate_limit_exceeded_returns_429(api_client, mock_auth_header):
    """Assert 429 when rate limit exceeded."""
    # Send 11 requests (exceeds 10/minute limit)
    for _ in range(11):
        response = api_client.post(
            "/api/v1/templates/experimental/generate",
            headers=mock_auth_header,
            data={"custom_system_prompt": "Test"}
        )

    assert response.status_code == 429
    data = response.json()
    assert data["error"] == "rate_limit_exceeded"
    assert "retry_after" in data
    assert isinstance(data["retry_after"], int)


def test_generation_failure_returns_500(api_client, mock_auth_header):
    """Assert 500 when template generation fails."""
    # This would require mocking the LLM client to fail
    # For now, we assert the error response structure

    # Assuming we can trigger a failure by passing invalid model
    response = api_client.post(
        "/api/v1/templates/experimental/generate",
        headers=mock_auth_header,
        data={
            "custom_system_prompt": "Test",
            "model_preference": "invalid_model_that_does_not_exist"
        }
    )

    # Should either reject at validation (400) or fail at generation (500)
    assert response.status_code in [400, 500]
    if response.status_code == 500:
        data = response.json()
        assert data["error"] == "generation_failed"
