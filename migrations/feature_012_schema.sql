-- Feature 012: Comprehensive Frontend Enhancement Suite
-- Database Schema Migration
-- Generated: 2025-10-16 12:44
--
-- Creates tables for:
-- - Role-based access control (roles, users)
-- - Template management (templates, template_versions)
-- - Workflow automation (workflows, workflow_steps, workflow_executions)
-- - Advanced search (saved_queries)
-- - Analytics dashboard (analytics_metrics)
-- - Admin panel (audit_logs)

-- Enable UUID extension if not already enabled
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. Create roles table
CREATE TABLE IF NOT EXISTS roles (
    role_name VARCHAR(50) PRIMARY KEY,
    permissions JSONB NOT NULL,
    description TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Insert default roles (skip if already exist)
INSERT INTO roles (role_name, permissions, description) VALUES
('admin',
 '["users:read", "users:write", "users:delete", "config:read", "config:write", "audit:read", "templates:read", "templates:write", "templates:delete", "workflows:read", "workflows:write", "workflows:delete", "workflows:execute", "analytics:read", "search:read", "search:write", "a11y:configure", "a11y:audit"]'::jsonb,
 'Full system access including user management, configuration, and audit logs'),
('caseworker',
 '["templates:read", "templates:write", "workflows:read", "workflows:write", "workflows:execute", "analytics:read", "search:read", "search:write", "a11y:audit"]'::jsonb,
 'Can create, edit, and manage templates and workflows'),
('operator',
 '["templates:read", "workflows:read", "workflows:execute", "search:read", "search:write"]'::jsonb,
 'Can execute workflows and perform searches'),
('viewer',
 '["search:read", "templates:read"]'::jsonb,
 'Read-only access to search and view documents')
ON CONFLICT (role_name) DO NOTHING;

-- 2. Create users table
CREATE TABLE IF NOT EXISTS users (
    id VARCHAR(36) PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL REFERENCES roles(role_name) ON DELETE RESTRICT ON UPDATE CASCADE,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_login_at TIMESTAMP,
    CONSTRAINT check_user_status CHECK (status IN ('active', 'inactive'))
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);
CREATE INDEX IF NOT EXISTS idx_users_status ON users(status);

-- 3. Create templates table
CREATE TABLE IF NOT EXISTS templates (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    category VARCHAR(100) NOT NULL,
    created_by VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_templates_category ON templates(category);
CREATE INDEX IF NOT EXISTS idx_templates_created_by ON templates(created_by);
CREATE INDEX IF NOT EXISTS idx_templates_is_active ON templates(is_active);

-- 4. Create template_versions table
CREATE TABLE IF NOT EXISTS template_versions (
    id VARCHAR(36) PRIMARY KEY,
    template_id VARCHAR(36) NOT NULL REFERENCES templates(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    content JSONB NOT NULL,
    change_summary TEXT,
    created_by VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_template_version UNIQUE (template_id, version_number)
);

CREATE INDEX IF NOT EXISTS idx_template_versions_template_id ON template_versions(template_id);
CREATE INDEX IF NOT EXISTS idx_template_versions_version_number ON template_versions(version_number);

-- 5. Create workflows table
CREATE TABLE IF NOT EXISTS workflows (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    trigger_type VARCHAR(50) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_by VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT check_trigger_type CHECK (trigger_type IN ('manual', 'scheduled', 'event', 'webhook'))
);

CREATE INDEX IF NOT EXISTS idx_workflows_trigger_type ON workflows(trigger_type);
CREATE INDEX IF NOT EXISTS idx_workflows_is_active ON workflows(is_active);
CREATE INDEX IF NOT EXISTS idx_workflows_created_by ON workflows(created_by);

-- 6. Create workflow_steps table
CREATE TABLE IF NOT EXISTS workflow_steps (
    id VARCHAR(36) PRIMARY KEY,
    workflow_id VARCHAR(36) NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
    step_order INTEGER NOT NULL,
    step_type VARCHAR(50) NOT NULL,
    configuration JSONB NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_workflow_step_order UNIQUE (workflow_id, step_order),
    CONSTRAINT check_step_type CHECK (step_type IN ('condition', 'action', 'transform', 'delay'))
);

CREATE INDEX IF NOT EXISTS idx_workflow_steps_workflow_id ON workflow_steps(workflow_id);
CREATE INDEX IF NOT EXISTS idx_workflow_steps_step_order ON workflow_steps(step_order);

-- 7. Create workflow_executions table
CREATE TABLE IF NOT EXISTS workflow_executions (
    id VARCHAR(36) PRIMARY KEY,
    workflow_id VARCHAR(36) NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
    triggered_by VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    status VARCHAR(20) NOT NULL,
    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    error_message TEXT,
    execution_log JSONB,
    CONSTRAINT check_execution_status CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled'))
);

CREATE INDEX IF NOT EXISTS idx_workflow_executions_workflow_id ON workflow_executions(workflow_id);
CREATE INDEX IF NOT EXISTS idx_workflow_executions_status ON workflow_executions(status);
CREATE INDEX IF NOT EXISTS idx_workflow_executions_triggered_by ON workflow_executions(triggered_by);
CREATE INDEX IF NOT EXISTS idx_workflow_executions_started_at ON workflow_executions(started_at);

-- 8. Create saved_queries table
CREATE TABLE IF NOT EXISTS saved_queries (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(200) NOT NULL,
    query_text TEXT NOT NULL,
    query_type VARCHAR(50) NOT NULL,
    filters JSONB,
    is_public BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_used_at TIMESTAMP,
    CONSTRAINT check_query_type CHECK (query_type IN ('simple', 'advanced', 'boolean'))
);

CREATE INDEX IF NOT EXISTS idx_saved_queries_user_id ON saved_queries(user_id);
CREATE INDEX IF NOT EXISTS idx_saved_queries_query_type ON saved_queries(query_type);
CREATE INDEX IF NOT EXISTS idx_saved_queries_is_public ON saved_queries(is_public);

-- 9. Create analytics_metrics table
CREATE TABLE IF NOT EXISTS analytics_metrics (
    id VARCHAR(36) PRIMARY KEY,
    metric_type VARCHAR(100) NOT NULL,
    metric_value NUMERIC(10, 2) NOT NULL,
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata JSONB,
    CONSTRAINT check_metric_type CHECK (metric_type IN ('search_query', 'response_time_ms', 'doc_view', 'template_usage', 'workflow_execution'))
);

CREATE INDEX IF NOT EXISTS idx_analytics_metrics_metric_type ON analytics_metrics(metric_type);
CREATE INDEX IF NOT EXISTS idx_analytics_metrics_timestamp ON analytics_metrics(timestamp);

-- 10. Create audit_logs table (distinct from existing audit_log)
CREATE TABLE IF NOT EXISTS audit_logs (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    action_type VARCHAR(100) NOT NULL,
    resource_type VARCHAR(100) NOT NULL,
    resource_id VARCHAR(36),
    old_value JSONB,
    new_value JSONB,
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ip_address VARCHAR(45),
    user_agent VARCHAR(255),
    CONSTRAINT check_action_type CHECK (action_type IN ('create', 'read', 'update', 'delete', 'execute', 'login', 'logout')),
    CONSTRAINT check_resource_type CHECK (resource_type IN ('user', 'role', 'template', 'workflow', 'query', 'config', 'session'))
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_user_id ON audit_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_action_type ON audit_logs(action_type);
CREATE INDEX IF NOT EXISTS idx_audit_logs_resource_type ON audit_logs(resource_type);
CREATE INDEX IF NOT EXISTS idx_audit_logs_timestamp ON audit_logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_logs_resource_id ON audit_logs(resource_id);

-- Verification: List all new tables
SELECT 'Feature 012 tables created successfully:' AS message;
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN ('roles', 'users', 'templates', 'template_versions', 'workflows', 'workflow_steps', 'workflow_executions', 'saved_queries', 'analytics_metrics', 'audit_logs')
ORDER BY table_name;
