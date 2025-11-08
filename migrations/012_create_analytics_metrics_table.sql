-- Migration: Feature 012 - Create analytics_metrics table with time-series partitioning
-- Date: 2025-10-14
-- Description: Store system performance metrics for analytics dashboard

CREATE TABLE IF NOT EXISTS analytics_metrics (
    id BIGSERIAL PRIMARY KEY,
    metric_name VARCHAR(100) NOT NULL,
    metric_value DOUBLE PRECISION NOT NULL CHECK (metric_value >= 0),
    metric_unit VARCHAR(20) NOT NULL CHECK (metric_unit IN ('count', 'ms', 'percentage', 'bytes', 'mb', 'gb')),
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    category VARCHAR(50) NOT NULL CHECK (category IN ('search', 'performance', 'error', 'resource')),
    metadata JSONB NULL
);

-- Create indexes for efficient time-series queries
CREATE INDEX IF NOT EXISTS idx_analytics_timestamp ON analytics_metrics(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_analytics_metric_name ON analytics_metrics(metric_name);
CREATE INDEX IF NOT EXISTS idx_analytics_category ON analytics_metrics(category);
CREATE INDEX IF NOT EXISTS idx_analytics_composite ON analytics_metrics(metric_name, category, timestamp DESC);

-- Optional: Partition table by month for better query performance
-- This is a manual partitioning strategy - adjust based on data volume
-- Example partition creation for current month:
-- CREATE TABLE analytics_metrics_2025_10 PARTITION OF analytics_metrics
--     FOR VALUES FROM ('2025-10-01') TO ('2025-11-01');

-- Note: Automatic archival of metrics older than 90 days should be implemented
-- via a scheduled cleanup job (Celery task or cron job)
