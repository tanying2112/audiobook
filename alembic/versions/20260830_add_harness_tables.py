"""Add harness iteration tables

Revision ID: 20260830_add_harness_tables
Revises: 20260829_add_email_verification
Create Date: 2026-08-30

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import sqlite

# revision identifiers, used by Alembic.
revision = "20260830_add_harness_tables"
down_revision = "20260829_add_email_verification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ──────────────────────────────────────────────────────────────────────────────
    # 反馈记录表
    # ──────────────────────────────────────────────────────────────────────────────
    op.create_table(
        "feedback_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("feedback_id", sa.String(64), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("chapter_id", sa.Integer(), nullable=True),
        sa.Column("paragraph_id", sa.Integer(), nullable=True),
        sa.Column("paragraph_index", sa.Integer(), nullable=True),
        sa.Column("chapter_index", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("input_snapshot", sa.JSON(), nullable=False, default={}),
        sa.Column("llm_output", sa.JSON(), nullable=False, default={}),
        sa.Column("corrected_output", sa.JSON(), nullable=False, default={}),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("diff_summary", sa.Text(), default=""),
        sa.Column("pattern_tags", sa.JSON(), default=[]),
        sa.Column("processed", sa.Boolean(), default=False, nullable=False),
        sa.Column("promoted", sa.Boolean(), default=False, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("feedback_id"),
    )
    op.create_index("ix_feedback_processed_stage", "feedback_records", ["processed", "stage"])
    op.create_index("ix_feedback_project_stage", "feedback_records", ["project_id", "stage"])

    # ──────────────────────────────────────────────────────────────────────────────
    # 金标样本表
    # ──────────────────────────────────────────────────────────────────────────────
    op.create_table(
        "golden_samples",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sample_id", sa.String(64), nullable=False),
        sa.Column("split", sa.String(16), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("input_data", sa.JSON(), nullable=False),
        sa.Column("output_data", sa.JSON(), nullable=False),
        sa.Column("rubric", sa.Text(), nullable=True),
        sa.Column("expected", sa.JSON(), nullable=True),
        sa.Column("source", sa.String(32), default="unknown", nullable=False),
        sa.Column("version", sa.Integer(), default=1, nullable=False),
        sa.Column("sample_hash", sa.String(64), nullable=False),
        sa.Column("human_verified", sa.Boolean(), default=False, nullable=False),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column("pattern_tags", sa.JSON(), default=[]),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sample_id"),
        sa.UniqueConstraint("sample_hash"),
    )
    op.create_index("ix_golden_split_stage", "golden_samples", ["split", "stage"])
    op.create_index("ix_golden_verified_stage", "golden_samples", ["human_verified", "stage"])

    # ──────────────────────────────────────────────────────────────────────────────
    # Prompt 版本表
    # ──────────────────────────────────────────────────────────────────────────────
    op.create_table(
        "prompt_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("template_path", sa.String(255), nullable=False),
        sa.Column("template_content", sa.Text(), nullable=False),
        sa.Column("exemplars", sa.JSON(), default=[]),
        sa.Column("status", sa.String(32), default="draft", nullable=False),
        sa.Column("compiled", sa.Boolean(), default=False, nullable=False),
        sa.Column("k_shot", sa.Integer(), default=3, nullable=False),
        sa.Column("selection_note", sa.Text(), default=""),
        sa.Column("eval_case_count", sa.Integer(), default=0, nullable=False),
        sa.Column("eval_mean_score", sa.Float(), default=0.0, nullable=False),
        sa.Column("eval_baseline_mean", sa.Float(), nullable=True),
        sa.Column("effect_size", sa.Float(), nullable=True),
        sa.Column("passed", sa.Boolean(), default=False, nullable=False),
        sa.Column("deployed", sa.Boolean(), default=False, nullable=False),
        sa.Column("deployed_at", sa.DateTime(), nullable=True),
        sa.Column("failed_criteria", sa.JSON(), default=[]),
        sa.Column("exemplars_source", sa.String(64), default="golden_train", nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("deployed_at", sa.DateTime(), nullable=True),
        sa.Column("rolled_back_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_prompt_stage_version", "prompt_versions", ["stage", "version"], unique=True)
    op.create_index("ix_prompt_stage_status", "prompt_versions", ["stage", "status"])

    # ──────────────────────────────────────────────────────────────────────────────
    # SOP 规则表
    # ──────────────────────────────────────────────────────────────────────────────
    op.create_table(
        "sop_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("condition", sa.JSON(), nullable=False),
        sa.Column("action", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), default="active", nullable=False),
        sa.Column("version", sa.Integer(), default=1, nullable=False),
        sa.Column("parent_rule_id", sa.String(64), nullable=True),
        sa.Column("hit_count", sa.Integer(), default=0, nullable=False),
        sa.Column("success_count", sa.Integer(), default=0, nullable=False),
        sa.Column("last_hit_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rule_id"),
    )
    op.create_index("ix_sop_stage_status", "sop_rules", ["stage", "status"])

    # ──────────────────────────────────────────────────────────────────────────────
    # 质量阈值表
    # ──────────────────────────────────────────────────────────────────────────────
    op.create_table(
        "quality_thresholds",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("threshold_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("metric_name", sa.String(32), nullable=False),
        sa.Column("operator", sa.String(8), default=">=", nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("weight", sa.Float(), default=1.0, nullable=False),
        sa.Column("distribution_stats", sa.JSON(), default={}),
        sa.Column("sample_count", sa.Integer(), default=0, nullable=False),
        sa.Column("last_calibrated_at", sa.DateTime(), nullable=True),
        sa.Column("version", sa.Integer(), default=1, nullable=False),
        sa.Column("is_active", sa.Boolean(), default=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("threshold_id"),
    )
    op.create_index("ix_quality_stage_metric", "quality_thresholds", ["stage", "metric_name"])

    # ──────────────────────────────────────────────────────────────────────────────
    # 路由权重表
    # ──────────────────────────────────────────────────────────────────────────────
    op.create_table(
        "routing_weights",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("weight_id", sa.String(64), nullable=False),
        sa.Column("character_name", sa.String(64), nullable=False),
        sa.Column("voice_id", sa.String(64), nullable=False),
        sa.Column("engine", sa.String(32), nullable=False),
        sa.Column("weight", sa.Float(), default=1.0, nullable=False),
        sa.Column("min_weight", sa.Float(), default=0.1, nullable=False),
        sa.Column("max_weight", sa.Float(), default=10.0, nullable=False),
        sa.Column("success_count", sa.Integer(), default=0, nullable=False),
        sa.Column("failure_count", sa.Integer(), default=0, nullable=False),
        sa.Column("last_failure_at", sa.DateTime(), nullable=True),
        sa.Column("last_success_at", sa.DateTime(), nullable=True),
        sa.Column("decay_on_failure", sa.Float(), default=0.9, nullable=False),
        sa.Column("min_success_for_recovery", sa.Integer(), default=5, nullable=False),
        sa.Column("min_weight", sa.Float(), default=0.1, nullable=False),
        sa.Column("max_weight", sa.Float(), default=10.0, nullable=False),
        sa.Column("min_success_for_recovery", sa.Integer(), default=5, nullable=False),
        sa.Column("min_success_for_increase", sa.Integer(), default=10, nullable=False),
        sa.Column("is_active", sa.Boolean(), default=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("weight_id"),
    )
    op.create_index("ix_routing_char_voice", "routing_weights", ["character_name", "voice_id"], unique=True)

    # ──────────────────────────────────────────────────────────────────────────────
    # 审计日志
    # ──────────────────────────────────────────────────────────────────────────────
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("username", sa.String(64), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("details", sa.JSON(), default={}, nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_timestamp", "audit_logs", ["timestamp"])
    op.create_index("ix_audit_user_type", "audit_logs", ["user_id", "event_type"])

    # ──────────────────────────────────────────────────────────────────────────────
    # 金丝雀测试
    # ──────────────────────────────────────────────────────────────────────────────
    op.create_table(
        "canary_tests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("test_id", sa.String(64), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("candidate_version", sa.Integer(), nullable=False),
        sa.Column("baseline_version", sa.Integer(), nullable=False),
        sa.Column("traffic_percentage", sa.Float(), default=10.0, nullable=False),
        sa.Column("status", sa.String(16), default="running", nullable=False),
        sa.Column("candidate_pass_rate", sa.Float(), nullable=True),
        sa.Column("baseline_pass_rate", sa.Float(), nullable=True),
        sa.Column("candidate_mean_score", sa.Float(), nullable=True),
        sa.Column("baseline_mean_score", sa.Float(), nullable=True),
        sa.Column("promoted", sa.Boolean(), default=False, nullable=False),
        sa.Column("promoted_at", sa.DateTime(), nullable=True),
        sa.Column("rolled_back_at", sa.DateTime(), nullable=True),
        sa.Column("stopped_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("test_id"),
    )
    op.create_index("ix_canary_stage_status", "canary_tests", ["stage", "status"])


def downgrade() -> None:
    op.drop_table("canary_tests")
    op.drop_index("ix_audit_user_type", table_name="audit_logs")
    op.drop_index("ix_audit_timestamp", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index("ix_routing_char_voice", table_name="routing_weights")
    op.drop_table("routing_weights")
    op.drop_index("ix_quality_stage_metric", table_name="quality_thresholds")
    op.drop_table("quality_thresholds")
    op.drop_index("ix_sop_stage_status", table_name="sop_rules")
    op.drop_table("sop_rules")
    op.drop_index("ix_prompt_stage_status", table_name="prompt_versions")
    op.drop_index("ix_prompt_stage_version", table_name="prompt_versions")
    op.drop_table("prompt_versions")
    op.drop_index("ix_golden_verified_stage", table_name="golden_samples")
    op.drop_index("ix_golden_split_stage", table_name="golden_samples")
    op.drop_table("golden_samples")
    op.drop_index("ix_feedback_project_stage", table_name="feedback_records")
    op.drop_index("ix_feedback_processed_stage", table_name="feedback_records")
    op.drop_table("feedback_records")
