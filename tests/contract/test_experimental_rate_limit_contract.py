"""
Contract test for rate limiting on experimental endpoint.
Tests 10 requests/minute and 100 requests/hour limits.

CRITICAL: This test is expected to FAIL until T015 is implemented.
This is part of TDD workflow - write failing tests first.
"""

import pytest
from fastapi.testclient import TestClient
import time


# These tests will fail until implementation exists
pytestmark = pytest.mark.xfail(
    reason="Rate limiting not yet implemented (T015 pending)",
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
def editor_token():
    """Mock Google OAuth token for Editor role."""
    return "Bearer mock_google_oauth_editor_jwt"


def test_rate_limit_10_per_minute_enforced(api_client, editor_token):
    """Assert 10 requests/minute limit enforced."""
    endpoint = "/api/v1/templates/experimental/generate"
    headers = {"Authorization": editor_token}

    # Send 10 requests - should all succeed (or fail for other reasons, but not rate limit)
    for i in range(10):
        response = api_client.post(
            endpoint,
            headers=headers,
            data={"custom_system_prompt": f"Test prompt {i}"}
        )
        # Should NOT be rate limited yet
        assert response.status_code != 429, \
            f"Request {i+1}/10 should not be rate limited"

    # 11th request should be rate limited
    response = api_client.post(
        endpoint,
        headers=headers,
        data={"custom_system_prompt": "11th request - should fail"}
    )

    assert response.status_code == 429, "11th request should exceed 10/minute limit"
    data = response.json()
    assert data["error"] == "rate_limit_exceeded"
    assert "10" in data["message"] and "minute" in data["message"].lower()


def test_rate_limit_100_per_hour_enforced(api_client, editor_token):
    """Assert 100 requests/hour limit enforced."""
    endpoint = "/api/v1/templates/experimental/generate"
    headers = {"Authorization": editor_token}

    # This test is expensive (100+ requests), so we simulate by checking the limit exists
    # In production, this would run in integration tests with time acceleration

    # Send requests until we hit the hour limit or 101 requests
    for i in range(101):
        response = api_client.post(
            endpoint,
            headers=headers,
            data={"custom_system_prompt": f"Hour test {i}"}
        )

        # If we get 429 before 101 requests, check it's the hour limit
        if response.status_code == 429:
            data = response.json()
            # Should mention hour limit or be after ~100 requests
            assert i >= 100 or "hour" in data["message"].lower(), \
                "Rate limit triggered too early or wrong limit"
            break
    else:
        # If we sent 101 requests without 429, rate limit not working
        pytest.fail("101st request should exceed 100/hour limit")


def test_rate_limit_includes_retry_after_header(api_client, editor_token):
    """Assert 429 response includes retry_after header."""
    endpoint = "/api/v1/templates/experimental/generate"
    headers = {"Authorization": editor_token}

    # Trigger rate limit (send 11 requests to exceed 10/minute)
    for i in range(11):
        response = api_client.post(
            endpoint,
            headers=headers,
            data={"custom_system_prompt": f"Retry test {i}"}
        )

    # Last request should be rate limited
    assert response.status_code == 429
    data = response.json()

    # Must include retry_after field per OpenAPI spec
    assert "retry_after" in data, "Response must include retry_after"
    assert isinstance(data["retry_after"], int), "retry_after must be integer (seconds)"
    assert data["retry_after"] > 0, "retry_after must be positive"
    assert data["retry_after"] <= 3600, "retry_after should not exceed 1 hour"


def test_rate_limit_per_user(api_client):
    """Assert rate limiting is per-user (different tokens have separate limits)."""
    endpoint = "/api/v1/templates/experimental/generate"

    editor1_token = "Bearer mock_google_oauth_editor1_jwt"
    editor2_token = "Bearer mock_google_oauth_editor2_jwt"

    # User 1: send 10 requests (at limit)
    for i in range(10):
        response = api_client.post(
            endpoint,
            headers={"Authorization": editor1_token},
            data={"custom_system_prompt": f"User1 request {i}"}
        )
        assert response.status_code != 429, "User 1 should not be rate limited yet"

    # User 2: should be able to send 10 requests (separate limit)
    for i in range(10):
        response = api_client.post(
            endpoint,
            headers={"Authorization": editor2_token},
            data={"custom_system_prompt": f"User2 request {i}"}
        )
        assert response.status_code != 429, \
            "User 2 should have separate rate limit from User 1"

    # User 1: 11th request should be rate limited
    response = api_client.post(
        endpoint,
        headers={"Authorization": editor1_token},
        data={"custom_system_prompt": "User1 11th request"}
    )
    assert response.status_code == 429, "User 1 should be rate limited on 11th request"

    # User 2: 11th request should also be rate limited (own limit)
    response = api_client.post(
        endpoint,
        headers={"Authorization": editor2_token},
        data={"custom_system_prompt": "User2 11th request"}
    )
    assert response.status_code == 429, "User 2 should be rate limited on 11th request"


def test_rate_limit_resets_after_window(api_client, editor_token):
    """Assert rate limit resets after time window expires."""
    endpoint = "/api/v1/templates/experimental/generate"
    headers = {"Authorization": editor_token}

    # Send 10 requests (at limit)
    for i in range(10):
        api_client.post(
            endpoint,
            headers=headers,
            data={"custom_system_prompt": f"Window test {i}"}
        )

    # 11th request should be rate limited
    response = api_client.post(
        endpoint,
        headers=headers,
        data={"custom_system_prompt": "Should be rate limited"}
    )
    assert response.status_code == 429

    # Wait for rate limit window to reset (61 seconds for 1 minute window)
    time.sleep(61)

    # Next request should succeed (limit reset)
    response = api_client.post(
        endpoint,
        headers=headers,
        data={"custom_system_prompt": "Should succeed after reset"}
    )
    assert response.status_code != 429, \
        "Rate limit should reset after time window expires"


def test_successful_requests_not_rate_limited(api_client, editor_token):
    """Assert successful requests within limit are not rate limited."""
    endpoint = "/api/v1/templates/experimental/generate"
    headers = {"Authorization": editor_token}

    # Send 5 requests (well under 10/minute limit)
    for i in range(5):
        response = api_client.post(
            endpoint,
            headers=headers,
            data={"custom_system_prompt": f"Success test {i}"}
        )

        # Should NOT be rate limited
        assert response.status_code != 429, \
            f"Request {i+1}/5 should not be rate limited"

        # May succeed or fail for other reasons (validation, generation, etc.)
        assert response.status_code in [200, 400, 401, 403, 500], \
            f"Unexpected status code: {response.status_code}"
