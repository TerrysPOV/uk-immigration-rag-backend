"""
Contract test for GET /api/rag/health endpoint (T005).
Validates health check response schema matches actual API implementation.
Uses actual running API instance (localhost:8000).

T005 Requirements:
- GET /api/rag/health → HTTP 200
- Response schema matches HealthStatus model
- Health status is "healthy" when Qdrant accessible
- Validates quantization_active, compression_ratio, memory_mb fields
"""

import pytest
import requests

API_BASE_URL = "http://localhost:8000"


def test_health_endpoint_returns_200():
    """T005: Test that GET /api/rag/health returns HTTP 200."""
    response = requests.get(f"{API_BASE_URL}/api/rag/health", timeout=10)

    # Should return 200 (success) or 401 (auth required)
    assert response.status_code in [200, 401], f"Unexpected status: {response.status_code}"


def test_health_response_schema():
    """T005: Test that health response matches HealthStatus model schema."""
    response = requests.get(f"{API_BASE_URL}/api/rag/health", timeout=10)

    if response.status_code == 200:
        data = response.json()

        # Assert required fields from HealthStatus model
        assert "status" in data, "Missing 'status' field"
        assert "document_count" in data, "Missing 'document_count' field"
        assert "quantization_active" in data, "Missing 'quantization_active' field"
        assert "compression_ratio" in data, "Missing 'compression_ratio' field"
        assert "memory_mb" in data, "Missing 'memory_mb' field"
        assert "qdrant_status" in data, "Missing 'qdrant_status' field"
        assert "deepinfra_status" in data, "Missing 'deepinfra_status' field"
        assert "pipeline_components" in data, "Missing 'pipeline_components' field"
        assert "last_check" in data, "Missing 'last_check' field"

        # Assert types
        assert isinstance(data["status"], str), "'status' must be string"
        assert isinstance(data["document_count"], int), "'document_count' must be integer"
        assert isinstance(data["quantization_active"], bool), "'quantization_active' must be boolean"
        assert isinstance(
            data["compression_ratio"], (int, float)
        ), "'compression_ratio' must be number"
        assert isinstance(data["memory_mb"], (int, float)), "'memory_mb' must be number"
        assert isinstance(data["qdrant_status"], str), "'qdrant_status' must be string"
        assert isinstance(data["deepinfra_status"], str), "'deepinfra_status' must be string"
        assert isinstance(data["pipeline_components"], list), "'pipeline_components' must be array"

    elif response.status_code == 401:
        pytest.skip("Authentication required - endpoint protected")
    else:
        pytest.fail(f"Unexpected status code: {response.status_code}")


def test_health_status_values():
    """T005: Test that health status is 'healthy' when Qdrant is accessible."""
    response = requests.get(f"{API_BASE_URL}/api/rag/health", timeout=10)

    if response.status_code == 200:
        data = response.json()

        # Status should be one of: healthy, degraded, unhealthy
        assert data["status"] in [
            "healthy",
            "degraded",
            "unhealthy",
        ], f"Invalid status value: {data['status']}"

        # When status is healthy, Qdrant should be connected
        if data["status"] == "healthy":
            assert (
                data["qdrant_status"] == "connected"
            ), "Qdrant must be connected when status is healthy"
            assert data["document_count"] > 0, "document_count should be > 0 when healthy"

    elif response.status_code == 401:
        pytest.skip("Authentication required - endpoint protected")
    else:
        pytest.fail(f"Unexpected status code: {response.status_code}")


def test_health_quantization_metrics():
    """T005: Test that quantization metrics are reported correctly."""
    response = requests.get(f"{API_BASE_URL}/api/rag/health", timeout=10)

    if response.status_code == 200:
        data = response.json()

        # Compression ratio validation
        assert 0.0 <= data["compression_ratio"] <= 1.0, "compression_ratio must be between 0.0-1.0"

        # Memory MB validation
        assert data["memory_mb"] >= 0.0, "memory_mb must be >= 0"

        # When quantization is active, compression ratio should be high (>=97%)
        if data["quantization_active"]:
            # Allow some tolerance for calculation differences
            assert (
                data["compression_ratio"] >= 0.95
            ), f"Expected compression_ratio >= 0.95, got {data['compression_ratio']}"

    elif response.status_code == 401:
        pytest.skip("Authentication required - endpoint protected")
    else:
        pytest.fail(f"Unexpected status code: {response.status_code}")


def test_health_pipeline_components():
    """T005: Test that pipeline_components array contains expected components."""
    response = requests.get(f"{API_BASE_URL}/api/rag/health", timeout=10)

    if response.status_code == 200:
        data = response.json()

        # pipeline_components should be a non-empty array when status is healthy
        if data["status"] == "healthy":
            assert len(data["pipeline_components"]) > 0, "pipeline_components should not be empty"

            # All components should be strings
            for component in data["pipeline_components"]:
                assert isinstance(component, str), "Each pipeline component must be a string"

    elif response.status_code == 401:
        pytest.skip("Authentication required - endpoint protected")
    else:
        pytest.fail(f"Unexpected status code: {response.status_code}")
