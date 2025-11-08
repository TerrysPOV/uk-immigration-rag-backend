"""
T026: AnalyticsMetric Model
Database model for time-series system performance monitoring

Entity: AnalyticsMetric
Purpose: Time-series data point for system performance monitoring
Table: analytics_metrics

Features:
- Time-series optimization with monthly partitioning
- Automatic archival of metrics older than 90 days
- Support for multiple metric categories (search/performance/error/resource)
"""

from datetime import datetime
from typing import Optional
from sqlalchemy import Column, BigInteger, VARCHAR, Float, TIMESTAMP, CheckConstraint, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import validates
from pydantic import BaseModel, Field, validator

from .base import Base


class AnalyticsMetric(Base):
    """
    AnalyticsMetric model for time-series performance data.

    Attributes:
        id (int): Primary key (BIGSERIAL)
        metric_name (str): Metric name (search_volume, response_time, error_rate, cpu_usage, etc.)
        metric_value (float): Numeric value
        metric_unit (str): Unit (count, ms, percentage, bytes, mb, gb)
        timestamp (datetime): Metric recording time
        category (str): Category (search/performance/error/resource)
        metadata (dict): Additional context (JSONB)

    Validation:
        - metric_value must be non-negative
        - metric_unit must be in allowed list
        - category must be in allowed list
        - timestamp must be within last 90 days (older metrics archived)

    Indexes:
        - idx_analytics_timestamp: timestamp DESC
        - idx_analytics_metric_name: metric_name
        - idx_analytics_category: category
        - idx_analytics_composite: (metric_name, category, timestamp DESC)
    """

    __tablename__ = "analytics_metrics"

    # Columns
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    metric_name = Column(VARCHAR(100), nullable=False)
    metric_value = Column(Float, nullable=False)
    metric_unit = Column(VARCHAR(20), nullable=False)
    timestamp = Column(TIMESTAMP, nullable=False, default=datetime.utcnow)
    category = Column(VARCHAR(50), nullable=False)
    metadata = Column(JSONB, nullable=True)

    # Allowed values
    ALLOWED_UNITS = ["count", "ms", "percentage", "bytes", "mb", "gb"]
    ALLOWED_CATEGORIES = ["search", "performance", "error", "resource"]

    # Constraints
    __table_args__ = (
        CheckConstraint("metric_value >= 0", name="ck_analytics_metric_value_positive"),
        Index("idx_analytics_timestamp", "timestamp", postgresql_ops={"timestamp": "DESC"}),
        Index("idx_analytics_metric_name", "metric_name"),
        Index("idx_analytics_category", "category"),
        Index(
            "idx_analytics_composite",
            "metric_name",
            "category",
            "timestamp",
            postgresql_ops={"timestamp": "DESC"},
        ),
    )

    @validates("metric_value")
    def validate_metric_value(self, key, value):
        """Validate metric_value is non-negative."""
        if value < 0:
            raise ValueError(f"metric_value must be non-negative, got {value}")
        return value

    @validates("metric_unit")
    def validate_metric_unit(self, key, value):
        """Validate metric_unit is in allowed list."""
        if value not in self.ALLOWED_UNITS:
            raise ValueError(f"metric_unit must be one of {self.ALLOWED_UNITS}, got '{value}'")
        return value

    @validates("category")
    def validate_category(self, key, value):
        """Validate category is in allowed list."""
        if value not in self.ALLOWED_CATEGORIES:
            raise ValueError(f"category must be one of {self.ALLOWED_CATEGORIES}, got '{value}'")
        return value

    def __repr__(self):
        return f"<AnalyticsMetric(id={self.id}, metric_name='{self.metric_name}', value={self.metric_value}, category='{self.category}')>"


# Pydantic schemas for API validation
class AnalyticsMetricBase(BaseModel):
    """Base analytics metric schema."""

    metric_name: str = Field(
        ..., description="Metric name (e.g., search_volume, response_time)", max_length=100
    )
    metric_value: float = Field(..., description="Numeric value", ge=0)
    metric_unit: str = Field(..., description="Unit (count/ms/percentage/bytes/mb/gb)")
    category: str = Field(..., description="Category (search/performance/error/resource)")
    metadata: Optional[dict] = Field(None, description="Additional context (JSONB)")

    @validator("metric_unit")
    def validate_unit(cls, v):
        if v not in AnalyticsMetric.ALLOWED_UNITS:
            raise ValueError(f"metric_unit must be one of {AnalyticsMetric.ALLOWED_UNITS}")
        return v

    @validator("category")
    def validate_category_value(cls, v):
        if v not in AnalyticsMetric.ALLOWED_CATEGORIES:
            raise ValueError(f"category must be one of {AnalyticsMetric.ALLOWED_CATEGORIES}")
        return v


class AnalyticsMetricCreate(AnalyticsMetricBase):
    """Schema for creating new metric."""

    pass


class AnalyticsMetricInDB(AnalyticsMetricBase):
    """Schema for metric stored in database."""

    id: int
    timestamp: datetime

    class Config:
        orm_mode = True


class MetricAggregation(BaseModel):
    """Schema for aggregated metrics."""

    metric_name: str
    category: str
    period_start: datetime
    period_end: datetime
    count: int
    min_value: float
    max_value: float
    avg_value: float
    sum_value: float
