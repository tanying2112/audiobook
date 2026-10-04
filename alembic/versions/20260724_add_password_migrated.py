"""Alembic migration: add password_migrated column to users table (SEC-002).

Adds a boolean column to track which user passwords have been migrated
from legacy SHA-256 to bcrypt. Default is False for existing users.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260724_add_password_migrated"
down_revision = "20260720_add_project_segments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add password_migrated column to users table
    op.add_column(
        "users",
        sa.Column("password_migrated", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    # Remove password_migrated column
    op.drop_column("users", "password_migrated")