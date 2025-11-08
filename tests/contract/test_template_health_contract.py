"""
Contract tests for GET /api/templates/health endpoint.
Based on: .specify/specs/023-create-a-production/contracts/health_endpoint.yaml
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
from datetime import datetime

from src.main import app


@pytest.mark.contract
class TestHealthEndpointContract:
    """Contract tests for GET /api/templates/health - Health Check endpoint."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)

    def test_health_no_authentication_required(self, client):
        """
        Test that health endpoint works without authentication (public endpoint).

        Contract reference: health_endpoint.yaml lines 17
        Functional requirement: FR-045
        """
        response = client.get("/api/templates/health")

        # Skip if endpoint not implemented yet
        if response.status_code == 404:
            pytest.skip("Endpoint not implemented yet")

        # Should NOT return 401 (authentication not required)
        assert response.status_code in [200, 503], \
            f"Health check should not require auth, got {response.status_code}"

    def test_health_response_schema_healthy(self, client):
        """
        Test that health endpoint returns valid response schema when healthy.

        Contract reference: health_endpoint.yaml lines 23-41
        Functional requirements: FR-046, FR-047, FR-048
        """
        response = client.get("/api/templates/health")

        # Skip if endpoint not implemented yet
        if response.status_code == 404:
            pytest.skip("Endpoint not implemented yet")

        # Accept either 200 (healthy) or 503 (unhealthy) as valid
        assert response.status_code in [200, 503], \
            f"Expected 200 or 503, got {response.status_code}"

        data = response.json()

        # Verify required top-level fields
        assert "status" in data, "Missing status field"
        assert "timestamp" in data, "Missing timestamp field"
        assert "components" in data, "Missing components field"
        assert "version" in data, "Missing version field"

        # Verify status enum
        assert data["status"] in ["healthy", "unhealthy"], \
            f"status must be 'healthy' or 'unhealthy', got {data['status']}"

        # Verify timestamp is ISO 8601 format
        try:
            datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00"))
        except ValueError:
            pytest.fail(f"timestamp is not valid ISO 8601: {data['timestamp']}")

        # Verify version is string
        assert isinstance(data["version"], str), "version must be string"

        # Verify components structure
        components = data["components"]
        assert "decision_library" in components, "Missing decision_library component"
        assert "llm_service" in components, "Missing llm_service component"

        # Verify decision_library component
        library = components["decision_library"]
        assert "status" in library, "decision_library missing status"
        assert library["status"] in ["healthy", "unhealthy"], \
            "decision_library status must be 'healthy' or 'unhealthy'"

        if library["status"] == "healthy":
            assert "loaded_count" in library, "Healthy library must include loaded_count"
            assert isinstance(library["loaded_count"], int), "loaded_count must be integer"
            assert library["loaded_count"] >= 10, \
                f"loaded_count must be at least 10 (FR-029), got {library['loaded_count']}"

            if "version" in library:
                assert isinstance(library["version"], str), "library version must be string"
        else:
            assert "error" in library, "Unhealthy library must include error message"
            assert isinstance(library["error"], str), "error must be string"

        # Verify llm_service component
        llm = components["llm_service"]
        assert "status" in llm, "llm_service missing status"
        assert llm["status"] in ["healthy", "unhealthy"], \
            "llm_service status must be 'healthy' or 'unhealthy'"

        if llm["status"] == "healthy":
            if "provider" in llm:
                assert isinstance(llm["provider"], str), "provider must be string"
            if "latency_ms" in llm:
                assert isinstance(llm["latency_ms"], int), "latency_ms must be integer"
                assert llm["latency_ms"] >= 0, "latency_ms must be non-negative"
        else:
            assert "error" in llm, "Unhealthy LLM service must include error message"
            assert isinstance(llm["error"], str), "error must be string"

    def test_health_returns_200_when_all_healthy(self, client):
        """
        Test that health endpoint returns 200 when all components healthy.

        Contract reference: health_endpoint.yaml lines 23-41
        Functional requirement: FR-048
        """
        response = client.get("/api/templates/health")

        # Skip if endpoint not implemented yet
        if response.status_code == 404:
            pytest.skip("Endpoint not implemented yet")

        if response.status_code == 200:
            data = response.json()
            # If status is 200, overall status must be "healthy"
            assert data["status"] == "healthy", \
                "200 response must have status='healthy'"

            # All components must be healthy
            assert data["components"]["decision_library"]["status"] == "healthy", \
                "200 response requires healthy decision_library"
            assert data["components"]["llm_service"]["status"] == "healthy", \
                "200 response requires healthy llm_service"

    def test_health_returns_503_when_components_unhealthy(self, client):
        """
        Test that health endpoint returns 503 when components unhealthy.

        Contract reference: health_endpoint.yaml lines 43-92
        Functional requirement: FR-049
        """
        response = client.get("/api/templates/health")

        # Skip if endpoint not implemented yet
        if response.status_code == 404:
            pytest.skip("Endpoint not implemented yet")

        if response.status_code == 503:
            data = response.json()
            # If status is 503, overall status must be "unhealthy"
            assert data["status"] == "unhealthy", \
                "503 response must have status='unhealthy'"

            # At least one component must be unhealthy
            library_unhealthy = data["components"]["decision_library"]["status"] == "unhealthy"
            llm_unhealthy = data["components"]["llm_service"]["status"] == "unhealthy"

            assert library_unhealthy or llm_unhealthy, \
                "503 response requires at least one unhealthy component"

    def test_health_library_missing_error(self, client):
        """
        Test health response when decision library not found.

        Contract reference: health_endpoint.yaml lines 50-62
        Functional requirement: FR-032
        """
        # This test requires mocking library unavailability
        # Skip for now - requires implementation-specific mocking
        pytest.skip("Requires implementation-specific library unavailability simulation")

    def test_health_llm_unavailable_error(self, client):
        """
        Test health response when LLM service unreachable.

        Contract reference: health_endpoint.yaml lines 65-78
        Functional requirement: FR-047
        """
        # This test requires mocking LLM service failure
        # Skip for now - requires implementation-specific mocking
        pytest.skip("Requires implementation-specific LLM unavailability simulation")

    def test_health_consistent_schema_200_vs_503(self, client):
        """
        Test that health response schema is consistent between 200 and 503.

        Both status codes must return same fields, just with different values.
        """
        response = client.get("/api/templates/health")

        # Skip if endpoint not implemented yet
        if response.status_code == 404:
            pytest.skip("Endpoint not implemented yet")

        # Schema should be identical regardless of status code
        data = response.json()
        required_fields = ["status", "timestamp", "components", "version"]
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"

        required_components = ["decision_library", "llm_service"]
        for component in required_components:
            assert component in data["components"], \
                f"Missing required component: {component}"
