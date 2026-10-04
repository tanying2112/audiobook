"""Merge password migration and content rating branches.

Revision ID: e4d685074691
Revises: 20260724_add_password_migrated, 20260720_add_content_rating_to_paragraphs
Create Date: 2026-07-24
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "e4d685074691"
down_revision = ("20260724_add_password_migrated", "20260720_add_content_rating_to_paragraphs")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Merge migration - no operations needed."""
    pass


def downgrade() -> None:
    """Merge migration - no operations needed."""
    pass