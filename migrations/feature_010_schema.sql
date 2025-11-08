-- Feature 010: Enhanced Search and Filtering UI
-- Database Schema for Search History and Saved Searches
-- Generated: 2025-10-16
-- Author: Claude (Feature 010 Implementation)

-- Enable UUID extension if not already enabled
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================================
-- Table: search_history
-- Purpose: User search history with auto-pruning at 50 entries
-- ============================================================================

CREATE TABLE IF NOT EXISTS search_history (
    id BIGSERIAL PRIMARY KEY,
    user_id VARCHAR(100) NOT NULL,
    query_text VARCHAR(500) NOT NULL,
    filters JSONB NOT NULL DEFAULT '{}'::jsonb,
    result_count INTEGER NOT NULL DEFAULT 0,
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT ck_search_history_result_count_positive CHECK (result_count >= 0)
);

-- Index for fast user lookup with timestamp ordering
CREATE INDEX IF NOT EXISTS idx_search_history_user_timestamp
    ON search_history (user_id, timestamp DESC);

COMMENT ON TABLE search_history IS 'User search history with automatic pruning at 50 entries per user';
COMMENT ON COLUMN search_history.user_id IS 'User identifier from JWT token';
COMMENT ON COLUMN search_history.query_text IS 'Search query string (max 500 chars)';
COMMENT ON COLUMN search_history.filters IS 'Applied filters as JSONB: {document_type: [], date_range: {}, source: []}';
COMMENT ON COLUMN search_history.result_count IS 'Number of results returned';
COMMENT ON COLUMN search_history.timestamp IS 'Search execution time';

-- ============================================================================
-- Table: saved_searches
-- Purpose: User-defined saved searches with name uniqueness
-- ============================================================================

CREATE TABLE IF NOT EXISTS saved_searches (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id VARCHAR(100) NOT NULL,
    name VARCHAR(100) NOT NULL,
    search_query JSONB NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_executed_at TIMESTAMP,

    CONSTRAINT uq_saved_search_user_name UNIQUE (user_id, name)
);

-- Index for fast user lookup
CREATE INDEX IF NOT EXISTS idx_saved_searches_user
    ON saved_searches (user_id);

-- Index for creation date ordering
CREATE INDEX IF NOT EXISTS idx_saved_searches_created
    ON saved_searches (created_at DESC);

COMMENT ON TABLE saved_searches IS 'User-defined saved searches with max 20 per user';
COMMENT ON COLUMN saved_searches.id IS 'Primary key (UUID)';
COMMENT ON COLUMN saved_searches.user_id IS 'User identifier from JWT token';
COMMENT ON COLUMN saved_searches.name IS 'User-defined search name (unique per user, 1-100 chars)';
COMMENT ON COLUMN saved_searches.search_query IS 'Full search query with filters as JSONB: {query_text, filters}';
COMMENT ON COLUMN saved_searches.created_at IS 'Creation timestamp';
COMMENT ON COLUMN saved_searches.last_executed_at IS 'Last execution timestamp (updated when search is run)';

-- ============================================================================
-- Auto-Pruning Function for search_history
-- ============================================================================

CREATE OR REPLACE FUNCTION auto_prune_search_history()
RETURNS TRIGGER AS $$
BEGIN
    -- Keep only the latest 50 entries per user
    DELETE FROM search_history
    WHERE id IN (
        SELECT id
        FROM search_history
        WHERE user_id = NEW.user_id
        ORDER BY timestamp DESC
        OFFSET 50
    );

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to auto-prune after each insert
DROP TRIGGER IF EXISTS trigger_auto_prune_search_history ON search_history;
CREATE TRIGGER trigger_auto_prune_search_history
    AFTER INSERT ON search_history
    FOR EACH ROW
    EXECUTE FUNCTION auto_prune_search_history();

COMMENT ON FUNCTION auto_prune_search_history() IS 'Auto-prune search history to keep only latest 50 entries per user';

-- ============================================================================
-- Validation Function for saved_searches limit
-- ============================================================================

CREATE OR REPLACE FUNCTION validate_saved_searches_limit()
RETURNS TRIGGER AS $$
DECLARE
    user_search_count INTEGER;
BEGIN
    -- Count existing saved searches for user
    SELECT COUNT(*) INTO user_search_count
    FROM saved_searches
    WHERE user_id = NEW.user_id;

    -- Enforce 20 saved search limit
    IF user_search_count >= 20 THEN
        RAISE EXCEPTION 'Maximum 20 saved searches per user. User % has % searches.',
            NEW.user_id, user_search_count;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to validate limit before insert
DROP TRIGGER IF EXISTS trigger_validate_saved_searches_limit ON saved_searches;
CREATE TRIGGER trigger_validate_saved_searches_limit
    BEFORE INSERT ON saved_searches
    FOR EACH ROW
    EXECUTE FUNCTION validate_saved_searches_limit();

COMMENT ON FUNCTION validate_saved_searches_limit() IS 'Enforce 20 saved searches limit per user';

-- ============================================================================
-- Grants (adjust user as needed for production)
-- ============================================================================

-- Grant permissions to application user (adjust as needed)
GRANT SELECT, INSERT, UPDATE, DELETE ON search_history TO postgres;
GRANT SELECT, INSERT, UPDATE, DELETE ON saved_searches TO postgres;
GRANT USAGE, SELECT ON SEQUENCE search_history_id_seq TO postgres;

-- ============================================================================
-- Sample Data (for development/testing - remove in production)
-- ============================================================================

-- Sample search history entries
INSERT INTO search_history (user_id, query_text, filters, result_count)
VALUES
    ('dev-admin-123', 'visa requirements', '{"document_type": ["guidance"]}', 42),
    ('dev-admin-123', 'passport renewal', '{"document_type": ["form"], "date_range": {"preset": "last_6_months"}}', 15),
    ('dev-user-456', 'immigration rules', '{"source": ["home_office"]}', 87)
ON CONFLICT DO NOTHING;

-- Sample saved searches
INSERT INTO saved_searches (user_id, name, search_query)
VALUES
    ('dev-admin-123', 'Recent visa guidance', '{"query_text": "visa requirements", "filters": {"document_type": ["guidance"], "date_range": {"preset": "last_6_months"}}}'),
    ('dev-admin-123', 'Passport forms', '{"query_text": "passport", "filters": {"document_type": ["form"]}}'),
    ('dev-user-456', 'Home Office guidance', '{"query_text": "immigration", "filters": {"source": ["home_office"]}}')
ON CONFLICT (user_id, name) DO NOTHING;

-- ============================================================================
-- Verification Queries
-- ============================================================================

-- Verify tables created
SELECT
    table_name,
    (SELECT COUNT(*) FROM information_schema.columns WHERE table_name = t.table_name) as column_count
FROM information_schema.tables t
WHERE table_schema = 'public'
    AND table_name IN ('search_history', 'saved_searches')
ORDER BY table_name;

-- Verify indexes created
SELECT
    tablename,
    indexname,
    indexdef
FROM pg_indexes
WHERE schemaname = 'public'
    AND tablename IN ('search_history', 'saved_searches')
ORDER BY tablename, indexname;

-- Verify sample data
SELECT 'search_history' as table_name, COUNT(*) as row_count FROM search_history
UNION ALL
SELECT 'saved_searches' as table_name, COUNT(*) as row_count FROM saved_searches;
