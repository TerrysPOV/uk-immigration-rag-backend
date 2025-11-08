"""
Contract test for POST /api/rag/query endpoint.
Validates request/response schemas match actual API implementation.
Uses actual running API instance (localhost:8000).
"""
import pytest
import requests

API_BASE_URL = "http://localhost:8000"

def test_rag_query_endpoint_exists():
    """Test that /api/rag/query endpoint is accessible."""
    response = requests.post(
        f"{API_BASE_URL}/api/rag/query",
        json={"query": "test", "top_k": 5},
        timeout=10
    )
    
    # Should return 200 (success) or 401 (auth required)
    assert response.status_code in [200, 401], f"Unexpected status: {response.status_code}"

def test_rag_query_response_schema():
    """Test that successful response matches expected schema."""
    response = requests.post(
        f"{API_BASE_URL}/api/rag/query",
        json={"query": "How do I apply for a Skilled Worker visa?", "top_k": 3},
        timeout=15
    )
    
    if response.status_code == 200:
        data = response.json()
        
        # Assert top-level fields exist
        assert "results" in data, "Missing 'results' field"
        
        # Assert results is array
        assert isinstance(data["results"], list), "'results' must be array"
        
        # Pipeline metadata should be at top level
        assert "hybrid_search_used" in data or "query_preprocessed" in data or "reranking_used" in data,             "Missing pipeline metadata fields"
        
        # If results present, validate first result schema
        if len(data["results"]) > 0:
            result = data["results"][0]
            # Each result has embedded metadata
            assert "metadata" in result or "document_id" in result or "title" in result,                 "Missing result fields"
    elif response.status_code == 401:
        pytest.skip("Authentication required - endpoint protected")
    else:
        pytest.fail(f"Unexpected status code: {response.status_code}")

def test_rag_query_invalid_request():
    """Test that invalid request returns 400/422."""
    response = requests.post(
        f"{API_BASE_URL}/api/rag/query",
        json={"query": "", "top_k": 5},  # Empty query
        timeout=10
    )
    
    # Should return 400/422 for validation error, or 401 if auth required first
    assert response.status_code in [400, 401, 422], f"Expected 400/401/422, got {response.status_code}"

def test_rag_query_top_k_validation():
    """Test that top_k parameter is validated."""
    response = requests.post(
        f"{API_BASE_URL}/api/rag/query",
        json={"query": "test query", "top_k": 100},  # Should be capped at 50
        timeout=15
    )
    
    # Should either accept and cap, reject, or require auth
    assert response.status_code in [200, 400, 401, 422], f"Unexpected status: {response.status_code}"
    
    if response.status_code == 200:
        data = response.json()
        # Results should be capped
        assert len(data["results"]) <= 50, "Results exceed maximum"
