-- Migration: Feature 012 - Extend users table with role and status
-- Date: 2025-10-14
-- Description: Add role FK and status fields to support admin panel user management

-- Add role column (FK to roles table, will be added after roles table exists)
ALTER TABLE users
ADD COLUMN role VARCHAR(50);

-- Add status column with default
ALTER TABLE users
ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'active'
CHECK (status IN ('active', 'inactive'));

-- Add last_login_at timestamp
ALTER TABLE users
ADD COLUMN last_login_at TIMESTAMP NULL;

-- Create indexes for efficient queries
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);
CREATE INDEX IF NOT EXISTS idx_users_status ON users(status);
CREATE INDEX IF NOT EXISTS idx_users_last_login ON users(last_login_at DESC);

-- Add foreign key constraint to roles table (after roles table is created)
-- This constraint will be added by running:
-- ALTER TABLE users ADD CONSTRAINT fk_users_role FOREIGN KEY (role) REFERENCES roles(role_name) ON DELETE RESTRICT ON UPDATE CASCADE;

-- NOTE: The FK constraint above should be applied AFTER 012_create_roles_table.sql is executed
