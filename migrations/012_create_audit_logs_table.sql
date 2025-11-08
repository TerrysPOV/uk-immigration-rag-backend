-- Migration: Feature 012 - Create audit_logs table with monthly partitioning
-- Date: 2025-10-14
-- Description: Immutable records of system changes for compliance (7-year retention)

CREATE TABLE IF NOT EXISTS audit_logs (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    user_id UUID NOT NULL,
    action_type VARCHAR(50) NOT NULL CHECK (action_type IN ('create', 'update', 'delete', 'login', 'logout', 'config_change', 'role_change')),
    resource_type VARCHAR(50) NOT NULL CHECK (resource_type IN ('user', 'role', 'template', 'workflow', 'config', 'session')),
    resource_id VARCHAR(100) NULL,
    old_value JSONB NULL,
    new_value JSONB NULL,
    ip_address INET NOT NULL,
    user_agent TEXT NULL,

    -- FK to users table (RESTRICT to preserve audit logs even if user is deleted)
    CONSTRAINT fk_audit_logs_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE RESTRICT
);

-- Create indexes for efficient audit queries
CREATE INDEX IF NOT EXISTS idx_audit_logs_timestamp ON audit_logs(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_logs_user ON audit_logs(user_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_logs_resource ON audit_logs(resource_type, resource_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON audit_logs(action_type, timestamp DESC);

-- Prevent UPDATE and DELETE operations (INSERT-only table)
CREATE OR REPLACE FUNCTION prevent_audit_log_modification()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'UPDATE operations are not allowed on audit_logs table (immutable)';
    ELSIF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'DELETE operations are not allowed on audit_logs table (immutable)';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_prevent_audit_log_update
BEFORE UPDATE ON audit_logs
FOR EACH ROW
EXECUTE FUNCTION prevent_audit_log_modification();

CREATE TRIGGER trigger_prevent_audit_log_delete
BEFORE DELETE ON audit_logs
FOR EACH ROW
EXECUTE FUNCTION prevent_audit_log_modification();

-- Optional: Partition table by month for better query performance
-- Example partition creation for current month:
-- CREATE TABLE audit_logs_2025_10 PARTITION OF audit_logs
--     FOR VALUES FROM ('2025-10-01') TO ('2025-11-01');

-- Note: 7-year retention policy should be implemented via scheduled cleanup job
-- that moves old partitions to archive storage (Celery task or cron job)
