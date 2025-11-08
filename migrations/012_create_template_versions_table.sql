-- Migration: Feature 012 - Create template_versions table
-- Date: 2025-10-14
-- Description: Historical snapshots of template changes for version control

CREATE TABLE IF NOT EXISTS template_versions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    template_id UUID NOT NULL,
    version_number INTEGER NOT NULL,
    content_snapshot JSONB NOT NULL,
    change_description TEXT NULL,
    author UUID NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- FK constraints
    CONSTRAINT fk_template_versions_template FOREIGN KEY (template_id) REFERENCES templates(id) ON DELETE CASCADE,
    CONSTRAINT fk_template_versions_author FOREIGN KEY (author) REFERENCES users(id) ON DELETE RESTRICT,

    -- Ensure version numbers are sequential and unique per template
    CONSTRAINT unique_template_version UNIQUE (template_id, version_number)
);

-- Create indexes for efficient version queries
CREATE INDEX IF NOT EXISTS idx_template_versions_template ON template_versions(template_id, version_number DESC);
CREATE INDEX IF NOT EXISTS idx_template_versions_created_at ON template_versions(created_at DESC);

-- Trigger to auto-increment version_number
CREATE OR REPLACE FUNCTION auto_increment_version_number()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.version_number IS NULL THEN
        SELECT COALESCE(MAX(version_number), 0) + 1
        INTO NEW.version_number
        FROM template_versions
        WHERE template_id = NEW.template_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_auto_increment_version_number
BEFORE INSERT ON template_versions
FOR EACH ROW
EXECUTE FUNCTION auto_increment_version_number();
