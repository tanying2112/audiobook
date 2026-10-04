"""add manual_voice_id/manual_engine to paragraphs (human review overrides)

Revision ID: 20261003_add_paragraph_manual_overrides
Revises: 20260929_add_chapter_review_status
Create Date: 2026-10-03

人工终审门（Manual Review Gate）的人工逐段覆盖：客户在合成语音前可对单段
强制指定音色/引擎（NULL=不覆盖，路由按角色绑定+能力选择自动决策）。
合成时路由决策优先级：manual_voice_id/manual_engine > 角色绑定 > 自动选择。
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20261003_add_paragraph_manual_overrides"
down_revision = "20260929_add_chapter_review_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("paragraphs", sa.Column("manual_voice_id", sa.String(length=255), nullable=True))
    op.add_column("paragraphs", sa.Column("manual_engine", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("paragraphs", "manual_engine")
    op.drop_column("paragraphs", "manual_voice_id")
