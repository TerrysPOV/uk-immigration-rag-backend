"""Add Feature 024 tables (prompt_versions, production_prompt, audit_logs for playground)

Revision ID: 005_feature_024
Revises: 004_feature_010
Create Date: 2025-11-02 15:00:00

Feature 024: Template Workflow Playground
- prompt_versions table with soft-delete and optimistic locking
- production_prompt singleton table with optimistic locking
- audit_logs table for playground operations compliance tracking
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '005_feature_024'
down_revision = '004_feature_010'
branch_labels = None
depends_on = None


def upgrade():
    """Create Feature 024 tables and indexes."""

    # Enable UUID extension if not already enabled
    op.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\";")

    # ============================================================================
    # Table: prompt_versions
    # ============================================================================
    op.create_table(
        'prompt_versions',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('name', sa.VARCHAR(length=255), nullable=False),
        sa.Column('prompt_text', sa.Text(), nullable=False),
        sa.Column('author_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('deleted_at', sa.TIMESTAMP(), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False, server_default=sa.text('1')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name', name='uq_prompt_version_name'),
        sa.CheckConstraint('length(prompt_text) <= 10000', name='ck_prompt_text_length'),
        sa.ForeignKeyConstraint(['author_id'], ['users.id'], name='fk_prompt_version_author', ondelete='RESTRICT')
    )

    # Indexes for prompt_versions
    op.create_index(
        'idx_prompt_versions_deleted',
        'prompt_versions',
        ['deleted_at'],
        unique=False
    )

    op.create_index(
        'idx_prompt_versions_author',
        'prompt_versions',
        ['author_id'],
        unique=False
    )

    # ============================================================================
    # Table: production_prompt (Singleton)
    # ============================================================================
    op.create_table(
        'production_prompt',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('prompt_text', sa.Text(), nullable=False),
        sa.Column('promoted_at', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('promoted_by', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('previous_backup_path', sa.VARCHAR(length=500), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False, server_default=sa.text('1')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['promoted_by'], ['users.id'], name='fk_production_prompt_promoter', ondelete='RESTRICT')
    )

    # Ensure only one row in production_prompt table
    op.create_index(
        'idx_production_prompt_singleton',
        'production_prompt',
        ['id'],
        unique=True
    )

    # ============================================================================
    # Table: audit_logs (Feature 024 playground operations)
    # ============================================================================
    op.create_table(
        'playground_audit_logs',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('event_type', sa.VARCHAR(length=50), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('prompt_version_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('outcome', sa.VARCHAR(length=20), nullable=False),
        sa.Column('context', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('timestamp', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint("event_type IN ('test_analysis', 'save_version', 'promote', 'delete_version')", name='ck_audit_log_event_type'),
        sa.CheckConstraint("outcome IN ('success', 'failure')", name='ck_audit_log_outcome'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_audit_log_user', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['prompt_version_id'], ['prompt_versions.id'], name='fk_audit_log_prompt_version', ondelete='SET NULL')
    )

    # Indexes for playground_audit_logs
    op.create_index(
        'idx_playground_audit_logs_timestamp',
        'playground_audit_logs',
        [sa.text('timestamp DESC')],
        unique=False
    )

    op.create_index(
        'idx_playground_audit_logs_user',
        'playground_audit_logs',
        ['user_id'],
        unique=False
    )

    op.create_index(
        'idx_playground_audit_logs_event_type',
        'playground_audit_logs',
        ['event_type'],
        unique=False
    )

    # ============================================================================
    # Insert Default Production Prompt (Singleton Row)
    # ============================================================================
    # Note: This requires a system user to exist. We'll use a placeholder.
    # The actual default prompt should be loaded from template_prompt_IMPROVED.md
    op.execute("""
        INSERT INTO production_prompt (id, prompt_text, promoted_by)
        VALUES (
            1,
            'Default production prompt for template workflow analysis. This will be replaced by the actual prompt from template_prompt_IMPROVED.md during deployment.',
            (SELECT id FROM users WHERE email = 'system@gov.uk' LIMIT 1)
        );
    """)

    # ============================================================================
    # Trigger: Hard-delete old soft-deleted prompts (30-day retention)
    # ============================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION hard_delete_old_prompts()
        RETURNS TRIGGER AS $$
        BEGIN
            -- Delete soft-deleted prompts older than 30 days
            DELETE FROM prompt_versions
            WHERE deleted_at IS NOT NULL
              AND deleted_at < NOW() - INTERVAL '30 days';

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # Trigger runs daily (via PostgreSQL scheduler or external cron)
    # For now, just create the function - scheduling is done externally


def downgrade():
    """Drop Feature 024 tables, indexes, triggers, and functions."""

    # Drop function
    op.execute("DROP FUNCTION IF EXISTS hard_delete_old_prompts();")

    # Drop indexes (automatically dropped with tables, but explicit for clarity)
    op.drop_index('idx_playground_audit_logs_event_type', table_name='playground_audit_logs')
    op.drop_index('idx_playground_audit_logs_user', table_name='playground_audit_logs')
    op.drop_index('idx_playground_audit_logs_timestamp', table_name='playground_audit_logs')
    op.drop_index('idx_production_prompt_singleton', table_name='production_prompt')
    op.drop_index('idx_prompt_versions_author', table_name='prompt_versions')
    op.drop_index('idx_prompt_versions_deleted', table_name='prompt_versions')

    # Drop tables
    op.drop_table('playground_audit_logs')
    op.drop_table('production_prompt')
    op.drop_table('prompt_versions')
