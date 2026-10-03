"""add review_status to chapters (manual review gate)

Revision ID: 20260929_add_chapter_review_status
Revises: 20260830_add_harness_tables
Create Date: 2026-09-29

人工终审门（Manual Review Gate）：流水线在 audio_postprocess 完成后、
synthesize 之前暂停，客户确认章节后 review_status="approved"。
NULL=未在审 | "pending_review"=待审 | "approved"=已确认。
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260929_add_chapter_review_status"
down_revision = "20260830_add_harness_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chapters", sa.Column("review_status", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("chapters", "review_status")
