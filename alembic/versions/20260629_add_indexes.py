"""Add missing database indexes for query performance.

Revision ID: 20260629_indexes
Revises: 20250612_harness_models
Create Date: 2026-06-29
"""

from alembic import op

revision = "20260629_indexes"
down_revision = "20250612_harness_models"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Chapter indexes
    op.create_index("ix_chapters_project_id", "chapters", ["project_id"])
    op.create_index("ix_chapters_index", "chapters", ["index"])

    # Paragraph indexes
    op.create_index("ix_paragraphs_project_id", "paragraphs", ["project_id"])
    op.create_index("ix_paragraphs_chapter_id", "paragraphs", ["chapter_id"])
    op.create_index("ix_paragraphs_index", "paragraphs", ["index"])

    # AudioSegment indexes
    op.create_index("ix_audio_segments_project_id", "audio_segments", ["project_id"])
    op.create_index("ix_audio_segments_chapter_id", "audio_segments", ["chapter_id"])
    op.create_index("ix_audio_segments_paragraph_id", "audio_segments", ["paragraph_id"])

    # FeedbackRecord indexes
    op.create_index("ix_feedback_records_project_id", "feedback_records", ["project_id"])
    op.create_index("ix_feedback_records_source", "feedback_records", ["source"])
    op.create_index("ix_feedback_records_stage", "feedback_records", ["stage"])
    op.create_index("ix_feedback_records_processed", "feedback_records", ["processed"])

    # Quality index
    op.create_index("ix_qualities_paragraph_id", "qualities", ["paragraph_id"])


def downgrade() -> None:
    op.drop_index("ix_qualities_paragraph_id")
    op.drop_index("ix_feedback_records_processed")
    op.drop_index("ix_feedback_records_stage")
    op.drop_index("ix_feedback_records_source")
    op.drop_index("ix_feedback_records_project_id")
    op.drop_index("ix_audio_segments_paragraph_id")
    op.drop_index("ix_audio_segments_chapter_id")
    op.drop_index("ix_audio_segments_project_id")
    op.drop_index("ix_paragraphs_index")
    op.drop_index("ix_paragraphs_chapter_id")
    op.drop_index("ix_paragraphs_project_id")
    op.drop_index("ix_chapters_index")
    op.drop_index("ix_chapters_project_id")
