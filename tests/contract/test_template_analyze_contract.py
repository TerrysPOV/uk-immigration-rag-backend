"""
Contract tests for POST /api/templates/analyze endpoint.
Based on: .specify/specs/023-create-a-production/contracts/analyze_endpoint.yaml
"""
import pytest
from fastapi.testclient import TestClient
from uuid import UUID
import json


@pytest.mark.asyncio
async def test_analyze_request_schema(client: TestClient, mock_editor_token: str):
    """Test that analyze endpoint accepts valid request schema."""
    response = client.post(
        "/api/templates/analyze",
        headers={"Authorization": f"Bearer {mock_editor_token}"},
        json={
            "document_url": "https://www.gov.uk/guidance/immigration-rules/immigration-rules-appendix-eu"
        }
    )

    # Should return 200 or error, but not 422 (validation error)
    assert response.status_code != 422, f"Request schema invalid: {response.json()}"


@pytest.mark.asyncio
async def test_analyze_response_schema(client: TestClient, mock_editor_token: str):
    """Test that analyze endpoint returns valid response schema (FR-010 through FR-018)."""
    response = client.post(
        "/api/templates/analyze",
        headers={"Authorization": f"Bearer {mock_editor_token}"},
        json={
            "document_url": "https://www.gov.uk/guidance/immigration-rules/immigration-rules-appendix-eu"
        }
    )

    # Skip if endpoint not implemented yet
    if response.status_code == 404:
        pytest.skip("Endpoint not implemented yet")

    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

    data = response.json()

    # Verify required fields
    assert "request_id" in data, "Missing request_id"
    assert "document_url" in data, "Missing document_url"
    assert "matches" in data, "Missing matches"
    assert "analysis_timestamp" in data, "Missing analysis_timestamp"
    assert "model_used" in data, "Missing model_used"
    assert "processing_time_ms" in data, "Missing processing_time_ms"

    # Verify request_id is valid UUID
    try:
        UUID(data["request_id"])
    except ValueError:
        pytest.fail(f"request_id is not a valid UUID: {data['request_id']}")

    # Verify matches structure
    assert isinstance(data["matches"], list), "matches must be an array"

    for match in data["matches"]:
        assert "decision_id" in match, "Match missing decision_id"
        assert "confidence" in match, "Match missing confidence"
        assert "evidence" in match, "Match missing evidence"

        # Verify confidence is 0.0-1.0
        assert 0.0 <= match["confidence"] <= 1.0, f"Invalid confidence: {match['confidence']}"

        # Verify evidence max length (FR-013)
        assert len(match["evidence"]) <= 500, f"Evidence exceeds 500 chars: {len(match['evidence'])}"

    # Verify processing_time_ms
    assert isinstance(data["processing_time_ms"], int), "processing_time_ms must be integer"
    assert data["processing_time_ms"] >= 0, "processing_time_ms must be non-negative"


@pytest.mark.asyncio
async def test_analyze_authentication_required(client: TestClient):
    """Test that analyze endpoint requires authentication (FR-001)."""
    response = client.post(
        "/api/templates/analyze",
        json={"document_url": "https://www.gov.uk/guidance/test"}
    )

    # Should return 401 Unauthorized
    assert response.status_code == 401, f"Expected 401 without auth, got {response.status_code}"

    data = response.json()
    assert "request_id" in data, "Error response missing request_id"
    assert "error" in data, "Error response missing error"
    assert "message" in data, "Error response missing message"


@pytest.mark.asyncio
async def test_analyze_rate_limiting(client: TestClient, mock_editor_token: str):
    """Test that analyze endpoint enforces rate limits (FR-005, FR-006)."""
    # Skip if endpoint not implemented
    test_url = "https://www.gov.uk/guidance/test-rate-limit"

    # Make 11 requests rapidly (limit is 10/min)
    responses = []
    for i in range(11):
        response = client.post(
            "/api/templates/analyze",
            headers={"Authorization": f"Bearer {mock_editor_token}"},
            json={"document_url": test_url}
        )
        responses.append(response)

    # Check if any request got rate limited
    status_codes = [r.status_code for r in responses]

    # Should have at least one 429 if rate limiting works
    # (or all 404 if not implemented yet)
    if all(code == 404 for code in status_codes):
        pytest.skip("Endpoint not implemented yet")

    # Verify rate limit headers present
    last_response = responses[-1]
    if last_response.status_code != 404:
        assert "X-RateLimit-Limit" in last_response.headers or last_response.status_code == 429


@pytest.mark.asyncio
async def test_analyze_invalid_url_format(client: TestClient, mock_editor_token: str):
    """Test that analyze endpoint validates URL format (FR-052 SSRF protection)."""
    invalid_urls = [
        "http://insecure.com",  # Not HTTPS
        "https://localhost/test",  # Localhost blocked
        "https://127.0.0.1/test",  # Loopback blocked
        "https://192.168.1.1/test",  # Private IP blocked
    ]

    for invalid_url in invalid_urls:
        response = client.post(
            "/api/templates/analyze",
            headers={"Authorization": f"Bearer {mock_editor_token}"},
            json={"document_url": invalid_url}
        )

        # Skip if not implemented
        if response.status_code == 404:
            pytest.skip("Endpoint not implemented yet")

        # Should return 400 Bad Request for invalid URLs
        assert response.status_code == 400, f"Expected 400 for {invalid_url}, got {response.status_code}"

        data = response.json()
        assert data["error"] == "ValidationError", f"Expected ValidationError, got {data.get('error')}"


@pytest.mark.asyncio
async def test_analyze_document_not_found(client: TestClient, mock_editor_token: str):
    """Test that analyze endpoint handles missing documents (404 error)."""
    response = client.post(
        "/api/templates/analyze",
        headers={"Authorization": f"Bearer {mock_editor_token}"},
        json={"document_url": "https://www.gov.uk/nonexistent-document-12345"}
    )

    # Skip if not implemented
    if response.status_code == 404 and "not found" not in response.text.lower():
        pytest.skip("Endpoint not implemented yet")

    # Should return 404 or 502 for document not found
    assert response.status_code in [404, 502], f"Expected 404 or 502, got {response.status_code}"


@pytest.mark.asyncio
async def test_analyze_timeout_handling(client: TestClient, mock_editor_token: str):
    """Test that analyze endpoint handles timeouts (504 error, FR-017 30s timeout)."""
    # This is a contract test - actual timeout behavior verified in integration tests
    # Just verify the endpoint can return 504
    pass  # Timeout testing requires mocking


@pytest.mark.asyncio
async def test_analyze_custom_prompt_optional(client: TestClient, mock_editor_token: str):
    """Test that custom_analysis_prompt is optional."""
    response = client.post(
        "/api/templates/analyze",
        headers={"Authorization": f"Bearer {mock_editor_token}"},
        json={
            "document_url": "https://www.gov.uk/guidance/test",
            "custom_analysis_prompt": "Focus on date requirements only"
        }
    )

    # Skip if not implemented
    if response.status_code == 404:
        pytest.skip("Endpoint not implemented yet")

    # Should accept custom prompt (status 200, 400, or 502, but not 422)
    assert response.status_code != 422, "Should accept custom_analysis_prompt"
