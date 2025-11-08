-- Migration: Feature 012 - Create workflow_steps table
-- Date: 2025-10-14
-- Description: Individual actions within workflow processes with retry configuration

CREATE TABLE IF NOT EXISTS workflow_steps (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workflow_id UUID NOT NULL,
    step_number INTEGER NOT NULL,
    step_type VARCHAR(50) NOT NULL CHECK (step_type IN ('transform', 'api', 'notify', 'condition', 'delay')),
    parameters JSONB NOT NULL,
    input_source VARCHAR(100) NULL,
    output_destination VARCHAR(100) NULL,
    retry_config JSONB NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- FK to workflows table
    CONSTRAINT fk_workflow_steps_workflow FOREIGN KEY (workflow_id) REFERENCES workflows(id) ON DELETE CASCADE,

    -- Ensure step numbers are unique per workflow
    CONSTRAINT unique_workflow_step_order UNIQUE (workflow_id, step_number)
);

-- Create indexes for efficient step queries
CREATE INDEX IF NOT EXISTS idx_workflow_steps_workflow ON workflow_steps(workflow_id, step_number);

-- Validate retry_config structure
CREATE OR REPLACE FUNCTION validate_retry_config()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.retry_config IS NOT NULL THEN
        -- Check required keys exist
        IF NOT (NEW.retry_config ? 'strategy') THEN
            RAISE EXCEPTION 'retry_config must contain "strategy" key';
        END IF;

        -- Validate strategy value
        IF NOT (NEW.retry_config->>'strategy' IN ('immediate', 'exponential', 'manual', 'circuit_breaker')) THEN
            RAISE EXCEPTION 'retry_config.strategy must be one of: immediate, exponential, manual, circuit_breaker';
        END IF;

        -- Validate strategy-specific required fields
        IF NEW.retry_config->>'strategy' IN ('immediate', 'exponential') THEN
            IF NOT (NEW.retry_config ? 'max_attempts') THEN
                RAISE EXCEPTION 'retry_config must contain "max_attempts" for immediate/exponential strategies';
            END IF;
        END IF;

        IF NEW.retry_config->>'strategy' = 'exponential' THEN
            IF NOT (NEW.retry_config ? 'backoff_multiplier') THEN
                RAISE EXCEPTION 'retry_config must contain "backoff_multiplier" for exponential strategy';
            END IF;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_validate_retry_config
BEFORE INSERT OR UPDATE ON workflow_steps
FOR EACH ROW
EXECUTE FUNCTION validate_retry_config();
