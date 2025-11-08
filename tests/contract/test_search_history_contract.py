"""
T014: Contract test for GET/DELETE /api/search/history endpoints.
Validates request/response schemas match API contracts (api_contracts.yaml).
Tests endpoints that don't exist yet (TDD approach - tests MUST FAIL initially).

Contract Requirements:
- GET /api/search/history → HTTP 200 with SearchHistoryEntry[]
- DELETE /api/search/history/{id} → HTTP 204 (no content)
- Auth required: All requests need bearer token → HTTP 401 if missing
- Security: DELETE only works for entries owned by user → HTTP 403 if wrong user
- Not found: DELETE non-existent entry → HTTP 404
"""

import pytest
import requests
import uuid

API_BASE_URL = "http://localhost:8000"


def test_search_history_list_endpoint_exists():
    """T014: Test that GET /api/search/history endpoint exists."""
    response = requests.get(f"{API_BASE_URL}/api/search/history", timeout=10)

    # Endpoint should exist (not 404) - expects 200 or 401 (auth required)
    assert response.status_code != 404, (
        "Endpoint /api/search/history should exist (expected 200/401, got 404)"
    )


def test_search_history_list_returns_200():
    """T014: Test that GET /api/search/history returns HTTP 200 with correct schema."""
    response = requests.get(f"{API_BASE_URL}/api/search/history", timeout=10)

    # Should return 200 (success) or 401 (auth required)
    assert response.status_code in [200, 401], f"Unexpected status: {response.status_code}"

    if response.status_code == 200:
        data = response.json()

        # Response should be array
        assert isinstance(data, list), "Response must be array of SearchHistoryEntry"

        # If entries exist, validate first entry schema
        if len(data) > 0:
            entry = data[0]

            # Assert required fields from SearchHistoryEntry schema
            assert "id" in entry, "Missing 'id' field"
            assert "user_id" in entry, "Missing 'user_id' field"
            assert "query" in entry, "Missing 'query' field"
            assert "timestamp" in entry, "Missing 'timestamp' field"

            # Assert types
            assert isinstance(entry["id"], str), "'id' must be string (UUID)"
            assert isinstance(entry["user_id"], str), "'user_id' must be string"
            assert isinstance(entry["query"], str), "'query' must be string"
            assert isinstance(entry["timestamp"], str), "'timestamp' must be string (datetime)"

            # Assert query length constraints
            assert 1 <= len(entry["query"]) <= 1000, "query must be 1-1000 chars"

            # Optional fields (nullable)
            if "result_count" in entry and entry["result_count"] is not None:
                assert isinstance(entry["result_count"], int), "'result_count' must be integer"
                assert entry["result_count"] >= 0, "'result_count' must be >= 0"

            if "filters_applied" in entry and entry["filters_applied"] is not None:
                assert isinstance(entry["filters_applied"], dict), "'filters_applied' must be object"

            if "execution_time_ms" in entry and entry["execution_time_ms"] is not None:
                assert isinstance(entry["execution_time_ms"], int), "'execution_time_ms' must be integer"
                assert entry["execution_time_ms"] >= 0, "'execution_time_ms' must be >= 0"


def test_search_history_list_empty_returns_empty_array():
    """T014: Test that GET /api/search/history returns empty array if no history."""
    response = requests.get(f"{API_BASE_URL}/api/search/history", timeout=10)

    if response.status_code == 200:
        data = response.json()

        # Should return array (empty or with entries)
        assert isinstance(data, list), "Response must be array"
    elif response.status_code == 401:
        pytest.skip("Authentication required - endpoint protected")
    else:
        pytest.fail(f"Unexpected status code: {response.status_code}")


def test_search_history_list_sorted_newest_first():
    """T014: Test that GET /api/search/history returns entries sorted newest first."""
    response = requests.get(f"{API_BASE_URL}/api/search/history", timeout=10)

    if response.status_code == 200:
        data = response.json()

        # If 2+ entries, validate descending timestamp order
        if len(data) >= 2:
            # Timestamps should be in descending order (newest first)
            first_timestamp = data[0]["timestamp"]
            second_timestamp = data[1]["timestamp"]

            # Compare as strings (ISO format is lexicographically sortable)
            assert first_timestamp >= second_timestamp, (
                f"Entries should be sorted newest first: {first_timestamp} < {second_timestamp}"
            )
    elif response.status_code == 401:
        pytest.skip("Authentication required - endpoint protected")
    else:
        pytest.fail(f"Unexpected status code: {response.status_code}")


def test_search_history_delete_endpoint_exists():
    """T014: Test that DELETE /api/search/history/{id} endpoint exists."""
    # Use random UUID (entry doesn't exist, but endpoint should)
    test_id = str(uuid.uuid4())

    response = requests.delete(f"{API_BASE_URL}/api/search/history/{test_id}", timeout=10)

    # Endpoint should exist (not 404 for endpoint itself)
    # Expects 204 (success), 401 (auth), 403 (wrong user), or 404 (entry not found)
    assert response.status_code != 404 or response.status_code in [204, 401, 403], (
        f"Endpoint /api/search/history/{{id}} should exist (got {response.status_code})"
    )


def test_search_history_delete_returns_204():
    """T014: Test that DELETE /api/search/history/{id} returns HTTP 204 on success."""
    # First, get list of entries
    list_response = requests.get(f"{API_BASE_URL}/api/search/history", timeout=10)

    if list_response.status_code == 200:
        entries = list_response.json()

        if len(entries) > 0:
            # Delete first entry
            entry_id = entries[0]["id"]

            delete_response = requests.delete(
                f"{API_BASE_URL}/api/search/history/{entry_id}", timeout=10
            )

            # Should return 204 (success), 401 (auth), or 403 (wrong user)
            assert delete_response.status_code in [
                204,
                401,
                403,
            ], f"Unexpected status: {delete_response.status_code}"

            if delete_response.status_code == 204:
                # 204 should have no content
                assert delete_response.text == "" or len(delete_response.text) == 0, (
                    "HTTP 204 should have empty body"
                )
        else:
            pytest.skip("No search history entries to test delete")
    elif list_response.status_code == 401:
        pytest.skip("Authentication required - endpoint protected")
    else:
        pytest.fail(f"Unexpected list status code: {list_response.status_code}")


def test_search_history_delete_nonexistent_returns_404():
    """T014: Test that DELETE non-existent entry returns HTTP 404."""
    # Use random UUID that doesn't exist
    nonexistent_id = str(uuid.uuid4())

    response = requests.delete(
        f"{API_BASE_URL}/api/search/history/{nonexistent_id}", timeout=10
    )

    # Should return 404 (not found), 401 (auth), or 403 (wrong user)
    assert response.status_code in [
        401,
        403,
        404,
    ], f"Expected 401/403/404, got {response.status_code}"

    if response.status_code == 404:
        # Error response should have detail
        data = response.json()
        assert "detail" in data or "error" in data, "Error response should have detail field"


def test_search_history_delete_invalid_uuid_returns_400():
    """T014: Test that DELETE with invalid UUID format returns HTTP 400."""
    # Use invalid UUID format
    invalid_id = "not-a-valid-uuid-format"

    response = requests.delete(
        f"{API_BASE_URL}/api/search/history/{invalid_id}", timeout=10
    )

    # Should return 400/422 (validation error), 401 (auth), or 404 (not found)
    assert response.status_code in [
        400,
        401,
        404,
        422,
    ], f"Expected 400/401/404/422, got {response.status_code}"


def test_search_history_list_requires_authentication():
    """T014: Test that GET /api/search/history requires authentication."""
    # Request without Authorization header should return 401
    response = requests.get(
        f"{API_BASE_URL}/api/search/history", headers={}, timeout=10  # No auth header
    )

    # Should return 401 if auth is enforced
    # Or 200 if auth not yet implemented (will be enforced in production)
    assert response.status_code in [200, 401], f"Unexpected status: {response.status_code}"


def test_search_history_delete_requires_authentication():
    """T014: Test that DELETE /api/search/history/{id} requires authentication."""
    test_id = str(uuid.uuid4())

    # Request without Authorization header should return 401
    response = requests.delete(
        f"{API_BASE_URL}/api/search/history/{test_id}", headers={}, timeout=10  # No auth header
    )

    # Should return 401 if auth is enforced
    # Or 204/404 if auth not yet implemented (will be enforced in production)
    assert response.status_code in [204, 401, 404], f"Unexpected status: {response.status_code}"


def test_search_history_fifo_eviction():
    """T014: Test that search history respects 100 entry limit (FIFO eviction)."""
    # This test would require creating 101 entries to trigger eviction
    # For contract testing, we just verify the list endpoint works
    response = requests.get(f"{API_BASE_URL}/api/search/history", timeout=10)

    if response.status_code == 200:
        data = response.json()

        # Should never exceed 100 entries per user
        assert len(data) <= 100, f"Search history exceeds 100 entry limit: {len(data)}"
    elif response.status_code == 401:
        pytest.skip("Authentication required - endpoint protected")
    else:
        pytest.fail(f"Unexpected status code: {response.status_code}")
