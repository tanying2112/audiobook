"""Add updated_at column to RBAC tables (roles, permissions, project_permissions).

Revision ID: add_updated_at_to_rbac
Revises: 9edcfa5cce69
Create Date: 2026-08-23

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import sqlite

# revision identifiers, used by Alembic.
revision = 'add_updated_at_to_rbac'
down_revision = '9edcfa5cce69'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add updated_at to roles
    with op.batch_alter_table('roles') as batch_op:
        batch_op.add_column(sa.Column('updated_at', sa.DateTime(), 
            default=sa.func.now(), onupdate=sa.func.now(), nullable=False,
            server_default=sa.func.now()))
    
    # Add updated_at to permissions
    with op.batch_alter_table('permissions') as batch_op:
        batch_op.add_column(sa.Column('updated_at', sa.DateTime(), 
            default=sa.func.now(), onupdate=sa.func.now(), nullable=False,
            server_default=sa.func.now()))
    
    # Add updated_at to project_permissions
    with op.batch_alter_table('project_permissions') as batch_op:
        batch_op.add_column(sa.Column('updated_at', sa.DateTime(), 
            default=sa.func.now(), onupdate=sa.func.now(), nullable=False,
            server_default=sa.func.now()))


def downgrade() -> None:
    with op.batch_alter_table('project_permissions') as batch_op:
        batch_op.drop_column('updated_at')
    with op.batch_alter_table('permissions') as batch_op:
        batch_op.drop_column('updated_at')
    with op.batch_alter_table('roles') as batch_op:
        batch_op.drop_column('updated_at')
