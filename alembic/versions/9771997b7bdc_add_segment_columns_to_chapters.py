"""add segment columns to chapters

Revision ID: 9771997b7bdc
Revises: 20260720_add_project_segments
Create Date: 2026-08-22 10:09:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9771997b7bdc'
down_revision = '20260720_add_project_segments'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add segment columns to chapters table
    op.add_column('chapters', sa.Column('segment_data', sa.JSON(), nullable=True))
    op.add_column('chapters', sa.Column('segment_strategy', sa.String(length=50), nullable=True))
    op.add_column('chapters', sa.Column('segment_stats', sa.JSON(), nullable=True))
    op.add_column('chapters', sa.Column('segment_status', sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column('chapters', 'segment_status')
    op.drop_column('chapters', 'segment_stats')
    op.drop_column('chapters', 'segment_strategy')
    op.drop_column('chapters', 'segment_data')
