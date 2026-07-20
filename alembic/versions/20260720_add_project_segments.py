"""Alembic migration: add project_segments table for OCR text segments with content rating.

Adds:
- project_segments table for extracted text segments with OCR metadata and content ratings
- content_rating_enum enum type (儿童, 大众, 青少年, 成人)

Revision ID: 20260720_add_project_segments
Revises: 20260719_missing_tables
Create Date: 2026-07-20
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import sqlite

# revision identifiers, used by Alembic.
revision = "20260720_add_project_segments"
down_revision = "20260719_missing_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create enum type for content_rating
    content_rating_enum = sa.Enum(
        "儿童",
        "大众",
        "青少年",
        "成人",
        name="content_rating_enum",
        create_constraint=True,
    )
    content_rating_enum.create(op.get_bind(), checkfirst=True)

    # Create project_segments table
    op.create_table(
        "project_segments",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column(
            "project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
        ),
        sa.Column(
            "chapter_id", sa.Integer(), sa.ForeignKey("chapters.id", ondelete="SET NULL"), nullable=True, index=True
        ),
        sa.Column("segment_index", sa.Integer(), nullable=False, index=True),
        sa.Column("source_page", sa.Integer(), nullable=True),
        sa.Column("source_format", sa.String(length=32), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False, default=0),
        sa.Column("is_ocr", sa.Boolean(), default=False, nullable=False),
        sa.Column("ocr_confidence", sa.Float(), nullable=True),
        sa.Column("ocr_languages", sqlite.JSON(), default=list, server_default="[]", nullable=False),
        sa.Column("content_rating", content_rating_enum, default="大众", nullable=False),
        sa.Column("detected_language", sa.String(length=10), nullable=True),
        sa.Column("created_at", sa.DateTime(), default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )

    # Create index for segment ordering within project
    op.create_index("ix_project_segments_project_index", "project_segments", ["project_id", "segment_index"])


def downgrade() -> None:
    # Drop index
    op.drop_index("ix_project_segments_project_index", table_name="project_segments")

    # Drop table
    op.drop_table("project_segments")

    # Drop enum type
    content_rating_enum = sa.Enum(
        "儿童",
        "大众",
        "青少年",
        "成人",
        name="content_rating_enum",
        create_constraint=True,
    )
    content_rating_enum.drop(op.get_bind(), checkfirst=True)
