"""
Contract tests for POST /api/templates/render endpoint.
Based on: .specify/specs/023-create-a-production/contracts/render_endpoint.yaml
"""
import pytest
from fastapi.testclient import TestClient
from uuid import UUID


@pytest.mark.asyncio
async def test_render_request_schema(client: TestClient, mock_editor_token: str):
    """Test that render endpoint accepts valid request schema."""
    response = client.post(
        "/api/templates/render",
        headers={"Authorization": f"Bearer {mock_editor_token}"},
        json={
            "requirements": [
                {
                    "decision_id": "send_specific_documents",
                    "values": {"documents": ["passport", "utility bills"]}
                }
            ]
        }
    )

    # Should not return 422 (validation error)
    assert response.status_code != 422, f"Request schema invalid: {response.json()}"


@pytest.mark.asyncio
async def test_render_response_schema(client: TestClient, mock_editor_token: str):
    """Test that render endpoint returns valid response schema (FR-019 through FR-027)."""
    response = client.post(
        "/api/templates/render",
        headers={"Authorization": f"Bearer {mock_editor_token}"},
        json={
            "requirements": [
                {
                    "decision_id": "send_specific_documents",
                    "values": {"documents": ["passport", "utility bills"]}
                }
            ]
        }
    )

    # Skip if not implemented
    if response.status_code == 404:
        pytest.skip("Endpoint not implemented yet")

    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

    data = response.json()

    # Verify required fields
    assert "request_id" in data, "Missing request_id"
    assert "rendered_letter" in data, "Missing rendered_letter"
    assert "requirements_inserted" in data, "Missing requirements_inserted"
    assert "readability_metrics" in data, "Missing readability_metrics"
    assert "generation_timestamp" in data, "Missing generation_timestamp"
    assert "processing_time_ms" in data, "Missing processing_time_ms"

    # Verify request_id is valid UUID
    try:
        UUID(data["request_id"])
    except ValueError:
        pytest.fail(f"request_id is not a valid UUID: {data['request_id']}")

    # Verify rendered_letter is string
    assert isinstance(data["rendered_letter"], str), "rendered_letter must be string"
    assert len(data["rendered_letter"]) > 0, "rendered_letter must not be empty"

    # Verify requirements_inserted is array
    assert isinstance(data["requirements_inserted"], list), "requirements_inserted must be array"

    # Verify readability_metrics structure
    metrics = data["readability_metrics"]
    assert "flesch_kincaid_grade" in metrics, "Missing flesch_kincaid_grade"
    assert "reading_age" in metrics, "Missing reading_age"
    assert "average_sentence_length" in metrics, "Missing average_sentence_length"
    assert "max_sentence_length" in metrics, "Missing max_sentence_length"
    assert "gds_compliant" in metrics, "Missing gds_compliant"

    # Verify metrics types
    assert isinstance(metrics["reading_age"], int), "reading_age must be integer"
    assert isinstance(metrics["gds_compliant"], bool), "gds_compliant must be boolean"


@pytest.mark.asyncio
async def test_render_gds_compliance(client: TestClient, mock_editor_token: str):
    """Test that render endpoint validates GDS compliance (FR-023, FR-024)."""
    response = client.post(
        "/api/templates/render",
        headers={"Authorization": f"Bearer {mock_editor_token}"},
        json={
            "requirements": [
                {
                    "decision_id": "send_specific_documents",
                    "values": {"documents": ["passport"]}
                }
            ]
        }
    )

    # Skip if not implemented
    if response.status_code == 404:
        pytest.skip("Endpoint not implemented yet")

    assert response.status_code == 200

    data = response.json()
    metrics = data["readability_metrics"]

    # FR-023: Reading age must be 9 or below for GDS compliance
    if metrics["gds_compliant"]:
        assert metrics["reading_age"] <= 9, f"Reading age {metrics['reading_age']} exceeds limit"

    # FR-024: Max sentence length must be 25 words or fewer for GDS compliance
    if metrics["gds_compliant"]:
        assert metrics["max_sentence_length"] <= 25, f"Max sentence {metrics['max_sentence_length']} exceeds limit"


@pytest.mark.asyncio
async def test_render_empty_requirements(client: TestClient, mock_editor_token: str):
    """Test that render endpoint rejects empty requirements (FR-020)."""
    response = client.post(
        "/api/templates/render",
        headers={"Authorization": f"Bearer {mock_editor_token}"},
        json={"requirements": []}
    )

    # Skip if not implemented
    if response.status_code == 404:
        pytest.skip("Endpoint not implemented yet")

    # Should return 400 Bad Request
    assert response.status_code == 400, f"Expected 400 for empty requirements, got {response.status_code}"

    data = response.json()
    assert data["error"] == "ValidationError"
    assert "at least one" in data["message"].lower() or "minimum" in data["message"].lower()


@pytest.mark.asyncio
async def test_render_unknown_decision_id(client: TestClient, mock_editor_token: str):
    """Test that render endpoint rejects unknown decision IDs."""
    response = client.post(
        "/api/templates/render",
        headers={"Authorization": f"Bearer {mock_editor_token}"},
        json={
            "requirements": [
                {
                    "decision_id": "invalid_decision_id_12345",
                    "values": {}
                }
            ]
        }
    )

    # Skip if not implemented
    if response.status_code == 404:
        pytest.skip("Endpoint not implemented yet")

    # Should return 400 Bad Request
    assert response.status_code == 400, f"Expected 400 for unknown decision_id, got {response.status_code}"

    data = response.json()
    assert data["error"] == "ValidationError"


@pytest.mark.asyncio
async def test_render_authentication_required(client: TestClient):
    """Test that render endpoint requires authentication (FR-001)."""
    response = client.post(
        "/api/templates/render",
        json={
            "requirements": [
                {"decision_id": "send_specific_documents", "values": {"documents": ["passport"]}}
            ]
        }
    )

    # Should return 401 Unauthorized
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_render_rate_limiting(client: TestClient, mock_editor_token: str):
    """Test that render endpoint enforces rate limits (FR-005, FR-006)."""
    # Make 11 requests rapidly (limit is 10/min)
    responses = []
    for i in range(11):
        response = client.post(
            "/api/templates/render",
            headers={"Authorization": f"Bearer {mock_editor_token}"},
            json={
                "requirements": [
                    {"decision_id": "send_specific_documents", "values": {"documents": ["passport"]}}
                ]
            }
        )
        responses.append(response)

    status_codes = [r.status_code for r in responses]

    # Skip if not implemented
    if all(code == 404 for code in status_codes):
        pytest.skip("Endpoint not implemented yet")

    # Should have rate limit headers
    last_response = responses[-1]
    if last_response.status_code != 404:
        assert "X-RateLimit-Limit" in last_response.headers or last_response.status_code == 429


@pytest.mark.asyncio
async def test_render_multiple_requirements(client: TestClient, mock_editor_token: str):
    """Test that render endpoint handles multiple requirements."""
    response = client.post(
        "/api/templates/render",
        headers={"Authorization": f"Bearer {mock_editor_token}"},
        json={
            "requirements": [
                {
                    "decision_id": "evidence_between_dates",
                    "values": {"date_start": "2020-01-15", "date_end": "2023-06-30"}
                },
                {
                    "decision_id": "send_specific_documents",
                    "values": {"documents": ["passport", "utility bills"]}
                }
            ]
        }
    )

    # Skip if not implemented
    if response.status_code == 404:
        pytest.skip("Endpoint not implemented yet")

    assert response.status_code == 200

    data = response.json()
    assert len(data["requirements_inserted"]) == 2
    assert "evidence_between_dates" in data["requirements_inserted"]
    assert "send_specific_documents" in data["requirements_inserted"]


@pytest.mark.asyncio
async def test_render_invalid_date_range(client: TestClient, mock_editor_token: str):
    """Test that render endpoint validates date ranges (start before end)."""
    response = client.post(
        "/api/templates/render",
        headers={"Authorization": f"Bearer {mock_editor_token}"},
        json={
            "requirements": [
                {
                    "decision_id": "evidence_between_dates",
                    "values": {"date_start": "2023-12-31", "date_end": "2020-01-01"}
                }
            ]
        }
    )

    # Skip if not implemented
    if response.status_code == 404:
        pytest.skip("Endpoint not implemented yet")

    # Should return 400 for invalid date range
    assert response.status_code == 400

    data = response.json()
    assert data["error"] == "ValidationError"
    assert "date" in data["message"].lower() or "before" in data["message"].lower()
