-- Migration: Feature 012 - Create workflow_executions table
-- Date: 2025-10-14
-- Description: Historical records of workflow execution instances

CREATE TABLE IF NOT EXISTS workflow_executions (
    execution_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workflow_id UUID NOT NULL,
    status VARCHAR(20) NOT NULL CHECK (status IN ('running', 'completed', 'failed', 'paused')),
    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP NULL,
    current_step INTEGER NULL,
    execution_logs JSONB NOT NULL DEFAULT '[]',
    error_message TEXT NULL,
    progress_percentage INTEGER NULL CHECK (progress_percentage >= 0 AND progress_percentage <= 100),
    triggered_by VARCHAR(50) NOT NULL CHECK (triggered_by IN ('manual', 'automatic', 'schedule')),

    -- FK to workflows table
    CONSTRAINT fk_workflow_executions_workflow FOREIGN KEY (workflow_id) REFERENCES workflows(id) ON DELETE CASCADE,

    -- Ensure completed_at is after started_at
    CONSTRAINT check_execution_time_order CHECK (completed_at IS NULL OR completed_at >= started_at)
);

-- Create indexes for efficient execution queries
CREATE INDEX IF NOT EXISTS idx_workflow_executions_workflow ON workflow_executions(workflow_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_workflow_executions_status ON workflow_executions(status);
CREATE INDEX IF NOT EXISTS idx_workflow_executions_started_at ON workflow_executions(started_at DESC);

-- Validate execution_logs structure
CREATE OR REPLACE FUNCTION validate_execution_logs()
RETURNS TRIGGER AS $$
DECLARE
    log_entry JSONB;
BEGIN
    -- execution_logs must be an array of objects with step_number, status, duration_ms, output
    IF jsonb_typeof(NEW.execution_logs) != 'array' THEN
        RAISE EXCEPTION 'execution_logs must be a JSON array';
    END IF;

    -- Validate each log entry structure
    FOR log_entry IN SELECT * FROM jsonb_array_elements(NEW.execution_logs)
    LOOP
        IF NOT (log_entry ? 'step_number' AND log_entry ? 'status') THEN
            RAISE EXCEPTION 'execution_logs entries must contain step_number and status keys';
        END IF;
    END LOOP;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_validate_execution_logs
BEFORE INSERT OR UPDATE ON workflow_executions
FOR EACH ROW
EXECUTE FUNCTION validate_execution_logs();
