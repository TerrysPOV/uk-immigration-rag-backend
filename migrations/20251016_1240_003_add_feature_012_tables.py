"""Add Feature 012 tables: users, roles, templates, workflows, saved queries, analytics, audit logs

Revision ID: 003
Revises: 002
Create Date: 2025-10-16 12:40

Feature 012: Comprehensive Frontend Enhancement Suite
Creates database schema for:
- Role-based access control (roles, users)
- Template management (templates, template_versions)
- Workflow automation (workflows, workflow_steps, workflow_executions)
- Advanced search (saved_queries)
- Analytics dashboard (analytics_metrics)
- Admin panel (audit_logs)

All tables comply with UK data sovereignty requirements.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from datetime import datetime

# revision identifiers, used by Alembic
revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Create Feature 012 database tables.

    Order of creation respects foreign key dependencies:
    1. roles (independent)
    2. users (depends on roles)
    3. templates (depends on users)
    4. template_versions (depends on templates)
    5. workflows (depends on users)
    6. workflow_steps (depends on workflows)
    7. workflow_executions (depends on workflows, users)
    8. saved_queries (depends on users)
    9. analytics_metrics (independent)
    10. audit_logs (depends on users)
    """

    # 1. Create roles table
    op.create_table(
        'roles',
        sa.Column('role_name', sa.String(50), primary_key=True, nullable=False),
        sa.Column('permissions', JSONB, nullable=False),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('created_at', sa.TIMESTAMP, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('role_name')
    )

    # Insert default roles
    op.execute("""
        INSERT INTO roles (role_name, permissions, description) VALUES
        ('admin',
         '["users:read", "users:write", "users:delete", "config:read", "config:write", "audit:read", "templates:read", "templates:write", "templates:delete", "workflows:read", "workflows:write", "workflows:delete", "workflows:execute", "analytics:read", "search:read", "search:write", "a11y:configure", "a11y:audit"]',
         'Full system access including user management, configuration, and audit logs'),
        ('caseworker',
         '["templates:read", "templates:write", "workflows:read", "workflows:write", "workflows:execute", "analytics:read", "search:read", "search:write", "a11y:audit"]',
         'Can create, edit, and manage templates and workflows'),
        ('operator',
         '["templates:read", "workflows:read", "workflows:execute", "search:read", "search:write"]',
         'Can execute workflows and perform searches'),
        ('viewer',
         '["search:read", "templates:read"]',
         'Read-only access to search and view documents')
    """)

    # 2. Create users table
    op.create_table(
        'users',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('username', sa.VARCHAR(100), unique=True, nullable=False),
        sa.Column('email', sa.VARCHAR(255), unique=True, nullable=False),
        sa.Column('hashed_password', sa.VARCHAR(255), nullable=False),
        sa.Column('role', sa.VARCHAR(50), sa.ForeignKey('roles.role_name', ondelete='RESTRICT', onupdate='CASCADE'), nullable=False),
        sa.Column('status', sa.VARCHAR(20), nullable=False, server_default='active'),
        sa.Column('created_at', sa.TIMESTAMP, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('last_login_at', sa.TIMESTAMP, nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('username'),
        sa.UniqueConstraint('email'),
        sa.CheckConstraint("status IN ('active', 'inactive')", name='check_user_status')
    )

    # Create indexes for users
    op.create_index('idx_users_email', 'users', ['email'])
    op.create_index('idx_users_role', 'users', ['role'])
    op.create_index('idx_users_status', 'users', ['status'])

    # 3. Create templates table
    op.create_table(
        'templates',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('name', sa.VARCHAR(200), nullable=False),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('category', sa.VARCHAR(100), nullable=False),
        sa.Column('created_by', sa.String(36), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('created_at', sa.TIMESTAMP, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.TIMESTAMP, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes for templates
    op.create_index('idx_templates_category', 'templates', ['category'])
    op.create_index('idx_templates_created_by', 'templates', ['created_by'])
    op.create_index('idx_templates_is_active', 'templates', ['is_active'])

    # 4. Create template_versions table
    op.create_table(
        'template_versions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('template_id', sa.String(36), sa.ForeignKey('templates.id', ondelete='CASCADE'), nullable=False),
        sa.Column('version_number', sa.Integer, nullable=False),
        sa.Column('content', JSONB, nullable=False),
        sa.Column('change_summary', sa.Text, nullable=True),
        sa.Column('created_by', sa.String(36), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('template_id', 'version_number', name='unique_template_version')
    )

    # Create indexes for template_versions
    op.create_index('idx_template_versions_template_id', 'template_versions', ['template_id'])
    op.create_index('idx_template_versions_version_number', 'template_versions', ['version_number'])

    # 5. Create workflows table
    op.create_table(
        'workflows',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('name', sa.VARCHAR(200), nullable=False),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('trigger_type', sa.VARCHAR(50), nullable=False),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('created_by', sa.String(36), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.TIMESTAMP, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint("trigger_type IN ('manual', 'scheduled', 'event', 'webhook')", name='check_trigger_type')
    )

    # Create indexes for workflows
    op.create_index('idx_workflows_trigger_type', 'workflows', ['trigger_type'])
    op.create_index('idx_workflows_is_active', 'workflows', ['is_active'])
    op.create_index('idx_workflows_created_by', 'workflows', ['created_by'])

    # 6. Create workflow_steps table
    op.create_table(
        'workflow_steps',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('workflow_id', sa.String(36), sa.ForeignKey('workflows.id', ondelete='CASCADE'), nullable=False),
        sa.Column('step_order', sa.Integer, nullable=False),
        sa.Column('step_type', sa.VARCHAR(50), nullable=False),
        sa.Column('configuration', JSONB, nullable=False),
        sa.Column('created_at', sa.TIMESTAMP, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('workflow_id', 'step_order', name='unique_workflow_step_order'),
        sa.CheckConstraint("step_type IN ('condition', 'action', 'transform', 'delay')", name='check_step_type')
    )

    # Create indexes for workflow_steps
    op.create_index('idx_workflow_steps_workflow_id', 'workflow_steps', ['workflow_id'])
    op.create_index('idx_workflow_steps_step_order', 'workflow_steps', ['step_order'])

    # 7. Create workflow_executions table
    op.create_table(
        'workflow_executions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('workflow_id', sa.String(36), sa.ForeignKey('workflows.id', ondelete='CASCADE'), nullable=False),
        sa.Column('triggered_by', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('status', sa.VARCHAR(20), nullable=False),
        sa.Column('started_at', sa.TIMESTAMP, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('completed_at', sa.TIMESTAMP, nullable=True),
        sa.Column('error_message', sa.Text, nullable=True),
        sa.Column('execution_log', JSONB, nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint("status IN ('pending', 'running', 'completed', 'failed', 'cancelled')", name='check_execution_status')
    )

    # Create indexes for workflow_executions
    op.create_index('idx_workflow_executions_workflow_id', 'workflow_executions', ['workflow_id'])
    op.create_index('idx_workflow_executions_status', 'workflow_executions', ['status'])
    op.create_index('idx_workflow_executions_triggered_by', 'workflow_executions', ['triggered_by'])
    op.create_index('idx_workflow_executions_started_at', 'workflow_executions', ['started_at'])

    # 8. Create saved_queries table
    op.create_table(
        'saved_queries',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.VARCHAR(200), nullable=False),
        sa.Column('query_text', sa.Text, nullable=False),
        sa.Column('query_type', sa.VARCHAR(50), nullable=False),
        sa.Column('filters', JSONB, nullable=True),
        sa.Column('is_public', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('created_at', sa.TIMESTAMP, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('last_used_at', sa.TIMESTAMP, nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint("query_type IN ('simple', 'advanced', 'boolean')", name='check_query_type')
    )

    # Create indexes for saved_queries
    op.create_index('idx_saved_queries_user_id', 'saved_queries', ['user_id'])
    op.create_index('idx_saved_queries_query_type', 'saved_queries', ['query_type'])
    op.create_index('idx_saved_queries_is_public', 'saved_queries', ['is_public'])

    # 9. Create analytics_metrics table
    op.create_table(
        'analytics_metrics',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('metric_type', sa.VARCHAR(100), nullable=False),
        sa.Column('metric_value', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('timestamp', sa.TIMESTAMP, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('metadata', JSONB, nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint("metric_type IN ('search_query', 'response_time_ms', 'doc_view', 'template_usage', 'workflow_execution')", name='check_metric_type')
    )

    # Create indexes for analytics_metrics
    op.create_index('idx_analytics_metrics_metric_type', 'analytics_metrics', ['metric_type'])
    op.create_index('idx_analytics_metrics_timestamp', 'analytics_metrics', ['timestamp'])

    # 10. Create audit_logs table
    op.create_table(
        'audit_logs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('action_type', sa.VARCHAR(100), nullable=False),
        sa.Column('resource_type', sa.VARCHAR(100), nullable=False),
        sa.Column('resource_id', sa.String(36), nullable=True),
        sa.Column('old_value', JSONB, nullable=True),
        sa.Column('new_value', JSONB, nullable=True),
        sa.Column('timestamp', sa.TIMESTAMP, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('ip_address', sa.VARCHAR(45), nullable=True),
        sa.Column('user_agent', sa.VARCHAR(255), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint("action_type IN ('create', 'read', 'update', 'delete', 'execute', 'login', 'logout')", name='check_action_type'),
        sa.CheckConstraint("resource_type IN ('user', 'role', 'template', 'workflow', 'query', 'config', 'session')", name='check_resource_type')
    )

    # Create indexes for audit_logs
    op.create_index('idx_audit_logs_user_id', 'audit_logs', ['user_id'])
    op.create_index('idx_audit_logs_action_type', 'audit_logs', ['action_type'])
    op.create_index('idx_audit_logs_resource_type', 'audit_logs', ['resource_type'])
    op.create_index('idx_audit_logs_timestamp', 'audit_logs', ['timestamp'])
    op.create_index('idx_audit_logs_resource_id', 'audit_logs', ['resource_id'])


def downgrade() -> None:
    """
    Drop Feature 012 tables in reverse dependency order.
    """
    # Drop in reverse order of creation
    op.drop_table('audit_logs')
    op.drop_table('analytics_metrics')
    op.drop_table('saved_queries')
    op.drop_table('workflow_executions')
    op.drop_table('workflow_steps')
    op.drop_table('workflows')
    op.drop_table('template_versions')
    op.drop_table('templates')
    op.drop_table('users')
    op.drop_table('roles')
