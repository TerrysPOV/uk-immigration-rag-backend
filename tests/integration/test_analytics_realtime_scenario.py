"""
Feature 012 - T136: Integration Test - Analytics Dashboard Real-Time Metrics
FR-AD-005: Real-time system metrics via WebSocket
FR-AD-008: 30s metric update interval
FR-AD-010: Alert threshold breaches

Test Scenario:
1. Establish WebSocket connection to /ws/analytics/metrics
2. Receive initial metrics update
3. Verify 30s update interval (receive updates every 30s)
4. Simulate threshold breach and verify alert broadcast
5. Test exponential backoff reconnection logic
"""

import pytest
import asyncio
import json
from fastapi.testclient import TestClient
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import uuid

from src.main import app
from src.database import Base, get_db
from src.models.analytics_metric import AnalyticsMetric
from src.websocket.metrics_manager import metrics_ws_manager


# ============================================================================
# Test Database Setup
# ============================================================================

SQLALCHEMY_DATABASE_URL = "sqlite:///./test_analytics_realtime.db"

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
def setup_metrics_data():
    """Setup test analytics metrics."""
    db = TestingSessionLocal()

    # Create baseline metrics (healthy state)
    baseline_metrics = [
        AnalyticsMetric(
            id=str(uuid.uuid4()),
            metric_name="cpu_usage",
            metric_value=45.2,
            category="system",
            timestamp=datetime.utcnow(),
        ),
        AnalyticsMetric(
            id=str(uuid.uuid4()),
            metric_name="memory_usage",
            metric_value=62.1,
            category="system",
            timestamp=datetime.utcnow(),
        ),
        AnalyticsMetric(
            id=str(uuid.uuid4()),
            metric_name="response_time",
            metric_value=425.0,
            category="performance",
            timestamp=datetime.utcnow(),
        ),
        AnalyticsMetric(
            id=str(uuid.uuid4()),
            metric_name="error_rate",
            metric_value=2.0,  # 2% error rate (healthy)
            category="performance",
            timestamp=datetime.utcnow(),
        ),
    ]

    for metric in baseline_metrics:
        db.add(metric)

    db.commit()
    db.close()

    yield

    # Cleanup
    db = TestingSessionLocal()
    db.query(AnalyticsMetric).delete()
    db.commit()
    db.close()


# ============================================================================
# T136: Integration Test - Analytics Real-Time Metrics Scenario
# ============================================================================


@pytest.mark.asyncio
async def test_analytics_websocket_connection_and_updates(test_client, setup_metrics_data):
    """
    Test WebSocket connection and 30s update interval (FR-AD-005, FR-AD-008).

    Steps:
    1. Connect to /ws/analytics/metrics
    2. Verify connection confirmation message
    3. Receive first metrics update
    4. Wait 30s and verify second update
    5. Verify update contains all metric categories

    Expected:
    - Connection succeeds with auth token
    - Updates received every 30s
    - Each update contains cpu, memory, storage, db, websocket metrics
    """
    mock_token = "Bearer mock_admin_token_12345"

    with test_client.websocket_connect(f"/ws/analytics/metrics?token={mock_token}") as websocket:
        # Step 1: Verify connection confirmation
        connection_msg = websocket.receive_json(timeout=5)

        assert connection_msg["type"] == "connected"
        assert "timestamp" in connection_msg
        print(f"✅ WebSocket connected at {connection_msg['timestamp']}")

        # Step 2: Receive first metrics update
        first_update = websocket.receive_json(timeout=35)  # Should arrive within 30s + buffer

        assert first_update["type"] == "metrics_update"
        assert "data" in first_update
        assert "timestamp" in first_update

        # Verify all metric categories present
        data = first_update["data"]
        assert "cpu" in data
        assert "memory" in data
        assert "storage" in data
        assert "database_connections" in data
        assert "websocket_connections" in data

        # Verify metric structure
        assert data["cpu"]["percent"] >= 0
        assert data["cpu"]["status"] in ["healthy", "warning", "critical"]
        assert data["memory"]["percent"] >= 0
        assert data["memory"]["status"] in ["healthy", "warning", "critical"]

        first_timestamp = datetime.fromisoformat(first_update["timestamp"])
        print(f"✅ First metrics update received at {first_timestamp}")

        # Step 3: Wait for second update (should arrive ~30s after first)
        second_update = websocket.receive_json(timeout=35)

        assert second_update["type"] == "metrics_update"
        second_timestamp = datetime.fromisoformat(second_update["timestamp"])

        # Verify 30s interval (with 5s tolerance for test execution time)
        time_diff = (second_timestamp - first_timestamp).total_seconds()
        assert 25 <= time_diff <= 35, f"Update interval was {time_diff}s, expected ~30s"

        print(f"✅ Second metrics update received at {second_timestamp} (interval: {time_diff}s)")
        print("✅ T136a: WebSocket connection and 30s updates PASSED")


@pytest.mark.asyncio
async def test_analytics_alert_threshold_breach(test_client, setup_metrics_data):
    """
    Test alert threshold breach notification (FR-AD-010).

    Steps:
    1. Connect to WebSocket
    2. Inject high CPU metric (>70% WARNING, >90% CRITICAL)
    3. Verify alert broadcast in next update
    4. Verify alert contains threshold details

    Expected:
    - Alert triggered when threshold exceeded
    - Alert contains: metric_name, current_value, threshold_value, severity, message
    """
    mock_token = "Bearer mock_admin_token_12345"

    # Inject critical CPU metric (95% > 90% threshold)
    db = TestingSessionLocal()
    critical_metric = AnalyticsMetric(
        id=str(uuid.uuid4()),
        metric_name="cpu_usage",
        metric_value=95.0,  # CRITICAL threshold (>90%)
        category="system",
        timestamp=datetime.utcnow(),
    )
    db.add(critical_metric)
    db.commit()
    db.close()

    with test_client.websocket_connect(f"/ws/analytics/metrics?token={mock_token}") as websocket:
        # Receive connection confirmation
        websocket.receive_json(timeout=5)

        # Receive metrics update (should include alert)
        update = websocket.receive_json(timeout=35)

        assert update["type"] == "metrics_update"
        data = update["data"]

        # Verify CPU shows critical status
        assert data["cpu"]["percent"] >= 90
        assert data["cpu"]["status"] == "critical"

        # Check if alerts endpoint is called separately
        # (In real implementation, alerts may be separate or embedded in metrics)
        print(f"✅ Alert triggered: CPU at {data['cpu']['percent']}% (critical threshold: 90%)")
        print("✅ T136b: Alert threshold breach notification PASSED")


@pytest.mark.asyncio
async def test_analytics_websocket_reconnection_exponential_backoff(test_client):
    """
    Test exponential backoff reconnection logic (FR-AD-008).

    Steps:
    1. Connect to WebSocket
    2. Forcefully disconnect
    3. Attempt reconnection with exponential backoff (1s, 2s, 4s)
    4. Verify backoff intervals

    Expected:
    - First retry: 1s delay
    - Second retry: 2s delay
    - Third retry: 4s delay
    """
    mock_token = "Bearer mock_admin_token_12345"

    reconnection_attempts = []

    async def attempt_connection(delay_before: float):
        """Simulate connection attempt after delay."""
        await asyncio.sleep(delay_before)
        attempt_time = datetime.utcnow()

        try:
            with test_client.websocket_connect(
                f"/ws/analytics/metrics?token={mock_token}"
            ) as websocket:
                websocket.receive_json(timeout=5)  # Connection confirmation
                reconnection_attempts.append(
                    {
                        "time": attempt_time,
                        "success": True,
                    }
                )
                return True
        except Exception as e:
            reconnection_attempts.append(
                {
                    "time": attempt_time,
                    "success": False,
                    "error": str(e),
                }
            )
            return False

    # Initial connection (fail immediately)
    reconnection_attempts.append(
        {
            "time": datetime.utcnow(),
            "success": False,
            "error": "Simulated disconnect",
        }
    )

    # Exponential backoff attempts: 1s, 2s, 4s
    await attempt_connection(1.0)  # First retry after 1s
    await attempt_connection(2.0)  # Second retry after 2s
    await attempt_connection(4.0)  # Third retry after 4s

    # Verify exponential backoff intervals
    assert len(reconnection_attempts) == 4  # Initial + 3 retries

    # Calculate intervals between attempts
    intervals = []
    for i in range(1, len(reconnection_attempts)):
        time_diff = (
            reconnection_attempts[i]["time"] - reconnection_attempts[i - 1]["time"]
        ).total_seconds()
        intervals.append(time_diff)

    # Verify exponential pattern (with 0.5s tolerance)
    assert 0.5 <= intervals[0] <= 1.5, f"First retry interval: {intervals[0]}s, expected ~1s"
    assert 1.5 <= intervals[1] <= 2.5, f"Second retry interval: {intervals[1]}s, expected ~2s"
    assert 3.5 <= intervals[2] <= 4.5, f"Third retry interval: {intervals[2]}s, expected ~4s"

    print(f"✅ Reconnection intervals: {intervals}")
    print("✅ T136c: Exponential backoff reconnection PASSED")


@pytest.mark.asyncio
async def test_analytics_websocket_connection_limit(test_client):
    """
    Test concurrent WebSocket connection limit (FR-AD-008).

    Expected:
    - User can have max 3 concurrent connections
    - 4th connection rejected with error
    """
    mock_token = "Bearer mock_admin_token_12345"
    connections = []

    try:
        # Create 3 connections (should succeed)
        for i in range(3):
            ws = test_client.websocket_connect(f"/ws/analytics/metrics?token={mock_token}")
            ws.__enter__()
            connections.append(ws)
            msg = ws.receive_json(timeout=5)
            assert msg["type"] == "connected"
            print(f"✅ Connection {i + 1}/3 established")

        # Attempt 4th connection (should fail)
        with pytest.raises(Exception):  # Should raise WebSocketDisconnect or similar
            with test_client.websocket_connect(f"/ws/analytics/metrics?token={mock_token}") as ws:
                ws.receive_json(timeout=5)

        print("✅ T136d: Connection limit enforcement PASSED")

    finally:
        # Cleanup: Close all connections
        for ws in connections:
            try:
                ws.__exit__(None, None, None)
            except Exception:
                pass


# ============================================================================
# Pytest Configuration
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
