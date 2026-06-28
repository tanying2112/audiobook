"""A/B Test Interceptor — 灰度切流拦截器.

根据配置将请求路由到不同的 Prompt 版本 (v1/v2)，
支持基于用户、项目、环节的灵活分流策略。
"""

import hashlib
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Literal, Optional

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


@dataclass
class ABTestVariant:
    """A/B 测试变体配置."""

    name: str  # "control" 或 "treatment"
    version: int  # Prompt 版本号
    weight: float  # 权重 0-1
    description: str = ""


@dataclass
class ABTestConfig:
    """A/B 测试配置."""

    stage: str  # pipeline stage
    experiment_id: str
    variants: List[ABTestVariant] = field(default_factory=list)
    enabled: bool = True
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    # 定向规则
    target_books: List[str] = field(default_factory=list)  # 空 = 所有书籍
    target_users: List[str] = field(default_factory=list)  # 空 = 所有用户
    # 持久化分配
    sticky: bool = True  # 基于 hash 保持一致分配


# 默认实验配置 - 以 stage 为 key 便于查找
DEFAULT_EXPERIMENTS: Dict[str, ABTestConfig] = {
    "analyze_structure": ABTestConfig(
        stage="analyze_structure",
        experiment_id="analyze_structure_v2",
        variants=[
            ABTestVariant(
                name="control", version=1, weight=0.5, description="原版 prompt"
            ),
            ABTestVariant(
                name="treatment",
                version=2,
                weight=0.5,
                description="优化后的角色识别 prompt",
            ),
        ],
        enabled=True,
        sticky=True,
    ),
    "annotate_paragraph": ABTestConfig(
        stage="annotate_paragraph",
        experiment_id="annotate_paragraph_v2",
        variants=[
            ABTestVariant(
                name="control", version=1, weight=0.5, description="原版 prompt"
            ),
            ABTestVariant(
                name="treatment",
                version=2,
                weight=0.5,
                description="增强情感标注 prompt",
            ),
        ],
        enabled=True,
        sticky=True,
    ),
    "edit_for_tts": ABTestConfig(
        stage="edit_for_tts",
        experiment_id="edit_for_tts_v2",
        variants=[
            ABTestVariant(
                name="control", version=1, weight=0.5, description="原版 prompt"
            ),
            ABTestVariant(
                name="treatment", version=2, weight=0.5, description="更严格的断句规则"
            ),
        ],
        enabled=True,
        sticky=True,
    ),
    "tts_routing": ABTestConfig(
        stage="tts_routing",
        experiment_id="tts_routing_v2",
        variants=[
            ABTestVariant(
                name="control", version=1, weight=0.5, description="原版路由策略"
            ),
            ABTestVariant(
                name="treatment",
                version=2,
                weight=0.5,
                description="更激进的本地引擎优先",
            ),
        ],
        enabled=True,
        sticky=True,
    ),
    "quality_judge": ABTestConfig(
        stage="quality_judge",
        experiment_id="quality_judge_v2",
        variants=[
            ABTestVariant(
                name="control", version=1, weight=0.5, description="原版评分标准"
            ),
            ABTestVariant(
                name="treatment",
                version=2,
                weight=0.5,
                description="更严格的情感匹配阈值",
            ),
        ],
        enabled=True,
        sticky=True,
    ),
}


class ABTestAllocator:
    """A/B 测试分配器."""

    def __init__(self, experiments: Dict[str, ABTestConfig] = None):
        self.experiments = experiments or DEFAULT_EXPERIMENTS.copy()

    def get_variant(
        self,
        stage: str,
        book_id: str = "",
        user_id: str = "",
        request: Request = None,
    ) -> Optional[ABTestVariant]:
        """获取当前请求应分配的变体."""
        experiment = self.experiments.get(stage)
        if not experiment or not experiment.enabled:
            return None

        # 检查时间窗口
        now = datetime.now(timezone.utc)
        if experiment.start_at and now < experiment.start_at:
            return None
        if experiment.end_at and now > experiment.end_at:
            return None

        # 检查定向规则
        if experiment.target_books and book_id not in experiment.target_books:
            return None
        if experiment.target_users and user_id not in experiment.target_users:
            return None

        # 确定分配键
        if experiment.sticky:
            # 基于 book_id + user_id + experiment_id 计算一致性哈希
            key = f"{experiment.experiment_id}:{book_id}:{user_id}"
        else:
            # 纯随机
            key = f"{experiment.experiment_id}:{random.random()}"

        # 计算哈希值 (0-1)
        hash_val = int(hashlib.md5(key.encode()).hexdigest(), 16) / (2**128)

        # 根据权重分配
        cumulative = 0.0
        for variant in experiment.variants:
            cumulative += variant.weight
            if hash_val <= cumulative:
                return variant

        # 默认返回最后一个
        return experiment.variants[-1] if experiment.variants else None

    def get_prompt_version(
        self, stage: str, book_id: str = "", user_id: str = "", request: Request = None
    ) -> int:
        """获取应使用的 prompt 版本号."""
        variant = self.get_variant(stage, book_id, user_id, request)
        if variant:
            return variant.version
        return 1  # 默认版本

    def record_assignment(
        self,
        stage: str,
        variant_name: str,
        book_id: str,
        user_id: str,
        request_id: str = "",
    ):
        """记录分配结果 (用于后续分析)."""
        # 这里可以写入数据库或日志
        pass


class ABTestMiddleware(BaseHTTPMiddleware):
    """A/B 测试中间件 - 自动注入 prompt 版本到请求状态."""

    def __init__(self, app, allocator: ABTestAllocator = None):
        super().__init__(app)
        self.allocator = allocator or ABTestAllocator()

    async def dispatch(self, request: Request, call_next):
        # 提取上下文信息
        book_id = request.headers.get("X-Book-ID", "")
        user_id = request.headers.get("X-User-ID", "")

        # 尝试从路径参数获取
        if not book_id and hasattr(request, "path_params"):
            book_id = request.path_params.get("book_id", "") or request.path_params.get(
                "project_id", ""
            )

        # 为每个 pipeline stage 分配变体
        stage_versions = {}
        for stage in [
            "extract",
            "analyze_structure",
            "annotate_paragraph",
            "edit_for_tts",
            "tts_routing",
            "quality_judge",
        ]:
            version = self.allocator.get_prompt_version(
                stage, book_id, user_id, request
            )
            stage_versions[stage] = version

        # 注入到 request.state
        request.state.ab_test_versions = stage_versions
        request.state.book_id = book_id
        request.state.user_id = user_id

        # 继续处理
        response = await call_next(request)

        # 在响应头中返回分配信息 (便于调试)
        if stage_versions:
            version_header = ",".join(f"{k}={v}" for k, v in stage_versions.items())
            response.headers["X-AB-Test-Versions"] = version_header

        return response


# 依赖注入：获取当前请求的 prompt 版本
async def get_prompt_version(
    request: Request,
    stage: str,
) -> int:
    """FastAPI 依赖：获取当前请求应使用的 prompt 版本."""
    if hasattr(request.state, "ab_test_versions"):
        return request.state.ab_test_versions.get(stage, 1)
    return 1


def create_ab_test_middleware(allocator: ABTestAllocator = None):
    """工厂函数：创建中间件实例."""
    return lambda app: ABTestMiddleware(app, allocator)
