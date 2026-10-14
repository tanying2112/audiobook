"""add emotion speech_rate pitch_shift_semitones to characters (P3b)

Revision ID: 20261011_add_character_prosody
Revises: 20261011_add_paragraph_sentence_overrides
Create Date: 2026-10-11

Per-character TTS prosody defaults: emotion (str), speech_rate (float 0.5-2.0),
pitch_shift_semitones (int -12..12). These drive Kokoro/EdgeTTS prosody when
paragraph routing selects a character bound to a voice.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20261011_add_character_prosody"
down_revision = "20261011_add_paragraph_sentence_overrides"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("characters", sa.Column("emotion", sa.String(), nullable=True))
    op.add_column("characters", sa.Column("speech_rate", sa.Float(), nullable=True))
    op.add_column("characters", sa.Column("pitch_shift_semitones", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("characters", "pitch_shift_semitones")
    op.drop_column("characters", "speech_rate")
    op.drop_column("characters", "emotion")