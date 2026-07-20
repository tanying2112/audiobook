"""Alembic migration: create missing RBAC, collaboration, and agent tables.

Adds 12 core tables for user management, team collaboration, and agent orchestration:
- users, roles, permissions, project_permissions (RBAC)
- team_members, comments, tasks, approval_requests, approval_responses, change_records (collaboration)
- agent_knowledge, agent_tasks (agent orchestration)
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import sqlite

# revision identifiers, used by Alembic.
revision = "20260719_missing_tables"
down_revision = "20260629_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ────────────────── RBAC Tables ──────────────────

    # users
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("email", sa.String(length=255), unique=True, index=True, nullable=False),
        sa.Column("username", sa.String(length=100), unique=True, index=True, nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), default=True, nullable=False),
        sa.Column("is_superuser", sa.Boolean(), default=False, nullable=False),
        sa.Column("created_at", sa.DateTime(), default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.Column("last_login", sa.DateTime(), nullable=True),
    )

    # roles
    op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("name", sa.String(length=50), unique=True, index=True, nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), default=sa.func.now(), nullable=False),
    )

    # permissions
    op.create_table(
        "permissions",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("name", sa.String(length=100), unique=True, index=True, nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), default=sa.func.now(), nullable=False),
    )

    # project_permissions
    op.create_table(
        "project_permissions",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column(
            "project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
        ),
        sa.Column(
            "role",
            sa.Enum("admin", "project_owner", "editor", "viewer", "contributor", name="role_names"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), default=sa.func.now(), nullable=False),
        sa.Column("granted_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
    )

    # Association tables for many-to-many relationships
    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("role_id", sa.Integer(), sa.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    )

    op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.Integer(), sa.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("permission_id", sa.Integer(), sa.ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
    )

    # ────────────────── Collaboration Tables ──────────────────

    # team_members
    op.create_table(
        "team_members",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("name", sa.String(length=100), nullable=False, index=True),
        sa.Column("email", sa.String(length=255), unique=True, index=True, nullable=False),
        sa.Column("role", sa.String(length=50), nullable=False, index=True),
        sa.Column("is_active", sa.Boolean(), default=True, nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True, unique=True, index=True),
        sa.Column("avatar_url", sa.String(length=500), nullable=True),
        sa.Column("skills", sqlite.JSON(), default=list, server_default="[]", nullable=False),
        sa.Column("languages", sqlite.JSON(), default=list, server_default="[]", nullable=False),
        sa.Column("created_at", sa.DateTime(), default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )

    # comments
    op.create_table(
        "comments",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "comment_type",
            sa.Enum("comment", "suggestion", "question", "issue", name="commenttype"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "author_id", sa.Integer(), sa.ForeignKey("team_members.id", ondelete="CASCADE"), nullable=False, index=True
        ),
        sa.Column("created_at", sa.DateTime(), default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True, index=True),
        sa.Column("file_path", sa.String(length=500), nullable=True),
        sa.Column("line_number", sa.Integer(), nullable=True),
        sa.Column(
            "parent_id", sa.Integer(), sa.ForeignKey("comments.id", ondelete="CASCADE"), nullable=True, index=True
        ),
        sa.Column("resolved", sa.Boolean(), default=False, nullable=False),
        sa.Column("resolved_by", sa.Integer(), sa.ForeignKey("team_members.id", ondelete="SET NULL"), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
    )

    # tasks
    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("title", sa.String(length=200), nullable=False, index=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("todo", "in_progress", "review", "done", "archived", name="taskstatus"),
            default="todo",
            nullable=False,
            index=True,
        ),
        sa.Column(
            "assignee_id",
            sa.Integer(),
            sa.ForeignKey("team_members.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "reporter_id",
            sa.Integer(),
            sa.ForeignKey("team_members.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("due_date", sa.DateTime(), nullable=True),
        sa.Column("tags", sqlite.JSON(), default=list, server_default="[]", nullable=False),
        sa.Column("priority", sa.Integer(), default=1, nullable=False),
        sa.Column("estimated_hours", sa.Float(), nullable=True),
        sa.Column("actual_hours", sa.Float(), nullable=True),
        sa.Column(
            "project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
        ),
        sa.Column(
            "parent_task_id", sa.Integer(), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True, index=True
        ),
        sa.Column("created_at", sa.DateTime(), default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )

    # Association table for task dependencies (many-to-many)
    op.create_table(
        "task_dependencies",
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("depends_on_task_id", sa.Integer(), sa.ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True),
    )

    # approval_requests
    op.create_table(
        "approval_requests",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("requester_id", sa.Integer(), sa.ForeignKey("team_members.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "approved", "rejected", "needs_changes", name="approvalstatus"),
            default="pending",
            nullable=False,
            index=True,
        ),
        sa.Column("created_at", sa.DateTime(), default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True, index=True),
        sa.Column("artifact_path", sa.String(length=500), nullable=True),
        sa.Column("required_approvals", sa.Integer(), default=1, nullable=False),
        sa.Column("auto_approve_if_unstoppable", sa.Boolean(), default=False, nullable=False),
    )

    # Association table for approval request approvers (many-to-many)
    op.create_table(
        "approval_approvers",
        sa.Column(
            "approval_request_id",
            sa.Integer(),
            sa.ForeignKey("approval_requests.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("approver_id", sa.Integer(), sa.ForeignKey("team_members.id", ondelete="CASCADE"), primary_key=True),
    )

    # approval_responses
    op.create_table(
        "approval_responses",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column(
            "approval_request_id",
            sa.Integer(),
            sa.ForeignKey("approval_requests.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "approver_id",
            sa.Integer(),
            sa.ForeignKey("team_members.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "status",
            sa.Enum("pending", "approved", "rejected", "needs_changes", name="approvalstatus_response"),
            nullable=False,
        ),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("commented_at", sa.DateTime(), default=sa.func.now(), nullable=False),
    )

    # change_records
    op.create_table(
        "change_records",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column(
            "change_type",
            sa.Enum("create", "update", "delete", "move", name="changetype"),
            nullable=False,
            index=True,
        ),
        sa.Column("entity_type", sa.String(length=50), nullable=False, index=True),
        sa.Column("entity_id", sa.Integer(), nullable=False, index=True),
        sa.Column(
            "changed_by", sa.Integer(), sa.ForeignKey("team_members.id", ondelete="CASCADE"), nullable=False, index=True
        ),
        sa.Column("changed_at", sa.DateTime(), default=sa.func.now(), nullable=False, index=True),
        sa.Column("old_state", sa.Text(), nullable=True),
        sa.Column("new_state", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), default="", nullable=False),
        sa.Column(
            "related_change_id", sa.Integer(), sa.ForeignKey("change_records.id", ondelete="SET NULL"), nullable=True
        ),
    )

    # ────────────────── Agent Tables ──────────────────

    # agent_knowledge
    op.create_table(
        "agent_knowledge",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("topic", sa.String(), index=True),
        sa.Column("knowledge", sqlite.JSON()),
        sa.Column("source_agent", sa.String()),
        sa.Column("confidence_score", sqlite.JSON()),
        sa.Column("created_at", sa.DateTime(), default=sa.func.now()),
        sa.Column("last_accessed", sa.DateTime(), nullable=True),
    )

    # agent_tasks (TaskRecord)
    op.create_table(
        "agent_tasks",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("task_type", sa.String()),
        sa.Column("input_data", sqlite.JSON()),
        sa.Column("output_data", sqlite.JSON(), nullable=True),
        sa.Column("assigned_agent", sa.String()),
        sa.Column("status", sa.String()),
        sa.Column("retries", sqlite.JSON()),
        sa.Column("created_at", sa.DateTime(), default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )

    # ────────────────── Additional Indexes ──────────────────

    # Composite index for change_records (not auto-created)
    op.create_index("ix_change_records_entity", "change_records", ["entity_type", "entity_id"])


def downgrade() -> None:
    # Drop indexes first
    indexes_to_drop = [
        "ix_change_records_entity",
    ]
    for idx in indexes_to_drop:
        try:
            op.drop_index(idx)
        except Exception:
            pass

    # Drop tables in reverse order (respecting FK constraints)
    tables_to_drop = [
        "agent_tasks",
        "agent_knowledge",
        "change_records",
        "approval_responses",
        "approval_approvers",
        "approval_requests",
        "task_dependencies",
        "tasks",
        "comments",
        "team_members",
        "role_permissions",
        "user_roles",
        "project_permissions",
        "permissions",
        "roles",
        "users",
    ]
    for table in tables_to_drop:
        try:
            op.drop_table(table)
        except Exception:
            pass
