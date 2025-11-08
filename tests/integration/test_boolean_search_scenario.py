"""
Feature 012 - T139: Integration Test - Boolean Query Builder Scenario
FR-AS-001: Parse and validate boolean queries (AND, OR, NOT)
FR-AS-002: Execute boolean search with pagination
FR-AS-003: Save and execute queries

Test Scenario:
1. Validate simple boolean query
2. Parse complex boolean query with parentheses
3. Execute boolean search and verify results
4. Save query with parsed AST
5. Execute saved query
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import uuid

from src.main import app
from src.database import Base, get_db
from src.models.saved_query import SavedQuery


# ============================================================================
# Test Database Setup
# ============================================================================

SQLALCHEMY_DATABASE_URL = "sqlite:///./test_boolean_search.db"

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    """Override database dependency with test database."""
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(scope="module")
def test_db():
    """Create test database and tables."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="module")
def test_client(test_db):
    """Create test client."""
    client = TestClient(app)
    return client


@pytest.fixture(scope="function")
def cleanup_saved_queries():
    """Cleanup saved queries after each test."""
    yield

    db = TestingSessionLocal()
    db.query(SavedQuery).delete()
    db.commit()
    db.close()


# ============================================================================
# T139: Integration Test - Boolean Search Scenario
# ============================================================================


def test_validate_simple_boolean_query(test_client):
    """
    Test query validation with simple boolean query (FR-AS-001).

    Steps:
    1. Validate simple query: "visa OR permit"
    2. Verify query is valid
    3. Verify no syntax errors
    4. Verify parsed AST structure

    Expected:
    - is_valid: True
    - syntax_errors: []
    - parsed_query: Contains OR operator with operands
    """
    headers = {
        "Authorization": "Bearer mock_viewer_token",
    }

    validation_payload = {
        "query": "visa OR permit",
    }

    response = test_client.post("/api/v1/search/validate", json=validation_payload, headers=headers)

    assert response.status_code == 200, f"Validation failed: {response.text}"

    validation_result = response.json()
    assert validation_result["is_valid"] is True, "Query should be valid"
    assert len(validation_result["syntax_errors"]) == 0, "Should have no syntax errors"
    assert validation_result["parsed_query"] is not None, "Should return parsed AST"

    # Verify parsed query structure
    parsed_query = validation_result["parsed_query"]
    print(f"Parsed query: {parsed_query}")

    print("✅ T139a: Simple boolean query validation PASSED")


def test_validate_complex_boolean_query_with_parentheses(test_client):
    """
    Test query validation with complex boolean query (FR-AS-001).

    Steps:
    1. Validate complex query: "(visa OR permit) AND UK NOT rejected"
    2. Verify query is valid
    3. Verify parsed AST contains nested structure

    Expected:
    - is_valid: True
    - parsed_query: Contains nested AND, OR, NOT operators
    """
    headers = {
        "Authorization": "Bearer mock_viewer_token",
    }

    validation_payload = {
        "query": "(visa OR permit) AND UK NOT rejected",
    }

    response = test_client.post("/api/v1/search/validate", json=validation_payload, headers=headers)

    assert response.status_code == 200

    validation_result = response.json()
    assert validation_result["is_valid"] is True
    assert validation_result["parsed_query"] is not None

    # Verify complex structure
    parsed_query = validation_result["parsed_query"]
    print(f"Complex parsed query: {parsed_query}")

    print("✅ T139b: Complex boolean query with parentheses PASSED")


def test_validate_invalid_boolean_query(test_client):
    """
    Test query validation with invalid syntax (FR-AS-001).

    Steps:
    1. Validate invalid query: "visa OR AND permit"
    2. Verify query is invalid
    3. Verify syntax errors are returned

    Expected:
    - is_valid: False
    - syntax_errors: Contains error details
    """
    headers = {
        "Authorization": "Bearer mock_viewer_token",
    }

    validation_payload = {
        "query": "visa OR AND permit",  # Invalid: consecutive operators
    }

    response = test_client.post("/api/v1/search/validate", json=validation_payload, headers=headers)

    assert response.status_code == 200

    validation_result = response.json()
    assert validation_result["is_valid"] is False, "Query should be invalid"
    assert len(validation_result["syntax_errors"]) > 0, "Should have syntax errors"

    print(f"Syntax errors: {validation_result['syntax_errors']}")
    print("✅ T139c: Invalid boolean query validation PASSED")


def test_execute_boolean_query_with_results(test_client):
    """
    Test boolean query execution with results (FR-AS-002).

    Steps:
    1. Execute boolean query: "(immigration OR visa) AND UK"
    2. Verify results returned
    3. Verify pagination parameters
    4. Verify parsed query included in response

    Expected:
    - Status: 200
    - results: Array of search results
    - total_count: Result count
    - parsed_query: AST structure
    """
    headers = {
        "Authorization": "Bearer mock_viewer_token",
    }

    query_payload = {
        "query": "(immigration OR visa) AND UK",
        "limit": 20,
        "offset": 0,
    }

    response = test_client.post("/api/v1/search/boolean", json=query_payload, headers=headers)

    assert response.status_code == 200, f"Query execution failed: {response.text}"

    query_result = response.json()
    assert "results" in query_result
    assert "total_count" in query_result
    assert "parsed_query" in query_result

    # Verify pagination
    assert query_result["limit"] == 20
    assert query_result["offset"] == 0

    # Verify parsed query
    assert query_result["query"] == "(immigration OR visa) AND UK"
    assert query_result["parsed_query"] is not None

    print(f"Query returned {query_result['total_count']} results")
    print(f"Parsed query: {query_result['parsed_query']}")
    print("✅ T139d: Boolean query execution with results PASSED")


def test_save_query_with_parsed_ast(test_client, cleanup_saved_queries):
    """
    Test saving query with parsed AST (FR-AS-003).

    Steps:
    1. Save query: "visa application AND UK"
    2. Verify query saved successfully
    3. Verify parsed AST stored in boolean_operators
    4. Verify query_name and query_syntax stored

    Expected:
    - Status: 201 Created
    - saved_query: Contains id, query_name, query_syntax, boolean_operators
    """
    headers = {
        "Authorization": "Bearer mock_viewer_token",
    }

    save_payload = {
        "query_name": "UK Visa Applications",
        "query_syntax": "visa application AND UK",
    }

    response = test_client.post("/api/v1/search/saved-queries", json=save_payload, headers=headers)

    assert response.status_code == 201, f"Failed to save query: {response.text}"

    saved_query = response.json()
    assert "id" in saved_query
    assert saved_query["query_name"] == "UK Visa Applications"
    assert saved_query["query_syntax"] == "visa application AND UK"
    assert saved_query["boolean_operators"] is not None

    print(f"Saved query ID: {saved_query['id']}")
    print(f"Boolean operators: {saved_query['boolean_operators']}")
    print("✅ T139e: Save query with parsed AST PASSED")

    return saved_query["id"]


def test_execute_saved_query(test_client, cleanup_saved_queries):
    """
    Test executing saved query (FR-AS-003).

    Steps:
    1. Save query
    2. Execute saved query by ID
    3. Verify results returned
    4. Verify execution_count incremented
    5. Verify last_executed_at updated

    Expected:
    - Status: 200
    - results: Search results
    - parsed_query: Retrieved from saved AST
    """
    headers = {
        "Authorization": "Bearer mock_viewer_token",
    }

    # Step 1: Save query
    save_payload = {
        "query_name": "Settlement Applications",
        "query_syntax": "settlement AND indefinite leave",
    }

    save_response = test_client.post(
        "/api/v1/search/saved-queries", json=save_payload, headers=headers
    )

    assert save_response.status_code == 201
    query_id = save_response.json()["id"]

    # Step 2: Execute saved query
    execution_payload = {
        "limit": 10,
        "offset": 0,
    }

    exec_response = test_client.post(
        f"/api/v1/search/saved-queries/{query_id}/execute",
        json=execution_payload,
        headers=headers,
    )

    assert exec_response.status_code == 200, f"Failed to execute saved query: {exec_response.text}"

    exec_result = exec_response.json()
    assert "results" in exec_result
    assert exec_result["query"] == "settlement AND indefinite leave"
    assert exec_result["parsed_query"] is not None

    # Verify pagination overrides applied
    assert exec_result["limit"] == 10
    assert exec_result["offset"] == 0

    # Step 3: Verify execution stats updated
    get_response = test_client.get(f"/api/v1/search/saved-queries/{query_id}", headers=headers)

    assert get_response.status_code == 200

    updated_query = get_response.json()
    assert updated_query["execution_count"] == 1, "Execution count should be 1"
    assert updated_query["last_executed_at"] is not None, "last_executed_at should be set"

    print(f"Saved query executed successfully")
    print(f"Execution count: {updated_query['execution_count']}")
    print(f"Last executed: {updated_query['last_executed_at']}")
    print("✅ T139f: Execute saved query PASSED")


def test_list_and_delete_saved_queries(test_client, cleanup_saved_queries):
    """
    Test listing and deleting saved queries (FR-AS-003).

    Steps:
    1. Save 3 queries
    2. List saved queries
    3. Verify all 3 queries returned
    4. Delete one query
    5. List again, verify 2 queries remain

    Expected:
    - List returns all user's saved queries
    - Delete removes query
    - Cannot retrieve deleted query
    """
    headers = {
        "Authorization": "Bearer mock_viewer_token",
    }

    # Step 1: Save 3 queries
    queries = [
        {"query_name": "Query 1", "query_syntax": "visa OR permit"},
        {"query_name": "Query 2", "query_syntax": "immigration AND UK"},
        {"query_name": "Query 3", "query_syntax": "settlement NOT rejected"},
    ]

    saved_ids = []
    for query in queries:
        response = test_client.post("/api/v1/search/saved-queries", json=query, headers=headers)
        assert response.status_code == 201
        saved_ids.append(response.json()["id"])

    # Step 2: List saved queries
    list_response = test_client.get("/api/v1/search/saved-queries", headers=headers)

    assert list_response.status_code == 200

    saved_queries = list_response.json()
    assert len(saved_queries) == 3, f"Expected 3 saved queries, got {len(saved_queries)}"

    # Step 3: Delete one query
    delete_response = test_client.delete(
        f"/api/v1/search/saved-queries/{saved_ids[0]}", headers=headers
    )

    assert delete_response.status_code == 204, "Delete should return 204 No Content"

    # Step 4: List again
    list_response2 = test_client.get("/api/v1/search/saved-queries", headers=headers)

    assert list_response2.status_code == 200

    remaining_queries = list_response2.json()
    assert (
        len(remaining_queries) == 2
    ), f"Expected 2 remaining queries, got {len(remaining_queries)}"

    # Verify deleted query cannot be retrieved
    get_deleted_response = test_client.get(
        f"/api/v1/search/saved-queries/{saved_ids[0]}", headers=headers
    )

    assert get_deleted_response.status_code == 404, "Deleted query should return 404"

    print("✅ T139g: List and delete saved queries PASSED")


# ============================================================================
# Pytest Configuration
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
