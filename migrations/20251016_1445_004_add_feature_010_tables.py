"""Add Feature 010 tables (search_history, saved_searches)

Revision ID: 004_feature_010
Revises: 003_feature_012
Create Date: 2025-10-16 14:45:00

Feature 010: Enhanced Search and Filtering UI
- search_history table with auto-pruning at 50 entries
- saved_searches table with 20 search limit per user
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '004_feature_010'
down_revision = '003_feature_012'
branch_labels = None
depends_on = None


def upgrade():
    """Create Feature 010 tables and indexes."""

    # ============================================================================
    # Table: search_history
    # ============================================================================
    op.create_table(
        'search_history',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.VARCHAR(length=100), nullable=False),
        sa.Column('query_text', sa.VARCHAR(length=500), nullable=False),
        sa.Column('filters', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('result_count', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('timestamp', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.CheckConstraint('result_count >= 0', name='ck_search_history_result_count_positive'),
        sa.PrimaryKeyConstraint('id')
    )

    # Index for user_id + timestamp (DESC) for fast retrieval
    op.create_index(
        'idx_search_history_user_timestamp',
        'search_history',
        ['user_id', sa.text('timestamp DESC')],
        unique=False
    )

    # ============================================================================
    # Table: saved_searches
    # ============================================================================
    op.create_table(
        'saved_searches',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('user_id', sa.VARCHAR(length=100), nullable=False),
        sa.Column('name', sa.VARCHAR(length=100), nullable=False),
        sa.Column('search_query', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('last_executed_at', sa.TIMESTAMP(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'name', name='uq_saved_search_user_name')
    )

    # Index for user_id for fast lookup
    op.create_index(
        'idx_saved_searches_user',
        'saved_searches',
        ['user_id'],
        unique=False
    )

    # Index for created_at (DESC) for ordering
    op.create_index(
        'idx_saved_searches_created',
        'saved_searches',
        [sa.text('created_at DESC')],
        unique=False
    )

    # ============================================================================
    # Auto-Pruning Function for search_history
    # ============================================================================
    op.execute("""
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
    """)

    # Trigger to auto-prune after each insert
    op.execute("""
        CREATE TRIGGER trigger_auto_prune_search_history
            AFTER INSERT ON search_history
            FOR EACH ROW
            EXECUTE FUNCTION auto_prune_search_history();
    """)

    # ============================================================================
    # Validation Function for saved_searches limit
    # ============================================================================
    op.execute("""
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
    """)

    # Trigger to validate limit before insert
    op.execute("""
        CREATE TRIGGER trigger_validate_saved_searches_limit
            BEFORE INSERT ON saved_searches
            FOR EACH ROW
            EXECUTE FUNCTION validate_saved_searches_limit();
    """)


def downgrade():
    """Drop Feature 010 tables, indexes, and triggers."""

    # Drop triggers first
    op.execute("DROP TRIGGER IF EXISTS trigger_auto_prune_search_history ON search_history;")
    op.execute("DROP TRIGGER IF EXISTS trigger_validate_saved_searches_limit ON saved_searches;")

    # Drop functions
    op.execute("DROP FUNCTION IF EXISTS auto_prune_search_history();")
    op.execute("DROP FUNCTION IF EXISTS validate_saved_searches_limit();")

    # Drop indexes (automatically dropped with tables, but explicit for clarity)
    op.drop_index('idx_saved_searches_created', table_name='saved_searches')
    op.drop_index('idx_saved_searches_user', table_name='saved_searches')
    op.drop_index('idx_search_history_user_timestamp', table_name='search_history')

    # Drop tables
    op.drop_table('saved_searches')
    op.drop_table('search_history')
