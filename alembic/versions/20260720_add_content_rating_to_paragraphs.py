"""Add content_rating column to paragraphs table.

Revision ID: 20260720_add_content_rating_to_paragraphs
Revises: 20260720_add_project_segments
Create Date: 2026-07-20
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import sqlite

# revision identifiers, used by Alembic.
revision = "20260720_add_content_rating_to_paragraphs"
down_revision = "20260720_add_project_segments"
branch_labels = None
depends_on = None


# Create enum type for content_rating
content_rating_enum = sa.Enum(
    "儿童",
    "大众",
    "青少年",
    "成人",
    name="content_rating_enum",
    create_constraint=True,
)


def upgrade() -> None:
    # Create enum type if it doesn't exist
    bind = op.get_bind()
    # Check if enum already exists (it was created in previous migration)
    try:
        content_rating_enum.create(bind, checkfirst=True)
    except Exception:
        # Enum might already exist from project_segments migration
        pass

    # Add content_rating column to paragraphs table
    op.add_column("paragraphs", sa.Column("content_rating", content_rating_enum, default="大众", nullable=True))


def downgrade() -> None:
    # Drop column
    op.drop_column("paragraphs", "content_rating")

    # Don't drop enum - it's still used by project_segments table
