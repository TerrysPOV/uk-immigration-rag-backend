"""
T036: AnalyticsService
Business logic layer for system performance monitoring and metrics aggregation

Service Methods:
- record_metric(metric_name, value, unit, category, metadata): Record new metric
- get_metrics_by_period(period, metric_types): Query metrics with time period filter
- get_resource_usage(): Real-time system resource monitoring (CPU, memory, storage, connections)
- check_thresholds(): Evaluate metrics against alert thresholds
- export_to_csv(metrics, filename): Export metrics to CSV format
- export_to_json(metrics, filename): Export metrics to JSON format

Alert Thresholds (FR-AD-010):
- error_rate ≥5%: WARNING
- error_rate ≥15%: CRITICAL
- response_time ≥2000ms: WARNING
- response_time ≥5000ms: CRITICAL
- cpu_usage ≥70%: WARNING
- cpu_usage ≥90%: CRITICAL
- memory_usage ≥80%: WARNING
- memory_usage ≥95%: CRITICAL
"""

from typing import List, Optional, Dict, Tuple
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func
import psutil
import csv
import json

from ..models.analytics_metric import (
    AnalyticsMetric,
    AnalyticsMetricCreate,
    AnalyticsMetricInDB,
    MetricAggregation,
)


class Alert:
    """Alert object for threshold breaches."""

    def __init__(
        self,
        metric_name: str,
        current_value: float,
        threshold_value: float,
        severity: str,
        message: str,
    ):
        self.metric_name = metric_name
        self.current_value = current_value
        self.threshold_value = threshold_value
        self.severity = severity  # WARNING or CRITICAL
        self.message = message
        self.timestamp = datetime.utcnow()


class AnalyticsService:
    """
    Service layer for analytics and performance monitoring.

    Handles metric recording, aggregation, resource monitoring, and alerting.
    Supports CSV/JSON export for compliance reporting.
    """

    # Alert thresholds (FR-AD-010)
    THRESHOLDS = {
        "error_rate": {"WARNING": 5.0, "CRITICAL": 15.0},  # percentage
        "response_time": {"WARNING": 2000.0, "CRITICAL": 5000.0},  # milliseconds
        "cpu_usage": {"WARNING": 70.0, "CRITICAL": 90.0},  # percentage
        "memory_usage": {"WARNING": 80.0, "CRITICAL": 95.0},  # percentage
        "storage_usage": {"WARNING": 85.0, "CRITICAL": 95.0},  # percentage
        "db_connections": {"WARNING": 80.0, "CRITICAL": 95.0},  # percentage of max connections
    }

    def __init__(self, db: Session):
        """
        Initialize AnalyticsService with database session.

        Args:
            db: SQLAlchemy database session
        """
        self.db = db

    def record_metric(
        self,
        metric_name: str,
        value: float,
        unit: str,
        category: str,
        metadata: Optional[Dict] = None,
    ) -> AnalyticsMetricInDB:
        """
        Record new analytics metric.

        Args:
            metric_name: Metric identifier (search_volume, response_time, etc.)
            value: Numeric value
            unit: Measurement unit (count, ms, percentage, bytes, mb, gb)
            category: Metric category (search, performance, error, resource)
            metadata: Optional additional context

        Returns:
            Created metric record

        Logs:
            - INFO: Metric recorded successfully
            - ERROR: Metric recording failed
        """
        metric_data = AnalyticsMetricCreate(
            metric_name=metric_name,
            metric_value=value,
            metric_unit=unit,
            category=category,
            metadata=metadata,
        )

        new_metric = AnalyticsMetric(
            metric_name=metric_data.metric_name,
            metric_value=metric_data.metric_value,
            metric_unit=metric_data.metric_unit,
            category=metric_data.category,
            metadata=metric_data.metadata,
        )

        try:
            self.db.add(new_metric)
            self.db.commit()
            self.db.refresh(new_metric)

            print(
                f"[AnalyticsService] Recorded metric: {metric_name}={value}{unit} (category={category})"
            )
            return AnalyticsMetricInDB.from_orm(new_metric)

        except Exception as e:
            self.db.rollback()
            print(f"[AnalyticsService] ERROR: Failed to record metric - {str(e)}")
            raise ValueError(f"Failed to record metric: {str(e)}")

    def get_metrics_by_period(
        self, period: str, metric_types: Optional[List[str]] = None, granularity: str = "hour"
    ) -> List[MetricAggregation]:
        """
        Query metrics with time period filter and optional aggregation.

        Args:
            period: Time period (24h, 7d, 30d, 90d)
            metric_types: Optional list of metric names to filter
            granularity: Aggregation granularity (hour, day, week)

        Returns:
            List of aggregated metrics

        Logs:
            - INFO: Number of metrics retrieved with period details
        """
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

        query = self.db.query(
            AnalyticsMetric.metric_name,
            AnalyticsMetric.category,
            func.count(AnalyticsMetric.id).label("count"),
            func.min(AnalyticsMetric.metric_value).label("min_value"),
            func.max(AnalyticsMetric.metric_value).label("max_value"),
            func.avg(AnalyticsMetric.metric_value).label("avg_value"),
            func.sum(AnalyticsMetric.metric_value).label("sum_value"),
        ).filter(AnalyticsMetric.timestamp >= start_time)

        # Filter by metric types if provided
        if metric_types:
            query = query.filter(AnalyticsMetric.metric_name.in_(metric_types))

        # Group by metric name and category
        query = query.group_by(AnalyticsMetric.metric_name, AnalyticsMetric.category)

        results = query.all()

        aggregations = []
        for row in results:
            agg = MetricAggregation(
                metric_name=row.metric_name,
                category=row.category,
                period_start=start_time,
                period_end=datetime.utcnow(),
                count=row.count,
                min_value=row.min_value,
                max_value=row.max_value,
                avg_value=row.avg_value,
                sum_value=row.sum_value,
            )
            aggregations.append(agg)

        print(
            f"[AnalyticsService] Retrieved {len(aggregations)} metric aggregations for period={period}, granularity={granularity}"
        )
        return aggregations

    def get_resource_usage(self) -> Dict:
        """
        Get real-time system resource usage.

        Returns:
            Dict with CPU, memory, storage, and database connection metrics

        Logs:
            - INFO: Resource usage details
        """
        # CPU usage (percentage)
        cpu_percent = psutil.cpu_percent(interval=1)

        # Memory usage
        memory = psutil.virtual_memory()
        memory_percent = memory.percent
        memory_used_mb = memory.used / (1024 * 1024)
        memory_total_mb = memory.total / (1024 * 1024)

        # Storage usage
        disk = psutil.disk_usage("/")
        storage_percent = disk.percent
        storage_used_gb = disk.used / (1024 * 1024 * 1024)
        storage_total_gb = disk.total / (1024 * 1024 * 1024)

        # Database connections (mock - requires pg_stat_activity query)
        # TODO: Query PostgreSQL pg_stat_activity for actual connection count
        db_connections_active = 0  # Placeholder
        db_connections_max = 100  # Placeholder
        db_connections_percent = (db_connections_active / db_connections_max) * 100

        # Active WebSocket connections (mock - requires WebSocket manager)
        # TODO: Query WebSocket manager for active connection count
        websocket_connections = 0  # Placeholder

        resource_usage = {
            "cpu": {
                "percent": cpu_percent,
                "status": (
                    "healthy" if cpu_percent < 70 else "warning" if cpu_percent < 90 else "critical"
                ),
            },
            "memory": {
                "percent": memory_percent,
                "used_mb": round(memory_used_mb, 2),
                "total_mb": round(memory_total_mb, 2),
                "status": (
                    "healthy"
                    if memory_percent < 80
                    else "warning" if memory_percent < 95 else "critical"
                ),
            },
            "storage": {
                "percent": storage_percent,
                "used_gb": round(storage_used_gb, 2),
                "total_gb": round(storage_total_gb, 2),
                "status": (
                    "healthy"
                    if storage_percent < 85
                    else "warning" if storage_percent < 95 else "critical"
                ),
            },
            "database_connections": {
                "active": db_connections_active,
                "max": db_connections_max,
                "percent": db_connections_percent,
                "status": (
                    "healthy"
                    if db_connections_percent < 80
                    else "warning" if db_connections_percent < 95 else "critical"
                ),
            },
            "websocket_connections": {"active": websocket_connections, "status": "healthy"},
            "timestamp": datetime.utcnow().isoformat(),
        }

        print(
            f"[AnalyticsService] Resource usage: CPU={cpu_percent}%, Memory={memory_percent}%, Storage={storage_percent}%"
        )
        return resource_usage

    def check_thresholds(self) -> List[Alert]:
        """
        Check current metrics against alert thresholds.

        Returns:
            List of active alerts for metrics exceeding thresholds

        Logs:
            - INFO: Number of active alerts
            - WARNING: Threshold breach details
        """
        alerts = []

        # Get resource usage
        resource_usage = self.get_resource_usage()

        # Check CPU usage
        cpu_percent = resource_usage["cpu"]["percent"]
        if cpu_percent >= self.THRESHOLDS["cpu_usage"]["CRITICAL"]:
            alerts.append(
                Alert(
                    metric_name="cpu_usage",
                    current_value=cpu_percent,
                    threshold_value=self.THRESHOLDS["cpu_usage"]["CRITICAL"],
                    severity="CRITICAL",
                    message=f"CPU usage at {cpu_percent}% (threshold: {self.THRESHOLDS['cpu_usage']['CRITICAL']}%)",
                )
            )
        elif cpu_percent >= self.THRESHOLDS["cpu_usage"]["WARNING"]:
            alerts.append(
                Alert(
                    metric_name="cpu_usage",
                    current_value=cpu_percent,
                    threshold_value=self.THRESHOLDS["cpu_usage"]["WARNING"],
                    severity="WARNING",
                    message=f"CPU usage at {cpu_percent}% (threshold: {self.THRESHOLDS['cpu_usage']['WARNING']}%)",
                )
            )

        # Check memory usage
        memory_percent = resource_usage["memory"]["percent"]
        if memory_percent >= self.THRESHOLDS["memory_usage"]["CRITICAL"]:
            alerts.append(
                Alert(
                    metric_name="memory_usage",
                    current_value=memory_percent,
                    threshold_value=self.THRESHOLDS["memory_usage"]["CRITICAL"],
                    severity="CRITICAL",
                    message=f"Memory usage at {memory_percent}% (threshold: {self.THRESHOLDS['memory_usage']['CRITICAL']}%)",
                )
            )
        elif memory_percent >= self.THRESHOLDS["memory_usage"]["WARNING"]:
            alerts.append(
                Alert(
                    metric_name="memory_usage",
                    current_value=memory_percent,
                    threshold_value=self.THRESHOLDS["memory_usage"]["WARNING"],
                    severity="WARNING",
                    message=f"Memory usage at {memory_percent}% (threshold: {self.THRESHOLDS['memory_usage']['WARNING']}%)",
                )
            )

        # Check storage usage
        storage_percent = resource_usage["storage"]["percent"]
        if storage_percent >= self.THRESHOLDS["storage_usage"]["CRITICAL"]:
            alerts.append(
                Alert(
                    metric_name="storage_usage",
                    current_value=storage_percent,
                    threshold_value=self.THRESHOLDS["storage_usage"]["CRITICAL"],
                    severity="CRITICAL",
                    message=f"Storage usage at {storage_percent}% (threshold: {self.THRESHOLDS['storage_usage']['CRITICAL']}%)",
                )
            )
        elif storage_percent >= self.THRESHOLDS["storage_usage"]["WARNING"]:
            alerts.append(
                Alert(
                    metric_name="storage_usage",
                    current_value=storage_percent,
                    threshold_value=self.THRESHOLDS["storage_usage"]["WARNING"],
                    severity="WARNING",
                    message=f"Storage usage at {storage_percent}% (threshold: {self.THRESHOLDS['storage_usage']['WARNING']}%)",
                )
            )

        # Check error rate (query recent metrics)
        error_rate = self._calculate_error_rate()
        if error_rate is not None:
            if error_rate >= self.THRESHOLDS["error_rate"]["CRITICAL"]:
                alerts.append(
                    Alert(
                        metric_name="error_rate",
                        current_value=error_rate,
                        threshold_value=self.THRESHOLDS["error_rate"]["CRITICAL"],
                        severity="CRITICAL",
                        message=f"Error rate at {error_rate}% (threshold: {self.THRESHOLDS['error_rate']['CRITICAL']}%)",
                    )
                )
            elif error_rate >= self.THRESHOLDS["error_rate"]["WARNING"]:
                alerts.append(
                    Alert(
                        metric_name="error_rate",
                        current_value=error_rate,
                        threshold_value=self.THRESHOLDS["error_rate"]["WARNING"],
                        severity="WARNING",
                        message=f"Error rate at {error_rate}% (threshold: {self.THRESHOLDS['error_rate']['WARNING']}%)",
                    )
                )

        # Check response time (query recent metrics)
        avg_response_time = self._calculate_avg_response_time()
        if avg_response_time is not None:
            if avg_response_time >= self.THRESHOLDS["response_time"]["CRITICAL"]:
                alerts.append(
                    Alert(
                        metric_name="response_time",
                        current_value=avg_response_time,
                        threshold_value=self.THRESHOLDS["response_time"]["CRITICAL"],
                        severity="CRITICAL",
                        message=f"Response time at {avg_response_time}ms (threshold: {self.THRESHOLDS['response_time']['CRITICAL']}ms)",
                    )
                )
            elif avg_response_time >= self.THRESHOLDS["response_time"]["WARNING"]:
                alerts.append(
                    Alert(
                        metric_name="response_time",
                        current_value=avg_response_time,
                        threshold_value=self.THRESHOLDS["response_time"]["WARNING"],
                        severity="WARNING",
                        message=f"Response time at {avg_response_time}ms (threshold: {self.THRESHOLDS['response_time']['WARNING']}ms)",
                    )
                )

        print(f"[AnalyticsService] Threshold check complete: {len(alerts)} active alerts")
        for alert in alerts:
            print(f"[AnalyticsService] {alert.severity}: {alert.message}")

        return alerts

    def _calculate_error_rate(self) -> Optional[float]:
        """Calculate error rate over last 5 minutes."""
        five_min_ago = datetime.utcnow() - timedelta(minutes=5)

        error_count = (
            self.db.query(func.count(AnalyticsMetric.id))
            .filter(AnalyticsMetric.category == "error", AnalyticsMetric.timestamp >= five_min_ago)
            .scalar()
        )

        total_count = (
            self.db.query(func.count(AnalyticsMetric.id))
            .filter(AnalyticsMetric.timestamp >= five_min_ago)
            .scalar()
        )

        if total_count == 0:
            return None

        error_rate = (error_count / total_count) * 100
        return round(error_rate, 2)

    def _calculate_avg_response_time(self) -> Optional[float]:
        """Calculate average response time over last 5 minutes."""
        five_min_ago = datetime.utcnow() - timedelta(minutes=5)

        avg_time = (
            self.db.query(func.avg(AnalyticsMetric.metric_value))
            .filter(
                AnalyticsMetric.metric_name == "response_time",
                AnalyticsMetric.timestamp >= five_min_ago,
            )
            .scalar()
        )

        if avg_time is None:
            return None

        return round(avg_time, 2)

    def export_to_csv(self, metrics: List[AnalyticsMetricInDB], filename: str) -> str:
        """
        Export metrics to CSV file.

        Args:
            metrics: List of metrics to export
            filename: Output filename (without extension)

        Returns:
            Path to created CSV file

        Logs:
            - INFO: Export details
        """
        filepath = f"/tmp/{filename}.csv"

        with open(filepath, "w", newline="") as csvfile:
            fieldnames = [
                "id",
                "metric_name",
                "metric_value",
                "metric_unit",
                "timestamp",
                "category",
                "metadata",
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            writer.writeheader()
            for metric in metrics:
                writer.writerow(
                    {
                        "id": metric.id,
                        "metric_name": metric.metric_name,
                        "metric_value": metric.metric_value,
                        "metric_unit": metric.metric_unit,
                        "timestamp": metric.timestamp.isoformat(),
                        "category": metric.category,
                        "metadata": json.dumps(metric.metadata) if metric.metadata else "",
                    }
                )

        print(f"[AnalyticsService] Exported {len(metrics)} metrics to CSV: {filepath}")
        return filepath

    def export_to_json(self, metrics: List[AnalyticsMetricInDB], filename: str) -> str:
        """
        Export metrics to JSON file.

        Args:
            metrics: List of metrics to export
            filename: Output filename (without extension)

        Returns:
            Path to created JSON file

        Logs:
            - INFO: Export details
        """
        filepath = f"/tmp/{filename}.json"

        metrics_data = []
        for metric in metrics:
            metrics_data.append(
                {
                    "id": metric.id,
                    "metric_name": metric.metric_name,
                    "metric_value": metric.metric_value,
                    "metric_unit": metric.metric_unit,
                    "timestamp": metric.timestamp.isoformat(),
                    "category": metric.category,
                    "metadata": metric.metadata,
                }
            )

        with open(filepath, "w") as jsonfile:
            json.dump(metrics_data, jsonfile, indent=2)

        print(f"[AnalyticsService] Exported {len(metrics)} metrics to JSON: {filepath}")
        return filepath
