-- Migration: Feature 012 - Create templates table
-- Date: 2025-10-14
-- Description: Document templates with placeholder variables for generation

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS templates (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    template_name VARCHAR(200) NOT NULL,
    description TEXT NULL,
    content_structure JSONB NOT NULL,
    placeholders TEXT[] NOT NULL DEFAULT '{}',
    permission_level VARCHAR(20) NOT NULL DEFAULT 'private' CHECK (permission_level IN ('public', 'private', 'shared')),
    created_by UUID NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP NULL,
    current_version INTEGER NOT NULL DEFAULT 1,

    -- FK to users table (will be added after users table exists)
    CONSTRAINT fk_templates_created_by FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE RESTRICT
);

-- Create indexes for efficient queries
CREATE INDEX IF NOT EXISTS idx_templates_created_by ON templates(created_by);
CREATE INDEX IF NOT EXISTS idx_templates_permission ON templates(permission_level);
CREATE INDEX IF NOT EXISTS idx_templates_deleted_at ON templates(deleted_at) WHERE deleted_at IS NULL;

-- Full-text search index on template name and description
CREATE INDEX IF NOT EXISTS idx_templates_search ON templates USING gin(to_tsvector('english', template_name || ' ' || COALESCE(description, '')));

-- Update updated_at trigger
CREATE OR REPLACE FUNCTION update_templates_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_templates_updated_at
BEFORE UPDATE ON templates
FOR EACH ROW
EXECUTE FUNCTION update_templates_updated_at();
