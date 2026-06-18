"""Alembic migration: create HARNESS-aligned tables.

Adds the full Project → Chapter → Paragraph → AudioSegment hierarchy
along with supporting tables for version tracking and backward compatibility.
"""

from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import sqlite

# revision identifiers, used by Alembic.
revision = "20250612_harness_models"
down_revision = "20241001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── New tables ──────────────────────────────────────────────────────────

    # projects (core entity, replaces old books)
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("author", sa.String(), nullable=True),
        sa.Column("genre", sa.String(), nullable=True),
        sa.Column("difficulty", sa.String(1), nullable=True),
        sa.Column("language", sa.String(2), nullable=False, server_default="zh"),
        sa.Column("era", sa.String(), nullable=True),
        sa.Column("total_chapters_estimated", sa.Integer(), nullable=True),
        sa.Column("global_style_notes", sa.Text(), nullable=True),
        sa.Column("story_line_summary", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column("current_stage", sa.String(), nullable=True),
        sa.Column("progress", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("total_cost_usd", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("cost_limit_per_book", sa.Float(), nullable=False, server_default="20.0"),
        sa.Column("cost_limit_per_chapter", sa.Float(), nullable=False, server_default="5.0"),
        sa.Column("created_at", sa.String(), nullable=True),
        sa.Column("updated_at", sa.String(), nullable=True),
        sa.Column("completed_at", sa.String(), nullable=True),
    )

    # chapters
    op.create_table(
        "chapters",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("index", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("analyzed_json", sqlite.JSON(), nullable=True),
        sa.Column("annotated_json", sqlite.JSON(), nullable=True),
        sa.Column("edited_json", sqlite.JSON(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("extract_status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("analyze_status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("annotate_status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("edit_status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("route_status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("synthesize_status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("quality_status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("token_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tts_chars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.String(), nullable=True),
        sa.Column("completed_at", sa.String(), nullable=True),
    )

    # characters
    op.create_table(
        "characters",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("canonical_name", sa.String(), nullable=False, index=True),
        sa.Column("aliases", sqlite.JSON(), nullable=True),
        sa.Column("gender", sa.String(), nullable=True),
        sa.Column("age_range", sa.String(), nullable=True),
        sa.Column("suggested_voice_id", sa.String(), nullable=True),
        sa.Column("sample_quote", sa.Text(), nullable=True),
    )

    # emotion_snapshots
    op.create_table(
        "emotion_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chapter", sa.Integer(), nullable=False),
        sa.Column("dominant_emotion", sa.String(), nullable=False),
        sa.Column("intensity", sa.Float(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
    )

    # audio_segments
    op.create_table(
        "audio_segments",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chapter_id", sa.Integer(), sa.ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("paragraph_id", sa.Integer(), sa.ForeignKey("paragraphs.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("file_path", sa.String(), nullable=False),
        sa.Column("format", sa.String(), nullable=False, server_default="mp3"),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        sa.Column("sample_rate", sa.Integer(), nullable=False, server_default="24000"),
        sa.Column("channels", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("engine", sa.String(), nullable=True),
        sa.Column("voice_id", sa.String(), nullable=True),
        sa.Column("prosody_overrides", sqlite.JSON(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("parent_segment_id", sa.Integer(), sa.ForeignKey("audio_segments.id"), nullable=True),
        sa.Column("quality_id", sa.Integer(), sa.ForeignKey("qualities.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )

    # feedback_records
    op.create_table(
        "feedback_records",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chapter_id", sa.Integer(), sa.ForeignKey("chapters.id", ondelete="CASCADE"), nullable=True),
        sa.Column("paragraph_id", sa.Integer(), sa.ForeignKey("paragraphs.id", ondelete="CASCADE"), nullable=True),
        sa.Column("feedback_id", sa.String(), nullable=False, unique=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("stage", sa.String(), nullable=False),
        sa.Column("input_snapshot", sqlite.JSON(), nullable=False),
        sa.Column("llm_output", sqlite.JSON(), nullable=False),
        sa.Column("corrected_output", sqlite.JSON(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("diff_summary", sa.Text(), nullable=True),
        sa.Column("pattern_tags", sqlite.JSON(), nullable=True),
        sa.Column("processed", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("promoted", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    # processing_runs
    op.create_table(
        "processing_runs",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_run_id", sa.Integer(), sa.ForeignKey("processing_runs.id"), nullable=True),
        sa.Column("config_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("prompt_versions", sqlite.JSON(), nullable=False),
        sa.Column("stages_completed", sqlite.JSON(), nullable=False),
        sa.Column("golden_score", sa.Float(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="running"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("version_tag", sa.String(), nullable=True),
        sa.Column("commit_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )

    # ── Legacy tables (backward compat for existing CRUD API tests) ─────────
    op.create_table(
        "legacy_books",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("author", sa.String(), nullable=False),
        sa.Column("language", sa.String(2), nullable=False),
        sa.Column("isbn", sa.String(), nullable=True),
    )
    op.create_table(
        "legacy_paragraphs",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("book_id", sa.Integer(), sa.ForeignKey("legacy_books.id"), nullable=False),
        sa.Column("index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("speaker", sa.String(), nullable=True),
    )
    op.create_table(
        "legacy_tts_edits",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("paragraph_id", sa.Integer(), sa.ForeignKey("legacy_paragraphs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("edited_text", sa.Text(), nullable=False),
        sa.Column("voice", sa.String(), nullable=True),
    )
    op.create_table(
        "legacy_routings",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("paragraph_id", sa.Integer(), sa.ForeignKey("legacy_paragraphs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("voice", sa.String(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
    )
    op.create_table(
        "legacy_qualities",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("tts_edit_id", sa.Integer(), sa.ForeignKey("legacy_tts_edits.id"), nullable=True),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("comments", sa.String(), nullable=True),
    )

    # ── Extend existing tables with new columns (batch mode for SQLite) ────

    # paragraphs: add HARNESS fields
    with op.batch_alter_table("paragraphs") as batch_op:
        batch_op.add_column(sa.Column("project_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("chapter_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("chapter_index", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("speaker_canonical_name", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("is_dialogue", sa.Boolean(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("emotion", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("emotion_intensity", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("speech_rate", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("pitch_shift_semitones", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("needs_sfx", sa.Boolean(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("sfx_tags", sqlite.JSON(), nullable=True))
        batch_op.add_column(sa.Column("pause_before_ms", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("pause_after_ms", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("confidence", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("notes", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("edited_text", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("edit_changes_made", sqlite.JSON(), nullable=True))
        batch_op.add_column(sa.Column("edit_forbidden_removed", sqlite.JSON(), nullable=True))
        batch_op.add_column(sa.Column("edit_confidence", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("edit_rationale", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("edit_difficulty", sa.String(1), nullable=True))
        batch_op.add_column(sa.Column("edit_forbid_edit", sa.Boolean(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("routing_engine", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("routing_voice_id", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("routing_prosody_overrides", sqlite.JSON(), nullable=True))
        batch_op.add_column(sa.Column("routing_fallback", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("routing_reasoning", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("routing_estimated_cost", sa.Float(), nullable=False, server_default="0.0"))
        batch_op.add_column(sa.Column("routing_estimated_duration", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("quality_speaker_clarity", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("quality_emotion_match", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("quality_prosody_naturalness", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("quality_text_audio_alignment", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("quality_overall_score", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("quality_issues", sqlite.JSON(), nullable=True))
        batch_op.add_column(sa.Column("quality_fix_suggestions", sqlite.JSON(), nullable=True))
        batch_op.add_column(sa.Column("quality_needs_regeneration", sa.Boolean(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("audio_segment_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("status", sa.String(), nullable=False, server_default="pending"))
        batch_op.create_foreign_key("fk_paragraphs_project", "projects", ["project_id"], ["id"], ondelete="CASCADE")
        batch_op.create_foreign_key("fk_paragraphs_chapter", "chapters", ["chapter_id"], ["id"], ondelete="CASCADE")
        batch_op.create_foreign_key("fk_paragraphs_audio_segment", "audio_segments", ["audio_segment_id"], ["id"], ondelete="SET NULL")

    # tts_edits: add HARNESS fields
    with op.batch_alter_table("tts_edits") as batch_op:
        batch_op.add_column(sa.Column("project_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("chapter_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
        batch_op.add_column(sa.Column("changes_made", sqlite.JSON(), nullable=True))
        batch_op.add_column(sa.Column("forbidden_content_removed", sqlite.JSON(), nullable=True))
        batch_op.add_column(sa.Column("confidence", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("rationale", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("difficulty", sa.String(1), nullable=True))
        batch_op.add_column(sa.Column("forbid_edit", sa.Boolean(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("source", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("llm_model", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("prompt_version", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("created_at", sa.DateTime(), nullable=True))
        batch_op.create_foreign_key("fk_tts_edits_project", "projects", ["project_id"], ["id"], ondelete="CASCADE")
        batch_op.create_foreign_key("fk_tts_edits_chapter", "chapters", ["chapter_id"], ["id"], ondelete="CASCADE")

    # routings: add HARNESS fields
    with op.batch_alter_table("routings") as batch_op:
        batch_op.add_column(sa.Column("project_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("chapter_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("engine_choice", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("voice_id", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("prosody_overrides", sqlite.JSON(), nullable=True))
        batch_op.add_column(sa.Column("fallback_engine", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("reasoning", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("estimated_cost_usd", sa.Float(), nullable=False, server_default="0.0"))
        batch_op.add_column(sa.Column("estimated_duration_ms", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("actual_engine", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("actual_cost_usd", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("actual_duration_ms", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("status", sa.String(), nullable=False, server_default="pending"))
        batch_op.add_column(sa.Column("created_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("completed_at", sa.DateTime(), nullable=True))
        batch_op.create_foreign_key("fk_routings_project", "projects", ["project_id"], ["id"], ondelete="CASCADE")
        batch_op.create_foreign_key("fk_routings_chapter", "chapters", ["chapter_id"], ["id"], ondelete="CASCADE")

    # qualities: add HARNESS fields
    with op.batch_alter_table("qualities") as batch_op:
        batch_op.add_column(sa.Column("project_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("chapter_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("paragraph_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("speaker_clarity", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("emotion_match", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("prosody_naturalness", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("text_audio_alignment", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("overall_score", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("issues", sqlite.JSON(), nullable=True))
        batch_op.add_column(sa.Column("fix_suggestions", sqlite.JSON(), nullable=True))
        batch_op.add_column(sa.Column("needs_regeneration", sa.Boolean(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("judge_model", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("judge_prompt_version", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("audio_file_path", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("audio_duration_ms", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("created_at", sa.DateTime(), nullable=True))
        batch_op.create_foreign_key("fk_qualities_project", "projects", ["project_id"], ["id"], ondelete="CASCADE")
        batch_op.create_foreign_key("fk_qualities_chapter", "chapters", ["chapter_id"], ["id"], ondelete="CASCADE")
        batch_op.create_foreign_key("fk_qualities_paragraph", "paragraphs", ["paragraph_id"], ["id"], ondelete="CASCADE")

    # Note: books table intentionally left unchanged (deprecated in favor of projects)


def downgrade() -> None:
    # First remove HARNESS columns from existing tables (before dropping
    # referenced tables so batch mode can reflect FK constraints).

    paragraph_cols = [
        "project_id", "chapter_id", "chapter_index", "speaker_canonical_name",
        "is_dialogue", "emotion", "emotion_intensity", "speech_rate",
        "pitch_shift_semitones", "needs_sfx", "sfx_tags", "pause_before_ms",
        "pause_after_ms", "confidence", "notes", "edited_text", "edit_changes_made",
        "edit_forbidden_removed", "edit_confidence", "edit_rationale", "edit_difficulty",
        "edit_forbid_edit", "routing_engine", "routing_voice_id", "routing_prosody_overrides",
        "routing_fallback", "routing_reasoning", "routing_estimated_cost",
        "routing_estimated_duration", "quality_speaker_clarity", "quality_emotion_match",
        "quality_prosody_naturalness", "quality_text_audio_alignment", "quality_overall_score",
        "quality_issues", "quality_fix_suggestions", "quality_needs_regeneration",
        "audio_segment_id", "status",
    ]
    with op.batch_alter_table("paragraphs") as batch_op:
        for col in paragraph_cols:
            try:
                batch_op.drop_column(col)
            except Exception:
                pass

    tts_edit_cols = [
        "project_id", "chapter_id", "version", "changes_made",
        "forbidden_content_removed", "confidence", "rationale", "difficulty",
        "forbid_edit", "source", "llm_model", "prompt_version", "created_at",
    ]
    with op.batch_alter_table("tts_edits") as batch_op:
        for col in tts_edit_cols:
            try:
                batch_op.drop_column(col)
            except Exception:
                pass

    routing_cols = [
        "project_id", "chapter_id", "engine_choice", "voice_id",
        "prosody_overrides", "fallback_engine", "reasoning", "estimated_cost_usd",
        "estimated_duration_ms", "actual_engine", "actual_cost_usd",
        "actual_duration_ms", "status", "created_at", "completed_at",
    ]
    with op.batch_alter_table("routings") as batch_op:
        for col in routing_cols:
            try:
                batch_op.drop_column(col)
            except Exception:
                pass

    quality_cols = [
        "project_id", "chapter_id", "paragraph_id", "speaker_clarity",
        "emotion_match", "prosody_naturalness", "text_audio_alignment",
        "overall_score", "issues", "fix_suggestions", "needs_regeneration",
        "judge_model", "judge_prompt_version", "audio_file_path",
        "audio_duration_ms", "created_at",
    ]
    with op.batch_alter_table("qualities") as batch_op:
        for col in quality_cols:
            try:
                batch_op.drop_column(col)
            except Exception:
                pass

    # Note: books table left unchanged in upgrade, so nothing to revert

    # Then drop new tables (reverse order to respect FKs)
    tables_to_drop = [
        "processing_runs", "feedback_records", "audio_segments",
        "emotion_snapshots", "characters", "chapters", "projects",
        "legacy_qualities", "legacy_routings", "legacy_tts_edits",
        "legacy_paragraphs", "legacy_books",
    ]
    for table in tables_to_drop:
        try:
            op.drop_table(table)
        except Exception:
            pass
