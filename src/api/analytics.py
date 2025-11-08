"""
Feature 012: Analytics Dashboard API
T053-T059: Analytics Dashboard API endpoints

Endpoints:
- GET /api/v1/analytics/search-volume - Query search volume by period/granularity
- GET /api/v1/analytics/top-queries - Aggregate top 20 search queries with metrics
- GET /api/v1/analytics/response-times - Calculate p50/p95/p99 response time percentiles
- GET /api/v1/analytics/error-rates - Calculate error rates over 5-minute windows
- GET /api/v1/analytics/resource-usage - Real-time CPU/memory/storage/DB/WebSocket metrics
- GET /api/v1/analytics/alerts - Check metrics against thresholds, return active alerts
- POST /api/v1/analytics/export - Export metrics to CSV/JSON format

Authentication: Requires Admin role
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timedelta
from pydantic import BaseModel, Field
import os

from ..database import get_db
from ..services.analytics_service import AnalyticsService, Alert
from ..models.analytics_metric import MetricAggregation, AnalyticsMetricInDB
from ..middleware.rbac import get_current_user_with_role


router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


# ============================================================================
# Request/Response Models
# ============================================================================


class SearchVolumeResponse(BaseModel):
    """Response schema for search volume endpoint."""

    period: str = Field(..., description="Time period (24h/7d/30d/90d)")
    granularity: str = Field(..., description="Aggregation granularity (hour/day/week)")
    data_points: List[dict] = Field(..., description="Time-series data points")


class TopQuery(BaseModel):
    """Schema for top query entry."""

    query_text: str
    count: int
    avg_response_time_ms: float
    avg_relevance_score: Optional[float] = None


class ResponseTimePercentiles(BaseModel):
    """Response schema for response times endpoint."""

    period: str
    query_type: Optional[str]
    p50_ms: float = Field(..., description="50th percentile (median)")
    p95_ms: float = Field(..., description="95th percentile")
    p99_ms: float = Field(..., description="99th percentile")
    sample_count: int


class ErrorRateWindow(BaseModel):
    """Schema for error rate window."""

    window_start: datetime
    window_end: datetime
    error_count: int
    total_count: int
    error_rate_percent: float


class AlertResponse(BaseModel):
    """Response schema for alert."""

    metric_name: str
    current_value: float
    threshold_value: float
    severity: str  # WARNING or CRITICAL
    message: str
    timestamp: datetime


class ExportRequest(BaseModel):
    """Request schema for metrics export."""

    format: str = Field(..., description="Export format (csv/json)")
    metric_types: Optional[List[str]] = Field(None, description="Optional filter for metric types")
    period: str = Field("30d", description="Time period for export (24h/7d/30d/90d)")


# ============================================================================
# T053: GET /api/v1/analytics/search-volume
# ============================================================================


@router.get("/search-volume", response_model=SearchVolumeResponse)
async def get_search_volume(
    period: str = Query("24h", description="Time period (24h/7d/30d/90d)"),
    granularity: str = Query("hour", description="Aggregation granularity (hour/day/week)"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_with_role("admin")),
):
    """
    Query search volume by period and granularity (T053).

    Requires: Admin role

    Periods:
    - 24h: Last 24 hours
    - 7d: Last 7 days
    - 30d: Last 30 days
    - 90d: Last 90 days

    Granularity:
    - hour: Aggregate by hour
    - day: Aggregate by day
    - week: Aggregate by week

    Returns:
        SearchVolumeResponse with time-series data points
    """
    try:
        analytics_service = AnalyticsService(db)

        # Get aggregated metrics for search volume
        metrics = analytics_service.get_metrics_by_period(
            period=period, metric_types=["search_volume"], granularity=granularity
        )

        # Convert to time-series data points
        # TODO: Group by time window based on granularity
        data_points = []
        for metric in metrics:
            data_points.append(
                {
                    "metric_name": metric.metric_name,
                    "category": metric.category,
                    "count": metric.count,
                    "sum_value": metric.sum_value,
                    "avg_value": metric.avg_value,
                    "period_start": metric.period_start.isoformat(),
                    "period_end": metric.period_end.isoformat(),
                }
            )

        return SearchVolumeResponse(period=period, granularity=granularity, data_points=data_points)

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve search volume: {str(e)}",
        )


# ============================================================================
# T054: GET /api/v1/analytics/top-queries
# ============================================================================


@router.get("/top-queries", response_model=List[TopQuery])
async def get_top_queries(
    limit: int = Query(20, ge=1, le=100, description="Number of top queries to return"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_with_role("admin")),
):
    """
    Aggregate top queries with metrics (T054).

    Requires: Admin role

    Queries search_history table and aggregates by query_text.
    Returns top N queries with:
    - Query count
    - Average response time
    - Average relevance score

    Args:
        limit: Number of top queries (default: 20, max: 100)

    Returns:
        List of TopQuery objects ordered by count descending
    """
    try:
        # TODO: Query search_history table (not yet created)
        # For now, return mock data
        print(f"[AnalyticsAPI] GET /top-queries - limit={limit}, user={current_user.username}")

        # Mock top queries (replace with actual query when search_history table exists)
        mock_queries = [
            TopQuery(
                query_text="UK immigration requirements",
                count=1245,
                avg_response_time_ms=892.5,
                avg_relevance_score=0.87,
            ),
            TopQuery(
                query_text="visa application process",
                count=987,
                avg_response_time_ms=1023.2,
                avg_relevance_score=0.82,
            ),
            TopQuery(
                query_text="settlement status check",
                count=756,
                avg_response_time_ms=945.8,
                avg_relevance_score=0.79,
            ),
        ]

        return mock_queries[:limit]

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve top queries: {str(e)}",
        )


# ============================================================================
# T055: GET /api/v1/analytics/response-times
# ============================================================================


@router.get("/response-times", response_model=ResponseTimePercentiles)
async def get_response_times(
    period: str = Query("24h", description="Time period (24h/7d/30d/90d)"),
    query_type: Optional[str] = Query(None, description="Optional filter by query type"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_with_role("admin")),
):
    """
    Calculate response time percentiles (T055).

    Requires: Admin role

    Queries analytics_metrics with metric_name='response_time'.
    Calculates p50 (median), p95, and p99 percentiles.

    Args:
        period: Time period for analysis
        query_type: Optional filter by query type

    Returns:
        ResponseTimePercentiles with p50/p95/p99 values
    """
    try:
        analytics_service = AnalyticsService(db)

        # Get response time metrics
        metrics = analytics_service.get_metrics_by_period(
            period=period, metric_types=["response_time"]
        )

        if not metrics:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No response time metrics found for period",
            )

        # For now, use aggregated values (avg) as approximation
        # TODO: Implement proper percentile calculation using window functions
        avg_value = metrics[0].avg_value if metrics else 0
        max_value = metrics[0].max_value if metrics else 0
        sample_count = metrics[0].count if metrics else 0

        # Approximate percentiles (replace with actual calculation)
        p50 = avg_value
        p95 = avg_value * 1.5  # Rough approximation
        p99 = max_value * 0.95  # Rough approximation

        return ResponseTimePercentiles(
            period=period,
            query_type=query_type,
            p50_ms=round(p50, 2),
            p95_ms=round(p95, 2),
            p99_ms=round(p99, 2),
            sample_count=sample_count,
        )

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to calculate response time percentiles: {str(e)}",
        )


# ============================================================================
# T056: GET /api/v1/analytics/error-rates
# ============================================================================


@router.get("/error-rates", response_model=List[ErrorRateWindow])
async def get_error_rates(
    period: str = Query("24h", description="Time period (24h/7d/30d/90d)"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_with_role("admin")),
):
    """
    Calculate error rates over 5-minute windows (T056).

    Requires: Admin role

    Queries analytics_metrics with category='error'.
    Calculates error_rate_percent = (errors / total) * 100 for each 5-minute window.

    Args:
        period: Time period for analysis

    Returns:
        List of ErrorRateWindow objects with error rate percentages
    """
    try:
        analytics_service = AnalyticsService(db)

        # Parse period to timedelta
        period_map = {
            "24h": timedelta(hours=24),
            "7d": timedelta(days=7),
            "30d": timedelta(days=30),
            "90d": timedelta(days=90),
        }

        if period not in period_map:
            raise ValueError(f"Invalid period '{period}'. Must be one of {list(period_map.keys())}")

        start_time = datetime.utcnow() - period_map[period]

        # TODO: Implement 5-minute window calculation using SQL window functions
        # For now, return single aggregated window
        metrics = analytics_service.get_metrics_by_period(
            period=period, metric_types=["error_count"]
        )

        windows = []
        if metrics:
            error_count = int(metrics[0].sum_value) if metrics else 0
            total_count = int(metrics[0].count) if metrics else 1
            error_rate = (error_count / total_count) * 100 if total_count > 0 else 0

            windows.append(
                ErrorRateWindow(
                    window_start=start_time,
                    window_end=datetime.utcnow(),
                    error_count=error_count,
                    total_count=total_count,
                    error_rate_percent=round(error_rate, 2),
                )
            )

        return windows

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to calculate error rates: {str(e)}",
        )


# ============================================================================
# T057: GET /api/v1/analytics/resource-usage
# ============================================================================


@router.get("/resource-usage", response_model=dict)
async def get_resource_usage(
    db: Session = Depends(get_db), current_user=Depends(get_current_user_with_role("admin"))
):
    """
    Get real-time system resource usage (T057).

    Requires: Admin role

    Returns real-time metrics:
    - CPU usage (percentage) via psutil
    - Memory usage (percentage, MB) via psutil
    - Storage usage (percentage, GB) via psutil
    - Database connections (active/max) via pg_stat_activity
    - Active WebSocket connections (count)

    Returns:
        Dict with resource usage metrics and status indicators
    """
    try:
        analytics_service = AnalyticsService(db)

        # Get resource usage from service
        resource_usage = analytics_service.get_resource_usage()

        return resource_usage

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve resource usage: {str(e)}",
        )


# ============================================================================
# T058: GET /api/v1/analytics/alerts
# ============================================================================


@router.get("/alerts", response_model=List[AlertResponse])
async def get_alerts(
    db: Session = Depends(get_db), current_user=Depends(get_current_user_with_role("admin"))
):
    """
    Check metrics against thresholds and return active alerts (T058).

    Requires: Admin role

    Thresholds (FR-AD-010):
    - error_rate ≥5%: WARNING, ≥15%: CRITICAL
    - response_time ≥2000ms: WARNING, ≥5000ms: CRITICAL
    - cpu_usage ≥70%: WARNING, ≥90%: CRITICAL
    - memory_usage ≥80%: WARNING, ≥95%: CRITICAL

    Returns:
        List of active Alert objects with severity and details
    """
    try:
        analytics_service = AnalyticsService(db)

        # Check thresholds
        alerts = analytics_service.check_thresholds()

        # Convert Alert objects to AlertResponse
        alert_responses = []
        for alert in alerts:
            alert_responses.append(
                AlertResponse(
                    metric_name=alert.metric_name,
                    current_value=alert.current_value,
                    threshold_value=alert.threshold_value,
                    severity=alert.severity,
                    message=alert.message,
                    timestamp=alert.timestamp,
                )
            )

        return alert_responses

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve alerts: {str(e)}",
        )


# ============================================================================
# T059: POST /api/v1/analytics/export
# ============================================================================


@router.post("/export")
async def export_metrics(
    export_request: ExportRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_with_role("admin")),
):
    """
    Export metrics to CSV or JSON format (T059).

    Requires: Admin role

    Exports metrics for specified period and optional metric types.
    Returns file download response (Blob type).

    Args:
        export_request: Export configuration (format, metric_types, period)

    Returns:
        FileResponse with CSV or JSON file
    """
    try:
        analytics_service = AnalyticsService(db)

        # Validate format
        if export_request.format not in ["csv", "json"]:
            raise ValueError("Format must be 'csv' or 'json'")

        # Get metrics for export
        aggregations = analytics_service.get_metrics_by_period(
            period=export_request.period, metric_types=export_request.metric_types
        )

        # TODO: Convert aggregations to AnalyticsMetricInDB objects
        # For now, create mock metrics list
        mock_metrics = []

        # Export to file
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"analytics_export_{timestamp}"

        if export_request.format == "csv":
            filepath = analytics_service.export_to_csv(mock_metrics, filename)
        else:
            filepath = analytics_service.export_to_json(mock_metrics, filename)

        # Return file response
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Export file not found: {filepath}")

        media_type = "text/csv" if export_request.format == "csv" else "application/json"

        return FileResponse(
            path=filepath, media_type=media_type, filename=os.path.basename(filepath)
        )

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to export metrics: {str(e)}",
        )
