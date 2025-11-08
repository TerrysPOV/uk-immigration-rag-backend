"""
Contract tests for Analytics Dashboard API.

Tests all 7 REST endpoints from contracts/analytics-api.yaml:
1. GET /api/v1/analytics/search-volume
2. GET /api/v1/analytics/top-queries
3. GET /api/v1/analytics/response-times
4. GET /api/v1/analytics/error-rates
5. GET /api/v1/analytics/resource-usage
6. GET /api/v1/analytics/alerts
7. POST /api/v1/analytics/export

These tests MUST FAIL before implementation (TDD).
"""

import pytest
from fastapi.testclient import TestClient
from datetime import datetime
import io


class TestSearchVolumeMetrics:
    """Test GET /api/v1/analytics/search-volume - Time-series search volume."""

    def test_get_search_volume_24h(self, client, auth_headers):
        """Test search volume for 24-hour period with hourly granularity."""
        response = client.get(
            "/api/v1/analytics/search-volume",
            params={"period": "24h", "granularity": "hour"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        assert "period" in data
        assert data["period"] == "24h"
        assert "data" in data
        assert isinstance(data["data"], list)

        # Validate data points
        if len(data["data"]) > 0:
            point = data["data"][0]
            assert "timestamp" in point
            assert "search_count" in point
            assert "unique_users" in point
            assert isinstance(point["search_count"], int)
            assert isinstance(point["unique_users"], int)

    def test_get_search_volume_7d_daily(self, client, auth_headers):
        """Test 7-day period with daily granularity."""
        response = client.get(
            "/api/v1/analytics/search-volume",
            params={"period": "7d", "granularity": "day"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["period"] == "7d"

    def test_get_search_volume_missing_period(self, client, auth_headers):
        """Test 400 when period parameter missing."""
        response = client.get("/api/v1/analytics/search-volume", headers=auth_headers)

        # Should return 422 (validation error) or 400
        assert response.status_code in [400, 422]

    def test_get_search_volume_unauthorized(self, client):
        """Test 401 without authentication."""
        response = client.get("/api/v1/analytics/search-volume", params={"period": "24h"})
        assert response.status_code == 401


class TestTopQueries:
    """Test GET /api/v1/analytics/top-queries - Most frequent queries."""

    def test_get_top_queries_default_limit(self, client, auth_headers):
        """Test top queries with default limit of 20."""
        response = client.get(
            "/api/v1/analytics/top-queries", params={"period": "7d"}, headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()

        assert "period" in data
        assert "queries" in data
        assert isinstance(data["queries"], list)
        assert len(data["queries"]) <= 20

        # Validate query schema
        if len(data["queries"]) > 0:
            query = data["queries"][0]
            assert "query_text" in query
            assert "count" in query
            assert "avg_response_time_ms" in query
            assert "avg_relevance_score" in query
            assert isinstance(query["count"], int)
            assert isinstance(query["avg_response_time_ms"], (int, float))
            assert isinstance(query["avg_relevance_score"], (int, float))

    def test_get_top_queries_custom_limit(self, client, auth_headers):
        """Test custom limit parameter."""
        response = client.get(
            "/api/v1/analytics/top-queries",
            params={"period": "30d", "limit": 10},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["queries"]) <= 10

    def test_get_top_queries_ordered_by_count(self, client, auth_headers):
        """Test queries are ordered by count descending."""
        response = client.get(
            "/api/v1/analytics/top-queries", params={"period": "7d"}, headers=auth_headers
        )

        assert response.status_code == 200
        queries = response.json()["queries"]

        # Verify descending order
        if len(queries) > 1:
            for i in range(len(queries) - 1):
                assert queries[i]["count"] >= queries[i + 1]["count"]


class TestResponseTimes:
    """Test GET /api/v1/analytics/response-times - Response time percentiles."""

    def test_get_response_times_all_query_types(self, client, auth_headers):
        """Test response times without query_type filter."""
        response = client.get(
            "/api/v1/analytics/response-times", params={"period": "7d"}, headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()

        assert "period" in data
        assert "data" in data
        assert isinstance(data["data"], list)

        # Validate percentile data
        if len(data["data"]) > 0:
            point = data["data"][0]
            assert "timestamp" in point
            assert "query_type" in point
            assert "avg_response_time_ms" in point
            assert "p50_ms" in point
            assert "p95_ms" in point
            assert "p99_ms" in point

            # Validate query_type enum
            assert point["query_type"] in ["semantic", "hybrid", "keyword"]

            # Validate percentile ordering: p50 <= p95 <= p99
            assert point["p50_ms"] <= point["p95_ms"]
            assert point["p95_ms"] <= point["p99_ms"]

    def test_get_response_times_semantic_only(self, client, auth_headers):
        """Test filtering by semantic query type."""
        response = client.get(
            "/api/v1/analytics/response-times",
            params={"period": "24h", "query_type": "semantic"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()["data"]

        # All data points should be semantic type
        for point in data:
            assert point["query_type"] == "semantic"


class TestErrorRates:
    """Test GET /api/v1/analytics/error-rates - Error rate time-series."""

    def test_get_error_rates_success(self, client, auth_headers):
        """Test error rate retrieval."""
        response = client.get(
            "/api/v1/analytics/error-rates", params={"period": "7d"}, headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()

        assert "period" in data
        assert "data" in data

        # Validate error rate schema
        if len(data["data"]) > 0:
            point = data["data"][0]
            assert "timestamp" in point
            assert "total_requests" in point
            assert "error_count" in point
            assert "error_rate_percent" in point
            assert "error_types" in point

            # Validate error rate calculation
            if point["total_requests"] > 0:
                expected_rate = (point["error_count"] / point["total_requests"]) * 100
                assert abs(point["error_rate_percent"] - expected_rate) < 0.01

            # Validate error types breakdown
            error_types = point["error_types"]
            assert "timeout" in error_types
            assert "server_error" in error_types
            assert "not_found" in error_types

    def test_error_rate_5min_windows(self, client, auth_headers):
        """Test error rates calculated over 5-minute windows."""
        response = client.get(
            "/api/v1/analytics/error-rates", params={"period": "24h"}, headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()["data"]

        # Verify data points are in 5-minute intervals
        if len(data) > 1:
            t1 = datetime.fromisoformat(data[0]["timestamp"].replace("Z", "+00:00"))
            t2 = datetime.fromisoformat(data[1]["timestamp"].replace("Z", "+00:00"))
            diff_seconds = abs((t2 - t1).total_seconds())
            assert diff_seconds == 300  # 5 minutes


class TestResourceUsage:
    """Test GET /api/v1/analytics/resource-usage - Real-time resource metrics."""

    def test_get_resource_usage_success(self, client, auth_headers):
        """Test real-time resource usage retrieval."""
        response = client.get("/api/v1/analytics/resource-usage", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()

        # Validate schema
        assert "timestamp" in data
        assert "cpu_usage_percent" in data
        assert "memory_usage_percent" in data
        assert "storage_usage_percent" in data
        assert "database_connections" in data
        assert "active_websocket_connections" in data

        # Validate ranges
        assert 0 <= data["cpu_usage_percent"] <= 100
        assert 0 <= data["memory_usage_percent"] <= 100
        assert 0 <= data["storage_usage_percent"] <= 100

        # Validate database connections
        db_conn = data["database_connections"]
        assert "active" in db_conn
        assert "idle" in db_conn
        assert "max" in db_conn
        assert db_conn["active"] + db_conn["idle"] <= db_conn["max"]

        # Validate WebSocket connections
        assert isinstance(data["active_websocket_connections"], int)
        assert data["active_websocket_connections"] >= 0


class TestAlerts:
    """Test GET /api/v1/analytics/alerts - Active threshold breach alerts."""

    def test_get_alerts_success(self, client, auth_headers):
        """Test retrieving active alerts."""
        response = client.get("/api/v1/analytics/alerts", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()

        assert "alerts" in data
        assert isinstance(data["alerts"], list)

        # Validate Alert schema
        if len(data["alerts"]) > 0:
            alert = data["alerts"][0]
            assert "alert_id" in alert
            assert "metric_name" in alert
            assert "severity" in alert
            assert "threshold" in alert
            assert "current_value" in alert
            assert "triggered_at" in alert

            # Validate severity enum
            assert alert["severity"] in ["WARNING", "CRITICAL"]

            # Validate metric_name enum
            assert alert["metric_name"] in [
                "error_rate",
                "response_time",
                "cpu_usage",
                "memory_usage",
                "storage_usage",
                "database_connections",
            ]

            # Validate threshold breach
            assert alert["current_value"] >= alert["threshold"]

    def test_alerts_threshold_logic(self, client, auth_headers):
        """Test alert thresholds match specification."""
        response = client.get("/api/v1/analytics/alerts", headers=auth_headers)

        assert response.status_code == 200
        alerts = response.json()["alerts"]

        for alert in alerts:
            # Error rate thresholds: ≥5% WARNING, ≥15% CRITICAL
            if alert["metric_name"] == "error_rate":
                if alert["severity"] == "WARNING":
                    assert 5 <= alert["current_value"] < 15
                elif alert["severity"] == "CRITICAL":
                    assert alert["current_value"] >= 15


class TestExportAnalytics:
    """Test POST /api/v1/analytics/export - Export metrics to CSV/JSON."""

    def test_export_csv_success(self, client, auth_headers):
        """Test exporting metrics to CSV format."""
        export_request = {
            "metric_types": ["search_volume", "top_queries"],
            "period": "7d",
            "format": "csv",
        }

        response = client.post(
            "/api/v1/analytics/export", json=export_request, headers=auth_headers
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/csv"

        # Validate CSV content
        content = response.content.decode("utf-8")
        assert len(content) > 0
        # CSV should have header row
        lines = content.split("\n")
        assert len(lines) > 1

    def test_export_json_success(self, client, auth_headers):
        """Test exporting metrics to JSON format."""
        export_request = {
            "metric_types": ["response_times", "error_rates"],
            "period": "30d",
            "format": "json",
        }

        response = client.post(
            "/api/v1/analytics/export", json=export_request, headers=auth_headers
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/json"

        data = response.json()
        assert isinstance(data, (dict, list))

    def test_export_all_metric_types(self, client, auth_headers):
        """Test exporting all available metric types."""
        export_request = {
            "metric_types": [
                "search_volume",
                "top_queries",
                "response_times",
                "error_rates",
                "resource_usage",
            ],
            "period": "24h",
            "format": "json",
        }

        response = client.post(
            "/api/v1/analytics/export", json=export_request, headers=auth_headers
        )

        assert response.status_code == 200

    def test_export_missing_required_fields(self, client, auth_headers):
        """Test 400 when required fields missing."""
        invalid_request = {
            "period": "7d",
            "format": "csv",
            # Missing metric_types
        }

        response = client.post(
            "/api/v1/analytics/export", json=invalid_request, headers=auth_headers
        )

        assert response.status_code in [400, 422]

    def test_export_invalid_format(self, client, auth_headers):
        """Test 400 with invalid export format."""
        invalid_request = {
            "metric_types": ["search_volume"],
            "period": "7d",
            "format": "xml",  # Not supported
        }

        response = client.post(
            "/api/v1/analytics/export", json=invalid_request, headers=auth_headers
        )

        assert response.status_code in [400, 422]


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
    """Admin authentication headers."""
    return {"Authorization": "Bearer fake-admin-jwt-token"}
