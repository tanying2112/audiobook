"""add sentence_overrides to paragraphs (v6 逐句三轴导演)

Revision ID: 20261011_add_paragraph_sentence_overrides
Revises: 20261003_add_paragraph_manual_overrides
Create Date: 2026-10-11

v6 逐句三轴导演：每段落可选的逐句韵律覆盖数组
每项: {"idx": 0, "gain_db": 4.0, "speed": 0.86, "pitch_st": 1.0,
       "voice_id": "am_onyx+am_fenrir*0.55", "pause_after_ms": 350}
字段全部可选，缺省继承段落级设置。
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.sqlite import JSON

# revision identifiers, used by Alembic.
revision = "20261011_add_paragraph_sentence_overrides"
down_revision = "20261003_add_paragraph_manual_overrides"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("paragraphs", sa.Column("sentence_overrides", JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("paragraphs", "sentence_overrides")