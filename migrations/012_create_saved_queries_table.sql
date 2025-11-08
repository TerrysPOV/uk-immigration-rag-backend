-- Migration: Feature 012 - Create saved_queries table
-- Date: 2025-10-14
-- Description: User-saved complex search queries for reuse

CREATE TABLE IF NOT EXISTS saved_queries (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    query_name VARCHAR(200) NOT NULL,
    query_syntax TEXT NOT NULL,
    field_filters JSONB NULL,
    boolean_operators JSONB NOT NULL,
    created_by UUID NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_executed_at TIMESTAMP NULL,
    execution_count INTEGER NOT NULL DEFAULT 0,

    -- FK to users table
    CONSTRAINT fk_saved_queries_created_by FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE CASCADE
);

-- Create indexes for efficient query retrieval
CREATE INDEX IF NOT EXISTS idx_saved_queries_user ON saved_queries(created_by, last_executed_at DESC);
CREATE INDEX IF NOT EXISTS idx_saved_queries_created_at ON saved_queries(created_at DESC);

-- Full-text search index on query name and syntax
CREATE INDEX IF NOT EXISTS idx_saved_queries_search ON saved_queries USING gin(to_tsvector('english', query_name || ' ' || query_syntax));

-- Validate field_filters structure
CREATE OR REPLACE FUNCTION validate_field_filters()
RETURNS TRIGGER AS $$
DECLARE
    filter_key TEXT;
BEGIN
    IF NEW.field_filters IS NOT NULL THEN
        -- Validate that filter keys are from allowed list
        FOR filter_key IN SELECT jsonb_object_keys(NEW.field_filters)
        LOOP
            IF filter_key NOT IN ('title', 'content', 'metadata', 'author', 'date') THEN
                RAISE EXCEPTION 'Invalid field_filters key: %. Allowed keys: title, content, metadata, author, date', filter_key;
            END IF;
        END LOOP;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_validate_field_filters
BEFORE INSERT OR UPDATE ON saved_queries
FOR EACH ROW
EXECUTE FUNCTION validate_field_filters();
