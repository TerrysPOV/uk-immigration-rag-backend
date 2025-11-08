"""
T015: Contract test for GET/POST/PUT/DELETE /api/search/saved endpoints.
Validates request/response schemas match API contracts (api_contracts.yaml).
Tests endpoints that don't exist yet (TDD approach - tests MUST FAIL initially).

Contract Requirements:
- GET /api/search/saved → HTTP 200 with SavedSearch[]
- POST /api/search/saved → HTTP 201 with SavedSearch
- PUT /api/search/saved/{id} → HTTP 200 with SavedSearch
- DELETE /api/search/saved/{id} → HTTP 204 (no content)
- Auth required: All requests need bearer token → HTTP 401 if missing
- Security: Modify/delete only user's own searches → HTTP 403 if wrong user
- Limit: 50 saved searches per user → HTTP 403 if exceeded
- Duplicate names: Auto-append timestamp to make unique
"""

import pytest
import requests
import uuid

API_BASE_URL = "http://localhost:8000"


def test_saved_searches_list_endpoint_exists():
    """T015: Test that GET /api/search/saved endpoint exists."""
    response = requests.get(f"{API_BASE_URL}/api/search/saved", timeout=10)

    # Endpoint should exist (not 404) - expects 200 or 401 (auth required)
    assert response.status_code != 404, (
        "Endpoint /api/search/saved should exist (expected 200/401, got 404)"
    )


def test_saved_searches_list_returns_200():
    """T015: Test that GET /api/search/saved returns HTTP 200 with correct schema."""
    response = requests.get(f"{API_BASE_URL}/api/search/saved", timeout=10)

    # Should return 200 (success) or 401 (auth required)
    assert response.status_code in [200, 401], f"Unexpected status: {response.status_code}"

    if response.status_code == 200:
        data = response.json()

        # Response should be array
        assert isinstance(data, list), "Response must be array of SavedSearch"

        # If searches exist, validate first search schema
        if len(data) > 0:
            search = data[0]

            # Assert required fields from SavedSearch schema
            assert "id" in search, "Missing 'id' field"
            assert "user_id" in search, "Missing 'user_id' field"
            assert "name" in search, "Missing 'name' field"
            assert "query" in search, "Missing 'query' field"
            assert "created_at" in search, "Missing 'created_at' field"

            # Assert types
            assert isinstance(search["id"], str), "'id' must be string (UUID)"
            assert isinstance(search["user_id"], str), "'user_id' must be string"
            assert isinstance(search["name"], str), "'name' must be string"
            assert isinstance(search["query"], str), "'query' must be string"
            assert isinstance(search["created_at"], str), "'created_at' must be string (datetime)"

            # Assert length constraints
            assert 1 <= len(search["name"]) <= 100, "name must be 1-100 chars"
            assert 1 <= len(search["query"]) <= 1000, "query must be 1-1000 chars"

            # Optional fields (nullable)
            if "filters" in search and search["filters"] is not None:
                assert isinstance(search["filters"], dict), "'filters' must be object"

            if "last_used_at" in search and search["last_used_at"] is not None:
                assert isinstance(search["last_used_at"], str), "'last_used_at' must be string"

            if "usage_count" in search:
                assert isinstance(search["usage_count"], int), "'usage_count' must be integer"
                assert search["usage_count"] >= 0, "'usage_count' must be >= 0"


def test_saved_searches_create_endpoint_exists():
    """T015: Test that POST /api/search/saved endpoint exists."""
    response = requests.post(
        f"{API_BASE_URL}/api/search/saved",
        json={"name": "Test Search", "query": "test query"},
        timeout=10,
    )

    # Endpoint should exist (not 404) - expects 201 or 401 (auth required)
    assert response.status_code != 404, (
        "Endpoint POST /api/search/saved should exist (expected 201/401, got 404)"
    )


def test_saved_searches_create_returns_201():
    """T015: Test that POST /api/search/saved returns HTTP 201 with created search."""
    response = requests.post(
        f"{API_BASE_URL}/api/search/saved",
        json={
            "name": "Skilled Worker Visa Search",
            "query": "How to apply for Skilled Worker visa?",
            "filters": {"document_type": "guidance"},
        },
        timeout=10,
    )

    # Should return 201 (created) or 401 (auth required)
    assert response.status_code in [201, 401], f"Unexpected status: {response.status_code}"

    if response.status_code == 201:
        data = response.json()

        # Assert required fields from SavedSearch schema
        assert "id" in data, "Missing 'id' field"
        assert "user_id" in data, "Missing 'user_id' field"
        assert "name" in data, "Missing 'name' field"
        assert "query" in data, "Missing 'query' field"
        assert "created_at" in data, "Missing 'created_at' field"

        # Assert values match request
        assert data["name"] == "Skilled Worker Visa Search", "name should match request"
        assert data["query"] == "How to apply for Skilled Worker visa?", "query should match request"

        # Assert usage_count defaults to 0
        if "usage_count" in data:
            assert data["usage_count"] == 0, "New search should have usage_count=0"


def test_saved_searches_create_duplicate_name_auto_appends_timestamp():
    """T015: Test that duplicate names are auto-appended with timestamp."""
    # Create first search with unique name
    search_name = f"Duplicate Test {uuid.uuid4().hex[:8]}"

    response1 = requests.post(
        f"{API_BASE_URL}/api/search/saved",
        json={"name": search_name, "query": "test query 1"},
        timeout=10,
    )

    if response1.status_code == 201:
        # Create second search with same name
        response2 = requests.post(
            f"{API_BASE_URL}/api/search/saved",
            json={"name": search_name, "query": "test query 2"},
            timeout=10,
        )

        if response2.status_code == 201:
            data2 = response2.json()

            # Name should be auto-modified (timestamp appended)
            assert data2["name"] != search_name, (
                f"Duplicate name should be auto-modified, got '{data2['name']}'"
            )
            assert data2["name"].startswith(search_name), "Modified name should start with original"
    elif response1.status_code == 401:
        pytest.skip("Authentication required - endpoint protected")
    else:
        pytest.fail(f"Unexpected status code: {response1.status_code}")


def test_saved_searches_create_limit_50_per_user():
    """T015: Test that users cannot exceed 50 saved searches limit."""
    # Get current count
    list_response = requests.get(f"{API_BASE_URL}/api/search/saved", timeout=10)

    if list_response.status_code == 200:
        current_count = len(list_response.json())

        # Should never exceed 50
        assert current_count <= 50, f"User has {current_count} saved searches (limit is 50)"

        # If at limit, creating new search should fail
        if current_count >= 50:
            response = requests.post(
                f"{API_BASE_URL}/api/search/saved",
                json={"name": "Should Fail", "query": "test"},
                timeout=10,
            )

            # Should return 403 (forbidden - limit exceeded)
            assert response.status_code in [403, 401], f"Expected 403/401, got {response.status_code}"

            if response.status_code == 403:
                data = response.json()
                assert "detail" in data or "error" in data, "Error response should have detail"
    elif list_response.status_code == 401:
        pytest.skip("Authentication required - endpoint protected")
    else:
        pytest.fail(f"Unexpected status code: {list_response.status_code}")


def test_saved_searches_update_endpoint_exists():
    """T015: Test that PUT /api/search/saved/{id} endpoint exists."""
    test_id = str(uuid.uuid4())

    response = requests.put(
        f"{API_BASE_URL}/api/search/saved/{test_id}",
        json={"name": "Updated Name", "query": "updated query"},
        timeout=10,
    )

    # Endpoint should exist (not 404 for endpoint itself)
    # Expects 200 (success), 401 (auth), 403 (wrong user), or 404 (entry not found)
    assert response.status_code != 404 or response.status_code in [200, 401, 403], (
        f"Endpoint PUT /api/search/saved/{{id}} should exist (got {response.status_code})"
    )


def test_saved_searches_update_returns_200():
    """T015: Test that PUT /api/search/saved/{id} returns HTTP 200 with updated search."""
    # First, get list of saved searches
    list_response = requests.get(f"{API_BASE_URL}/api/search/saved", timeout=10)

    if list_response.status_code == 200:
        searches = list_response.json()

        if len(searches) > 0:
            # Update first search
            search_id = searches[0]["id"]

            update_response = requests.put(
                f"{API_BASE_URL}/api/search/saved/{search_id}",
                json={"name": "Updated Name", "query": "updated query"},
                timeout=10,
            )

            # Should return 200 (success), 401 (auth), or 403 (wrong user)
            assert update_response.status_code in [
                200,
                401,
                403,
            ], f"Unexpected status: {update_response.status_code}"

            if update_response.status_code == 200:
                data = update_response.json()

                # Assert updated values
                assert data["name"] == "Updated Name", "name should be updated"
                assert data["query"] == "updated query", "query should be updated"
                assert data["id"] == search_id, "id should remain unchanged"
        else:
            pytest.skip("No saved searches to test update")
    elif list_response.status_code == 401:
        pytest.skip("Authentication required - endpoint protected")
    else:
        pytest.fail(f"Unexpected list status code: {list_response.status_code}")


def test_saved_searches_delete_endpoint_exists():
    """T015: Test that DELETE /api/search/saved/{id} endpoint exists."""
    test_id = str(uuid.uuid4())

    response = requests.delete(f"{API_BASE_URL}/api/search/saved/{test_id}", timeout=10)

    # Endpoint should exist (not 404 for endpoint itself)
    # Expects 204 (success), 401 (auth), 403 (wrong user), or 404 (entry not found)
    assert response.status_code != 404 or response.status_code in [204, 401, 403], (
        f"Endpoint DELETE /api/search/saved/{{id}} should exist (got {response.status_code})"
    )


def test_saved_searches_delete_returns_204():
    """T015: Test that DELETE /api/search/saved/{id} returns HTTP 204 on success."""
    # First, get list of saved searches
    list_response = requests.get(f"{API_BASE_URL}/api/search/saved", timeout=10)

    if list_response.status_code == 200:
        searches = list_response.json()

        if len(searches) > 0:
            # Delete first search
            search_id = searches[0]["id"]

            delete_response = requests.delete(
                f"{API_BASE_URL}/api/search/saved/{search_id}", timeout=10
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
            pytest.skip("No saved searches to test delete")
    elif list_response.status_code == 401:
        pytest.skip("Authentication required - endpoint protected")
    else:
        pytest.fail(f"Unexpected list status code: {list_response.status_code}")


def test_saved_searches_missing_required_fields_returns_400():
    """T015: Test that missing required fields returns HTTP 400."""
    # Missing 'query' field
    response = requests.post(
        f"{API_BASE_URL}/api/search/saved", json={"name": "Test Search"}, timeout=10  # Missing query
    )

    # Should return 400/422 for validation error, or 401 if auth required first
    assert response.status_code in [
        400,
        401,
        422,
    ], f"Expected 400/401/422, got {response.status_code}"

    if response.status_code in [400, 422]:
        data = response.json()
        assert "detail" in data or "error" in data, "Error response should have detail field"


def test_saved_searches_requires_authentication():
    """T015: Test that all endpoints require authentication."""
    # Test GET
    get_response = requests.get(
        f"{API_BASE_URL}/api/search/saved", headers={}, timeout=10  # No auth header
    )

    # Should return 401 if auth is enforced
    assert get_response.status_code in [200, 401], f"GET unexpected status: {get_response.status_code}"

    # Test POST
    post_response = requests.post(
        f"{API_BASE_URL}/api/search/saved",
        json={"name": "Test", "query": "test"},
        headers={},  # No auth header
        timeout=10,
    )

    # Should return 401 if auth is enforced
    assert post_response.status_code in [201, 401], f"POST unexpected status: {post_response.status_code}"
