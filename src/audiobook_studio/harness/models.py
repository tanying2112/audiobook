"""统一核心数据模型：马具迭代系统的核心数据结构。

统一了原本分散在 feedback/models.py、api/golden.py、feedback/loop.py 中的模型。
使用 Pydantic v2 + SQLAlchemy 2.0 风格，支持双写：SQLite (元数据/索引) + JSONL (明细/审计)。

注意：仅定义马具迭代新增的模型。现有模型（User、Role、Permission、FeedbackRecord、User、Role、Permission、ProjectPermission、AuditLog）
从原模块导入，避免重复定义。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Table, Text
from sqlalchemy.orm import Mapped, declarative_base, mapped_column, relationship

# Harness 独立 ORM 基类：与主应用 orm_base.Base 解耦，避免同名类（AuditLog/FeedbackRecord 等）
# 处于同一 declarative registry 导致 mapper 未注册 / 表无法创建。
HarnessBase = declarative_base()

from ..models.user import AuditLog as AuditLogModel
from ..models.user import Permission, ProjectPermission, Role, User, role_permissions, user_roles

# 使用主应用的 Base，避免多 metadata 冲突
from ..orm_base import Base


def utc_now() -> datetime:
    """返回 UTC 时间（去时区，用于 DB 存储）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ──────────────────────────────────────────────────────────────────────────────
# 审计日志（harness 独立表，避免与主应用 audit_logs 耦合）
# ──────────────────────────────────────────────────────────────────────────────


class AuditLog(HarnessBase):
    """harness 审计日志：安全相关事件的不可变记录。"""

    __tablename__ = "harness_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)


# ──────────────────────────────────────────────────────────────────────────────
# 反思报告
# ──────────────────────────────────────────────────────────────────────────────


class ReflectionReport(BaseModel):
    """反思引擎输出的结构化归因报告。"""

    summary: str = ""
    root_causes: List[Dict[str, Any]] = Field(default_factory=list)
    sop_rule_candidates: List[Dict[str, Any]] = Field(default_factory=list)
    prompt_suggestions: List[Dict[str, Any]] = Field(default_factory=list)
    confidence: float = 0.0
    stage: Optional[str] = None


# 晋升决策（与 harness/promotion_gate.PromotionDecision 同一实现，供外部/测试从 models 直接引用）
from .promotion_gate import PromotionDecision  # noqa: E402,F401

# ──────────────────────────────────────────────────────────────────────────────
# 枚举定义
# ──────────────────────────────────────────────────────────────────────────────


class FeedbackSource(str, Enum):
    """反馈来源。"""

    HUMAN_EDIT = "human_edit"
    QUALITY_JUDGE = "quality_judge"
    USER_RATING = "user_rating"
    AUTO_CORRECTION = "auto_correction"


class PipelineStage(str, Enum):
    """Pipeline 阶段名。"""

    EXTRACT = "extract"
    ANALYZE = "analyze"
    ANNOTATE = "annotate_paragraph"
    EDIT = "edit_for_tts"
    ROUTE = "tts_routing"
    QUALITY = "quality_judge"
    SYNTHESIZE = "synthesize"
    POSTPROCESS = "audio_postprocess"


class GoldenSplit(str, Enum):
    """金标数据集划分。"""

    TRAIN = "train"
    VAL = "val"
    TEST = "test"


class SOPRuleStatus(str, Enum):
    """SOP 规则状态。"""

    ACTIVE = "active"
    ARCHIVED = "archived"
    PENDING = "pending"


class PromptStatus(str, Enum):
    """Prompt 版本状态。"""

    DRAFT = "draft"
    CANDIDATE = "candidate"
    CANARY = "canary"
    LIVE = "live"
    ROLLED_BACK = "rolled_back"
    ARCHIVED = "archived"


class AuditEventType(str, Enum):
    """审计事件类型。"""

    USER_REGISTER = "user_register"
    USER_LOGIN = "user_login"
    USER_LOGOUT = "user_logout"
    PROMPT_COMPILED = "prompt_compiled"
    PROMPT_PROMOTED = "prompt_promoted"
    PROMPT_ROLLED_BACK = "prompt_rolled_back"
    THRESHOLD_ADJUSTED = "threshold_adjusted"
    ROUTING_WEIGHT_CHANGED = "routing_weight_changed"
    SOP_RULE_ADDED = "sop_rule_added"
    SOP_RULE_ARCHIVED = "sop_rule_archived"
    GOLDEN_SAMPLE_ADDED = "golden_sample_added"
    GOLDEN_SAMPLE_APPROVED = "golden_sample_approved"
    GOLDEN_SAMPLE_REJECTED = "golden_sample_rejected"
    CANARY_STARTED = "canary_started"
    CANARY_PROMOTED = "canary_promoted"
    CANARY_ROLLED_BACK = "canary_rolled_back"
    MODEL_SWITCHED = "model_switched"


class GoldenSplit(str, Enum):
    """金标数据集划分。"""

    TRAIN = "train"
    VAL = "val"
    TEST = "test"


class SOPRuleStatus(str, Enum):
    """SOP 规则状态。"""

    ACTIVE = "active"
    ARCHIVED = "archived"
    PENDING = "pending"


class PromptStatus(str, Enum):
    """Prompt 版本状态。"""

    DRAFT = "draft"
    CANDIDATE = "candidate"
    CANARY = "canary"
    LIVE = "live"
    ROLLED_BACK = "rolled_back"
    ARCHIVED = "archived"


# ──────────────────────────────────────────────────────────────────────────────
# 用户模型（Harness 独立，避免与主应用 User 模型冲突）
# ──────────────────────────────────────────────────────────────────────────────


class User(HarnessBase):
    """Harness 专用用户模型：用于审计日志关联。"""

    __tablename__ = "harness_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    is_superuser: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )
    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    password_migrated: Mapped[bool] = mapped_column(default=False, nullable=False)

    # Email verification
    is_email_verified: Mapped[bool] = mapped_column(default=False, nullable=False)
    email_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    email_verification_token: Mapped[Optional[str]] = mapped_column(String(512), nullable=True, index=True)
    email_verification_token_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # 注：harness 仅复用主应用用户表的列定义用于审计关联，不引入跨 registry 的关系
    #     （user_roles / role_permissions / PublishJob 等属于主应用 Base，避免 mapper 配置冲突）。


# ──────────────────────────────────────────────────────────────────────────────
# Role 模型
# ──────────────────────────────────────────────────────────────────────────────


class Role(HarnessBase):
    """角色模型。"""

    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )

    # 注：harness 不引入跨 registry 的关系（user_roles / role_permissions 属于主应用 Base）。


# ──────────────────────────────────────────────────────────────────────────────
# Permission 模型
# ──────────────────────────────────────────────────────────────────────────────


class Permission(HarnessBase):
    """权限模型。"""

    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )

    # 注：harness 不引入跨 registry 的关系（role_permissions 属于主应用 Base）。


# ──────────────────────────────────────────────────────────────────────────────
# ProjectPermission 模型
# ──────────────────────────────────────────────────────────────────────────────


class ProjectPermission(HarnessBase):
    """项目级权限。"""

    __tablename__ = "project_permissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("harness_users.id"), nullable=False, index=True)
    project_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    granted_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("harness_users.id"), nullable=True)

    # 注：harness 不引入跨 registry 的关系（Project 属于主应用 Base，避免 mapper 配置冲突）。


# ──────────────────────────────────────────────────────────────────────────────
# 金标样本（harness 自有 ORM，避免与主应用 golden_samples 耦合）
# ──────────────────────────────────────────────────────────────────────────────
class GoldenSample(HarnessBase):
    """金标样本：存入 JSONL 文件，元数据存 SQLite 以便索引/查询。"""

    __tablename__ = "golden_samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    sample_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    split: Mapped[str] = mapped_column(String(16), nullable=False, index=True)  # GoldenSplit
    stage: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    input_data: Mapped[dict] = mapped_column(JSON, nullable=False)
    output_data: Mapped[dict] = mapped_column(JSON, nullable=False)
    rubric: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    expected: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    source: Mapped[str] = mapped_column(String(32), default="unknown")
    version: Mapped[int] = mapped_column(Integer, default=1)
    sample_hash: Mapped[str] = mapped_column(String(64), index=True, unique=True)

    human_verified: Mapped[bool] = mapped_column(default=False, index=True)
    quality_score: Mapped[Optional[float]] = mapped_column(nullable=True)
    pattern_tags: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_golden_split_stage", "split", "stage"),
        Index("ix_golden_verified_stage", "human_verified", "stage"),
    )

    def compute_hash(self) -> str:
        payload = json.dumps(
            {"stage": self.stage, "input": self.input_data, "output": self.output_data},
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# ──────────────────────────────────────────────────────────────────────────────
# Prompt 版本管理 (新增)
# ──────────────────────────────────────────────────────────────────────────────


class PromptVersion(HarnessBase):
    """Prompt 版本管理：Jinja2 模板版本化。"""

    __tablename__ = "prompt_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    version: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    stage: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    template_path: Mapped[str] = mapped_column(String(255), nullable=False)
    template_content: Mapped[str] = mapped_column(Text, nullable=False)  # Jinja2 模板全文
    exemplars: Mapped[list] = mapped_column(JSON, default=list)  # few-shot 示例

    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)  # PromptStatus
    compiled: Mapped[bool] = mapped_column(default=False)
    k_shot: Mapped[int] = mapped_column(default=3)
    selection_note: Mapped[str] = mapped_column(Text, default="")

    # 评估指标
    eval_case_count: Mapped[int] = mapped_column(default=0)
    eval_mean_score: Mapped[float] = mapped_column(default=0.0)
    eval_baseline_mean: Mapped[Optional[float]] = mapped_column(nullable=True)
    effect_size: Mapped[Optional[float]] = mapped_column(nullable=True)

    # 晋升相关
    passed: Mapped[bool] = mapped_column(default=False)
    deployed: Mapped[bool] = mapped_column(default=False)
    deployed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    failed_criteria: Mapped[list] = mapped_column(JSON, default=list)

    # 元数据
    exemplars_source: Mapped[str] = mapped_column(default="golden_train")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    deployed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    rolled_back_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_prompt_stage_version", "stage", "version", unique=True),
        Index("ix_prompt_stage_status", "stage", "status"),
    )


# ──────────────────────────────────────────────────────────────────────────────
# SOP 规则库 (新增)
# ──────────────────────────────────────────────────────────────────────────────


class SOPRule(HarnessBase):
    """SOP 规则库：可版本化、可统计命中率的规则库。"""

    __tablename__ = "sop_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    rule_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 规则内容
    stage: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    condition: Mapped[dict] = mapped_column(JSON, nullable=False)  # 触发条件
    action: Mapped[dict] = mapped_column(JSON, nullable=False)  # 执行动作

    # 状态与版本
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)  # SOPRuleStatus
    version: Mapped[int] = mapped_column(default=1)
    parent_rule_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # 父规则（用于演化追踪）

    # 统计
    hit_count: Mapped[int] = mapped_column(default=0)
    success_count: Mapped[int] = mapped_column(default=0)
    last_hit_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # 元数据
    created_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (Index("ix_sop_stage_status", "stage", "status"),)


# ──────────────────────────────────────────────────────────────────────────────
# 质量阈值配置 (新增)
# ──────────────────────────────────────────────────────────────────────────────


class QualityThreshold(HarnessBase):
    """质量阈值配置：可版本化、可统计分布的阈值配置。"""

    __tablename__ = "quality_thresholds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    threshold_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)

    name: Mapped[str] = mapped_column(String(64), nullable=False)
    stage: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    # 阈值配置
    metric_name: Mapped[str] = mapped_column(String(32), nullable=False)  # dnsmos / wer / speaker_sim / ...
    operator: Mapped[str] = mapped_column(String(8), default=">=")  # >=, <=, >, <
    value: Mapped[float] = mapped_column(nullable=False)
    weight: Mapped[float] = mapped_column(default=1.0)  # 综合评分权重

    # 统计分布（用于自动校准）
    distribution_stats: Mapped[dict] = mapped_column(JSON, default=dict)  # mean, std, percentiles...
    sample_count: Mapped[int] = mapped_column(default=0)
    last_calibrated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # 版本与状态
    version: Mapped[int] = mapped_column(default=1)
    is_active: Mapped[bool] = mapped_column(default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )

    __table_args__ = (Index("ix_quality_stage_metric", "stage", "metric_name"),)


# ──────────────────────────────────────────────────────────────────────────────
# TTS 路由权重 (新增，扩展现有 RoutingWeightModel)
# ──────────────────────────────────────────────────────────────────────────────


class RoutingWeight(HarnessBase):
    """TTS 路由权重：角色→声线权重矩阵，可根据失败自动降权。"""

    __tablename__ = "routing_weights"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    weight_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)

    character_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    voice_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    engine: Mapped[str] = mapped_column(String(32), nullable=False)  # kokoro / edge / cosyvoice / vllm

    weight: Mapped[float] = mapped_column(default=1.0)  # 权重，越大越优先
    min_weight: Mapped[float] = mapped_column(default=0.1)
    max_weight: Mapped[float] = mapped_column(default=10.0)

    # 统计
    success_count: Mapped[int] = mapped_column(default=0)
    failure_count: Mapped[int] = mapped_column(default=0)
    last_failure_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_success_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # 自动降权参数
    decay_on_failure: Mapped[float] = mapped_column(default=0.9)  # 失败时乘以此系数
    min_success_for_recovery: Mapped[int] = mapped_column(default=5)  # 连续成功多少次可恢复

    is_active: Mapped[bool] = mapped_column(default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )

    __table_args__ = (Index("ix_routing_char_voice", "character_name", "voice_id", unique=True),)


# ──────────────────────────────────────────────────────────────────────────────
# 迭代报告 (从 feedback/harness.py 迁移)
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class IterationReport:
    """一轮迭代的结果摘要。"""

    stage: str
    candidate_version: int
    compiled: bool
    eval_case_count: int
    eval_mean_score: float
    eval_baseline_mean: Optional[float]
    effect_size: Optional[float]
    passed: bool
    deployed: bool
    failed_criteria: List[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stage": self.stage,
            "candidate_version": self.candidate_version,
            "compiled": self.compiled,
            "eval_case_count": self.eval_case_count,
            "eval_mean_score": self.eval_mean_score,
            "eval_baseline_mean": self.eval_baseline_mean,
            "effect_size": self.effect_size,
            "passed": self.passed,
            "deployed": self.deployed,
            "failed_criteria": list(self.failed_criteria),
            "notes": self.notes,
        }


# ──────────────────────────────────────────────────────────────────────────────
# 审计日志 (使用现有 AuditLogModel，不重复定义)
# ──────────────────────────────────────────────────────────────────────────────

# AuditLog = AuditLogModel  # 已在导入中别名

# ──────────────────────────────────────────────────────────────────────────────
# 金丝雀/AB测试 (新增)
# ──────────────────────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────────────────────
# 金丝雀/AB测试 (新增)
# ──────────────────────────────────────────────────────────────────────────────


class CanaryTest(HarnessBase):
    """金丝雀测试记录。"""

    __tablename__ = "canary_tests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    test_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)

    stage: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    candidate_version: Mapped[int] = mapped_column(nullable=False)
    baseline_version: Mapped[int] = mapped_column(nullable=False)

    traffic_percentage: Mapped[float] = mapped_column(default=10.0)  # 影子流量比例
    status: Mapped[str] = mapped_column(
        String(16), default="running", index=True
    )  # running/promoted/rolled_back/stopped

    # 指标
    candidate_pass_rate: Mapped[Optional[float]] = mapped_column(nullable=True)
    baseline_pass_rate: Mapped[Optional[float]] = mapped_column(nullable=True)
    candidate_mean_score: Mapped[Optional[float]] = mapped_column(nullable=True)
    baseline_mean_score: Mapped[Optional[float]] = mapped_column(nullable=True)

    # 决策
    promoted: Mapped[bool] = mapped_column(default=False)
    promoted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    rolled_back_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    stopped_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )

    __table_args__ = (Index("ix_canary_stage_status", "stage", "status"),)


# ──────────────────────────────────────────────────────────────────────────────
# 导出模型别名（兼容现有代码）
# ──────────────────────────────────────────────────────────────────────────────

# 现有模型别名（兼容导入）
User = User
Role = Role
Permission = Permission
ProjectPermission = ProjectPermission

# 新增模型（harness 自有 ORM，避免与主应用模型/FK 耦合）
GoldenSample = GoldenSample
PromptVersion = PromptVersion
SOPRule = SOPRule
QualityThreshold = QualityThreshold
RoutingWeight = RoutingWeight
CanaryTest = CanaryTest


# ──────────────────────────────────────────────────────────────────────────────
# 导出模型别名（兼容导入）
# ──────────────────────────────────────────────────────────────────────────────

# 现有模型别名（兼容导入）
# harness 自有 FeedbackRecord 已在文件末尾定义（harness_feedback_records 表），此处不再别名到主应用模型。
# harness 自有 AuditLog（harness_audit_logs 表），保留而不覆盖为主应用模型
# 注意：FeedbackRecord 为 harness 自有 ORM（定义在文件末尾），无需在此别名，
# 直接由类定义导出即可。
AuditLog = AuditLog

# 对外以 Base 名义导出 harness 基类（storage.create_all 依赖 Base.metadata）
Base = HarnessBase

# ──────────────────────────────────────────────────────────────────────────────
# Pydantic 模型 (API/序列化用)
# ──────────────────────────────────────────────────────────────────────────────


class CorrectionRecord(BaseModel):
    """纠错记录：用于 API/序列化。"""

    model_config = ConfigDict(from_attributes=True)

    feedback_id: str
    project_id: int
    chapter_id: Optional[int] = None
    paragraph_id: Optional[int] = None
    source: str
    stage: str
    input_snapshot: Dict[str, Any]
    llm_output: Dict[str, Any]
    corrected_output: Dict[str, Any]
    rationale: str
    diff_summary: str = ""
    pattern_tags: List[str] = []
    processed: bool = False
    promoted: bool = False
    created_at: datetime


class GoldenSampleSchema(BaseModel):
    """金标样本：API/序列化用。"""

    model_config = ConfigDict(from_attributes=True)

    sample_id: str
    split: str
    stage: str
    input_data: Dict[str, Any]
    output_data: Dict[str, Any]
    rubric: Optional[str] = None
    expected: Optional[Dict[str, Any]] = None
    source: str = "unknown"
    version: int = 1
    sample_hash: str = ""
    human_verified: bool = False
    quality_score: Optional[float] = None
    pattern_tags: List[str] = []
    created_at: datetime
    approved_at: Optional[datetime] = None


class GoldenSampleCreate(BaseModel):
    """创建金标样本请求。"""

    split: str  # train/val/test
    stage: str
    input_data: Dict[str, Any]
    output_data: Dict[str, Any]
    rubric: Optional[str] = None
    expected: Optional[Dict[str, Any]] = None
    source: str = "unknown"
    quality_score: Optional[float] = None
    pattern_tags: List[str] = []


class GoldenSampleBatch(BaseModel):
    """批量金标样本。"""

    samples: List[GoldenSampleCreate]


class GoldenDatasetStats(BaseModel):
    """金标数据集统计。"""

    train_count: int = 0
    val_count: int = 0
    test_count: int = 0
    total_count: int = 0
    by_stage: Dict[str, Dict[str, int]] = {}  # split -> stage -> count


class SOPRuleCreate(BaseModel):
    """创建 SOP 规则请求。"""

    rule_id: str
    name: str
    description: Optional[str] = None
    stage: str
    condition: Dict[str, Any]
    action: Dict[str, Any]
    parent_rule_id: Optional[str] = None
    created_by: Optional[int] = None


class SOPRuleUpdate(BaseModel):
    """更新 SOP 规则请求。"""

    name: Optional[str] = None
    description: Optional[str] = None
    condition: Optional[Dict[str, Any]] = None
    action: Optional[Dict[str, Any]] = None
    status: Optional[str] = None


class SOPRuleOut(BaseModel):
    """SOP 规则输出。"""

    model_config = ConfigDict(from_attributes=True)

    rule_id: str
    name: str
    description: Optional[str] = None
    stage: str
    condition: Dict[str, Any]
    action: Dict[str, Any]
    status: str
    version: int
    parent_rule_id: Optional[str] = None
    hit_count: int = 0
    success_count: int = 0
    last_hit_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    archived_at: Optional[datetime] = None


class PromptVersionOut(BaseModel):
    """Prompt 版本输出。"""

    model_config = ConfigDict(from_attributes=True)

    version: int
    stage: str
    template_path: str
    template_content: str
    exemplars: List[Dict[str, Any]] = []
    status: str
    compiled: bool = False
    k_shot: int = 3
    selection_note: str = ""
    eval_case_count: int = 0
    eval_mean_score: float = 0.0
    eval_baseline_mean: Optional[float] = None
    effect_size: Optional[float] = None
    passed: bool = False
    deployed: bool = False
    deployed_at: Optional[datetime] = None
    failed_criteria: List[str] = []
    created_at: datetime
    deployed_at: Optional[datetime] = None
    rolled_back_at: Optional[datetime] = None


class PromptCompileRequest(BaseModel):
    """编译候选 prompt 请求。"""

    stage: str
    k: int = 3
    exemplars_source: str = "golden_train"


class PromptCompileResponse(BaseModel):
    version: int
    stage: str
    exemplars_count: int
    selection_note: str
    template_path: str


class GoldenSampleCreateRequest(BaseModel):
    """创建金标样本请求。"""

    split: str  # train/val/test
    stage: str
    input_data: Dict[str, Any]
    output_data: Dict[str, Any]
    rubric: Optional[str] = None
    expected: Optional[Dict[str, Any]] = None
    source: str = "unknown"
    quality_score: Optional[float] = None
    pattern_tags: List[str] = []


class GoldenStatsResponse(BaseModel):
    train_count: int = 0
    val_count: int = 0
    test_count: int = 0
    total_count: int = 0
    by_stage: Dict[str, Dict[str, int]] = {}


class SOPRuleHitRecord(BaseModel):
    """SOP 规则命中记录。"""

    rule_id: str
    hit_count: int
    success_count: int
    success_rate: float
    last_hit_at: Optional[datetime] = None


class ThresholdCalibrationRequest(BaseModel):
    stage: str
    metric_name: str
    new_value: Optional[float] = None
    auto_calibrate: bool = True


class ThresholdCalibrationResponse(BaseModel):
    metric_name: str
    old_value: float
    new_value: float
    distribution_stats: Dict[str, Any]
    sample_count: int
    recommended: bool
    reason: str


class RoutingWeightUpdate(BaseModel):
    character_name: str
    voice_id: str
    weight_delta: float  # 正为增权，负为降权
    reason: str


class CanaryStartRequest(BaseModel):
    stage: str
    candidate_version: int
    baseline_version: int
    traffic_percentage: float = 10.0
    auto_promote: bool = True


class CanaryDecision(BaseModel):
    test_id: str
    action: str  # promote / rollback / continue
    reason: str
    promoted_at: Optional[datetime] = None


class AuditLogEntry(BaseModel):
    """审计日志条目。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    event_type: str
    user_id: Optional[int] = None
    username: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    details: Dict[str, Any] = {}
    timestamp: datetime


class WeeklyReportResponse(BaseModel):
    week_start: str
    week_end: str
    total_iterations: int
    total_promotions: int
    total_rollbacks: int
    golden_samples_added: int
    sop_rules_added: int
    prompts_promoted: List[Dict[str, Any]]
    threshold_changes: List[Dict[str, Any]]
    routing_changes: List[Dict[str, Any]]
    golden_stats: Dict[str, int]
    top_patterns: List[Dict[str, Any]]
    issues: List[str] = []


class HealthCheckResponse(BaseModel):
    status: str  # healthy / degraded / unhealthy
    components: Dict[str, str]
    golden_stats: Dict[str, int]
    active_canaries: int
    pending_promotions: int
    timestamp: str


# ──────────────────────────────────────────────────────────────────────────────
# 纠错反馈记录 (harness 自有表，避免与主应用 feedback_records 列定义冲突)
# ──────────────────────────────────────────────────────────────────────────────


class FeedbackRecord(HarnessBase):
    """马具迭代反馈记录：双写 SQLite + JSONL。

    独立于主应用 feedback_records（列定义不同），仅承载马具迭代所需的
    paragraph_index / chapter_index 等字段。
    """

    __tablename__ = "harness_feedback_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    feedback_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    project_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    chapter_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    paragraph_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    paragraph_index: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    chapter_index: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    source: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    stage: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    input_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    llm_output: Mapped[dict] = mapped_column(JSON, nullable=False)
    corrected_output: Mapped[dict] = mapped_column(JSON, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    diff_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    pattern_tags: Mapped[list] = mapped_column(JSON, default=list)

    processed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    promoted: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )
