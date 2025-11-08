"""
Contract tests for Advanced Search API.

Tests all 5 endpoints from contracts/advanced-search-api.yaml:
1. POST /api/v1/search/boolean
2. POST /api/v1/search/validate
3. POST /api/v1/search/field-search
4. GET /api/v1/search/saved-queries
5. POST /api/v1/search/saved-queries
6. GET /api/v1/search/saved-queries/{id}
7. DELETE /api/v1/search/saved-queries/{id}
8. POST /api/v1/search/saved-queries/{id}/execute

These tests MUST FAIL before implementation (TDD).
"""

import pytest
from fastapi.testclient import TestClient
from uuid import uuid4


class TestBooleanSearch:
    """Test POST /api/v1/search/boolean - Boolean query execution."""

    def test_execute_boolean_search_success(self, client, auth_headers):
        """Test successful boolean search with AND/OR/NOT (FR-AS-001)."""
        search_request = {
            "query_syntax": 'title:visa AND (content:"tier 2" OR content:"tier 5") NOT content:expired',
            "limit": 10,
            "offset": 0,
        }

        response = client.post("/api/v1/search/boolean", json=search_request, headers=auth_headers)

        assert response.status_code == 200
        data = response.json()

        assert "results" in data
        assert "total" in data
        assert "query_time_ms" in data
        assert "parsed_query" in data

        assert isinstance(data["results"], list)
        assert isinstance(data["total"], int)
        assert isinstance(data["query_time_ms"], (int, float))

        # SearchResult schema validation
        if len(data["results"]) > 0:
            result = data["results"][0]
            assert "id" in result
            assert "title" in result
            assert "content" in result
            assert "relevance_score" in result
            assert 0 <= result["relevance_score"] <= 1

    def test_execute_boolean_search_with_ast(self, client, auth_headers):
        """Test parsed query AST is returned (FR-AS-002)."""
        search_request = {"query_syntax": "title:immigration AND content:visa", "limit": 10}

        response = client.post("/api/v1/search/boolean", json=search_request, headers=auth_headers)

        assert response.status_code == 200
        data = response.json()

        # Validate AST structure
        parsed_query = data["parsed_query"]
        assert "type" in parsed_query
        assert parsed_query["type"] == "AND"
        assert "left" in parsed_query
        assert "right" in parsed_query

    def test_execute_boolean_search_invalid_syntax(self, client, auth_headers):
        """Test 400 with syntax error position."""
        invalid_request = {
            "query_syntax": "title:visa AND AND content:tier",  # Invalid: double AND
            "limit": 10,
        }

        response = client.post("/api/v1/search/boolean", json=invalid_request, headers=auth_headers)

        assert response.status_code == 400
        data = response.json()

        assert "error" in data
        assert "syntax_error_position" in data
        assert isinstance(data["syntax_error_position"], int)

    def test_execute_boolean_search_with_parentheses(self, client, auth_headers):
        """Test complex query with parentheses."""
        search_request = {
            "query_syntax": "(title:visa OR title:immigration) AND NOT content:expired",
            "limit": 10,
        }

        response = client.post("/api/v1/search/boolean", json=search_request, headers=auth_headers)

        assert response.status_code == 200

    def test_execute_boolean_search_pagination(self, client, auth_headers):
        """Test pagination with limit/offset."""
        search_request = {"query_syntax": "title:visa", "limit": 5, "offset": 10}

        response = client.post("/api/v1/search/boolean", json=search_request, headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) <= 5


class TestValidateQuery:
    """Test POST /api/v1/search/validate - Validate query syntax."""

    def test_validate_query_valid_syntax(self, client, auth_headers):
        """Test validating valid boolean query (FR-AS-003)."""
        validate_request = {"query_syntax": 'title:visa AND content:"tier 2"'}

        response = client.post(
            "/api/v1/search/validate", json=validate_request, headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()

        assert "valid" in data
        assert data["valid"] is True
        assert "parsed_query" in data
        assert "syntax_errors" in data
        assert len(data["syntax_errors"]) == 0

    def test_validate_query_invalid_syntax(self, client, auth_headers):
        """Test validation with syntax errors."""
        validate_request = {"query_syntax": "title:visa AND OR content:tier"}  # Invalid

        response = client.post(
            "/api/v1/search/validate", json=validate_request, headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()

        assert data["valid"] is False
        assert len(data["syntax_errors"]) > 0

        # Syntax error schema validation
        error = data["syntax_errors"][0]
        assert "message" in error
        assert "position" in error

    def test_validate_query_without_execution(self, client, auth_headers):
        """Test validation doesn't execute search."""
        validate_request = {"query_syntax": "title:test"}

        response = client.post(
            "/api/v1/search/validate", json=validate_request, headers=auth_headers
        )

        assert response.status_code == 200
        # Should not include results, only validation
        assert "results" not in response.json()


class TestFieldSearch:
    """Test POST /api/v1/search/field-search - Field-specific search."""

    def test_field_search_title_contains(self, client, auth_headers):
        """Test field search with contains operator (FR-AS-002)."""
        search_request = {
            "field": "title",
            "value": "visa",
            "operator": "contains",
            "limit": 10,
            "offset": 0,
        }

        response = client.post(
            "/api/v1/search/field-search", json=search_request, headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()

        assert "results" in data
        assert "total" in data
        assert "query_time_ms" in data

    def test_field_search_equals_operator(self, client, auth_headers):
        """Test equals operator."""
        search_request = {
            "field": "category",
            "value": "Immigration",
            "operator": "equals",
            "limit": 10,
        }

        response = client.post(
            "/api/v1/search/field-search", json=search_request, headers=auth_headers
        )

        assert response.status_code == 200

    def test_field_search_starts_with_operator(self, client, auth_headers):
        """Test starts_with operator."""
        search_request = {"field": "title", "value": "UK", "operator": "starts_with", "limit": 10}

        response = client.post(
            "/api/v1/search/field-search", json=search_request, headers=auth_headers
        )

        assert response.status_code == 200

    def test_field_search_regex_operator(self, client, auth_headers):
        """Test regex operator."""
        search_request = {
            "field": "content",
            "value": "tier [0-9]",
            "operator": "regex",
            "limit": 10,
        }

        response = client.post(
            "/api/v1/search/field-search", json=search_request, headers=auth_headers
        )

        assert response.status_code == 200

    def test_field_search_invalid_field(self, client, auth_headers):
        """Test 400 with invalid field name."""
        search_request = {"field": "invalid_field", "value": "test", "operator": "contains"}

        response = client.post(
            "/api/v1/search/field-search", json=search_request, headers=auth_headers
        )

        assert response.status_code in [400, 422]


class TestSavedQueries:
    """Test saved query management endpoints."""

    def test_list_saved_queries_success(self, client, auth_headers):
        """Test GET /api/v1/search/saved-queries - List user's queries (FR-AS-004)."""
        response = client.get("/api/v1/search/saved-queries", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()

        assert "queries" in data
        assert "total" in data
        assert "page" in data
        assert "limit" in data

        # SavedQuery schema validation
        if len(data["queries"]) > 0:
            query = data["queries"][0]
            assert "id" in query
            assert "user_id" in query
            assert "query_name" in query
            assert "query_syntax" in query
            assert "created_at" in query
            assert "last_executed_at" in query or query["last_executed_at"] is None
            assert "execution_count" in query

    def test_save_query_success(self, client, auth_headers):
        """Test POST /api/v1/search/saved-queries - Save query."""
        save_request = {
            "query_name": "Active Visa Applications",
            "description": "Find all active visa applications",
            "query_syntax": "title:visa AND status:active",
            "boolean_operators": {
                "type": "AND",
                "left": {"type": "field_search", "field": "title", "value": "visa"},
                "right": {"type": "field_search", "field": "status", "value": "active"},
            },
        }

        response = client.post(
            "/api/v1/search/saved-queries", json=save_request, headers=auth_headers
        )

        assert response.status_code == 201
        query = response.json()

        assert query["query_name"] == "Active Visa Applications"
        assert query["query_syntax"] == "title:visa AND status:active"
        assert "id" in query
        assert "user_id" in query

    def test_save_query_missing_required_fields(self, client, auth_headers):
        """Test 400 when required fields missing."""
        invalid_request = {
            "query_name": "Test Query"
            # Missing query_syntax
        }

        response = client.post(
            "/api/v1/search/saved-queries", json=invalid_request, headers=auth_headers
        )

        assert response.status_code in [400, 422]

    def test_get_saved_query_success(self, client, auth_headers, sample_query_id):
        """Test GET /api/v1/search/saved-queries/{id} - Get specific query."""
        response = client.get(
            f"/api/v1/search/saved-queries/{sample_query_id}", headers=auth_headers
        )

        assert response.status_code == 200
        query = response.json()

        assert query["id"] == str(sample_query_id)
        assert "query_name" in query
        assert "query_syntax" in query

    def test_get_saved_query_not_found(self, client, auth_headers):
        """Test 404 for non-existent query."""
        fake_id = uuid4()
        response = client.get(f"/api/v1/search/saved-queries/{fake_id}", headers=auth_headers)

        assert response.status_code == 404

    def test_delete_saved_query_success(self, client, auth_headers, sample_query_id):
        """Test DELETE /api/v1/search/saved-queries/{id} - Delete query."""
        response = client.delete(
            f"/api/v1/search/saved-queries/{sample_query_id}", headers=auth_headers
        )

        assert response.status_code == 204

    def test_delete_saved_query_forbidden_not_owner(
        self, client, viewer_auth_headers, sample_query_id
    ):
        """Test 403 when non-owner tries to delete."""
        response = client.delete(
            f"/api/v1/search/saved-queries/{sample_query_id}", headers=viewer_auth_headers
        )

        assert response.status_code == 403


class TestExecuteSavedQuery:
    """Test POST /api/v1/search/saved-queries/{id}/execute - Execute saved query."""

    def test_execute_saved_query_success(self, client, auth_headers, sample_query_id):
        """Test executing saved query (FR-AS-005)."""
        execute_request = {"limit": 20, "offset": 0}

        response = client.post(
            f"/api/v1/search/saved-queries/{sample_query_id}/execute",
            json=execute_request,
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        assert "query_name" in data
        assert "query_syntax" in data
        assert "results" in data
        assert "total" in data
        assert "query_time_ms" in data

        # Validate results
        assert isinstance(data["results"], list)

    def test_execute_saved_query_with_overrides(self, client, auth_headers, sample_query_id):
        """Test executing with limit/offset overrides."""
        execute_request = {"limit": 5, "offset": 10}

        response = client.post(
            f"/api/v1/search/saved-queries/{sample_query_id}/execute",
            json=execute_request,
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) <= 5

    def test_execute_saved_query_updates_metadata(self, client, auth_headers, sample_query_id):
        """Test execution updates last_executed_at and execution_count."""
        # Execute query
        client.post(
            f"/api/v1/search/saved-queries/{sample_query_id}/execute", json={}, headers=auth_headers
        )

        # Get query metadata
        query_response = client.get(
            f"/api/v1/search/saved-queries/{sample_query_id}", headers=auth_headers
        )

        query = query_response.json()
        assert query["last_executed_at"] is not None
        assert query["execution_count"] > 0

    def test_execute_saved_query_not_found(self, client, auth_headers):
        """Test 404 for non-existent query."""
        fake_id = uuid4()
        response = client.post(
            f"/api/v1/search/saved-queries/{fake_id}/execute", json={}, headers=auth_headers
        )

        assert response.status_code == 404


# Fixtures
@pytest.fixture
def client():
    """FastAPI test client."""
    # TODO: Import actual app after implementation
    # from src.main import app
    # return TestClient(app)
    pytest.skip("Endpoints not implemented yet - TDD test must fail first")


@pytest.fixture
def auth_headers():
    """Viewer authentication headers."""
    return {"Authorization": "Bearer fake-viewer-jwt-token"}


@pytest.fixture
def viewer_auth_headers():
    """Different viewer for permission testing."""
    return {"Authorization": "Bearer fake-viewer-2-jwt-token"}


@pytest.fixture
def sample_query_id():
    """Sample saved query UUID for testing."""
    return uuid4()
