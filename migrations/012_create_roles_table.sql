-- Migration: Feature 012 - Create roles table
-- Date: 2025-10-14
-- Description: Permission levels for role-based access control (RBAC)

CREATE TABLE IF NOT EXISTS roles (
    role_name VARCHAR(50) PRIMARY KEY,
    permissions JSONB NOT NULL,
    description TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Create index on created_at for audit queries
CREATE INDEX IF NOT EXISTS idx_roles_created_at ON roles(created_at DESC);

-- Insert default roles with permissions
INSERT INTO roles (role_name, permissions, description) VALUES
(
    'admin',
    '["users:read", "users:write", "users:delete", "config:read", "config:write", "audit:read", "templates:read", "templates:write", "templates:delete", "workflows:read", "workflows:write", "workflows:execute"]'::JSONB,
    'Full system administration privileges'
),
(
    'editor',
    '["templates:read", "templates:write", "workflows:read", "workflows:write", "workflows:execute"]'::JSONB,
    'Can create and manage templates and workflows'
),
(
    'operator',
    '["templates:read", "workflows:read", "workflows:execute"]'::JSONB,
    'Can execute workflows and view templates'
),
(
    'viewer',
    '["templates:read", "workflows:read"]'::JSONB,
    'Read-only access to templates and workflows'
)
ON CONFLICT (role_name) DO NOTHING;

-- Now add the FK constraint to users table (after roles are created)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'users') THEN
        -- Add FK constraint if it doesn't already exist
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.table_constraints
            WHERE constraint_name = 'fk_users_role' AND table_name = 'users'
        ) THEN
            ALTER TABLE users
            ADD CONSTRAINT fk_users_role
            FOREIGN KEY (role)
            REFERENCES roles(role_name)
            ON DELETE RESTRICT
            ON UPDATE CASCADE;
        END IF;
    END IF;
END $$;
