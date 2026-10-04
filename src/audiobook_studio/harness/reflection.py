"""反思引擎：基于 Ollama Qwen3.5-2B 的批量归因分析。

核心功能：
1. 批量分析纠错记录，输出结构化归因 JSON
2. 自动生成 SOP 规则候选
3. 生成 Prompt 改进建议
4. 生成阈值/路由调整建议
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from ..harness.storage import get_storage
from ..llm.client import LLMClient, LLMClientConfig

logger = logging.getLogger(__name__)


class ReflectionInput(BaseModel):
    """反思输入：一批纠错记录。"""

    corrections: List[Dict[str, Any]]
    stage: str
    window_days: int = 7


class ReflectionOutput(BaseModel):
    """反思输出：结构化归因分析。"""

    summary: str
    root_causes: List[Dict[str, Any]]  # 根因分析
    sop_rule_candidates: List[Dict[str, Any]]  # SOP 规则候选
    prompt_suggestions: List[Dict[str, Any]]  # Prompt 改进建议
    threshold_adjustments: List[Dict[str, Any]]  # 阈值调整建议
    routing_adjustments: List[Dict[str, Any]]  # 路由调整建议
    confidence: float  # 0-1，基于样本量和一致性


class ReflectionEngine:
    """反思引擎：批量分析纠错记录，输出结构化归因分析。

    核心流程：
    1. 收集近 N 天的纠错记录
    2. 调用 Ollama Qwen3.5-2B 进行归因分析
    3. 输出结构化归因 JSON
    4. 自动生成 SOP 规则候选、Prompt 改进建议等
    """

    def __init__(self):
        self._settings = None
        self._llm_client = None
        self._router = None

    @property
    def settings(self):
        if self._settings is None:
            from ..harness.config import get_harness_settings

            self._settings = get_harness_settings()
        return self._settings

    def _get_llm_client(self):
        """获取 LLM 客户端（懒加载）。"""
        if self._llm_client is None:
            config = LLMClientConfig(
                model=self.settings.SELF_ITERATION_LLM or self.settings.OLLAMA_DEFAULT_MODEL,
                temperature=self.settings.REFLECTION_TEMPERATURE,
                max_tokens=self.settings.REFLECTION_MAX_TOKENS,
                timeout=self.settings.OLLAMA_TIMEOUT,
                api_base=self.settings.OLLAMA_BASE_URL,
            )
            self._llm_client = LLMClient(config)
        return self._llm_client

    def _get_router(self):
        if self._router is None:
            from ..llm.router import LLMRouter

            self._router = LLMRouter()
        return self._router

    # ──────────────────────────────────────────────────────────────────────────
    # 核心反思流程
    # ──────────────────────────────────────────────────────────────────────────

    def reflect(
        self,
        corrections: List[Dict[str, Any]],
        stage: str,
        window_days: int = 7,
    ) -> Dict[str, Any]:
        """执行反思分析。

        Args:
            corrections: 纠错记录列表
            stage: pipeline stage 名
            window_days: 统计窗口天数

        Returns:
            结构化归因分析结果
        """
        if not corrections:
            return self._empty_reflection("无纠错记录")

        logger.info(
            f"[ReflectionEngine] 开始反思分析: stage={stage}, samples={len(corrections)}, window={window_days}d"
        )

        # 1. 预处理：聚合统计
        stats = self._aggregate_stats(corrections)

        # 2. 调用 LLM 进行归因分析
        reflection_prompt = self._build_reflection_prompt(stage, corrections, stats)
        llm_response = self._call_llm(reflection_prompt)

        # 3. 解析 LLM 输出
        reflection = self._parse_reflection(llm_response, stage)

        # 4. 补充统计信息
        reflection["stats"] = stats
        reflection["sample_count"] = len(corrections)
        reflection["window_days"] = 7
        reflection["timestamp"] = datetime.now(timezone.utc).isoformat()

        logger.info(
            f"[ReflectionEngine] 反思完成: stage={stage}, root_causes={len(reflection.get('root_causes', []))}, sop_candidates={len(reflection.get('sop_rule_candidates', []))}"
        )

        return reflection

    def _aggregate_stats(self, corrections: List[Dict[str, Any]]) -> Dict[str, Any]:
        """聚合统计信息。"""
        from collections import Counter

        len(corrections)
        by_source = {}
        by_stage = {}
        by_field = {}
        by_pattern = Counter()

        for c in corrections:
            src = c.get("source", "unknown")
            by_source[src] = by_source.get(src, 0) + 1

            stg = c.get("stage", "unknown")
            by_stage[stg] = by_stage.get(stg, 0) + 1

            field = c.get("field", c.get("input", {}).get("field", "unknown"))
            by_field[field] = by_field.get(field, 0) + 1

            for tag in c.get("pattern_tags", []):
                by_pattern[tag] += 1

        return {
            "total_corrections": len(corrections),
            "by_source": by_source,
            "by_stage": by_stage,
            "by_field": by_field,
            "top_patterns": by_pattern.most_common(10),
        }

    def _build_reflection_prompt(self, stage: str, corrections: List[Dict], stats: Dict) -> str:
        """构建反思提示词。"""
        # 截取前 50 条用于分析（避免超长）
        corrections[:50]

        corrections_json = json.dumps(corrections[:20], ensure_ascii=False, indent=2)
        json.dumps(stats, ensure_ascii=False, indent=2)

        prompt = f"""你是 Audiobook Studio 的质量工程师，负责分析 pipeline 阶段 {stage} 的纠错记录，输出结构化归因分析。

=== 统计概览 ===
总纠错数: {stats.get('total_corrections', 0)}
来源分布: {json.dumps(stats.get('by_source', {}), ensure_ascii=False)}
阶段分布: {json.dumps(stats.get('by_stage', {}), ensure_ascii=False)}
高频字段: {json.dumps(stats.get('by_field', {}), ensure_ascii=False)}
高频模式: {json.dumps(dict(stats.get('top_patterns', [])), ensure_ascii=False)}

=== 纠错样本（前20条） ===
{corrections_json}

=== 任务 ===
请输出 JSON 格式的归因分析，包含以下字段：
1. summary: 2-3 句话总结核心问题
2. root_causes: 根因分析列表，每项包含:
   - category: 类别 (prompt/routing/threshold/model/data)
   - description: 具体描述
   - frequency: 出现频次
   - severity: 严重程度 (high/medium/low)
   - evidence: 证据样本（引用 1-2 条具体纠错记录）
3. sop_rule_candidates: 建议新增的 SOP 规则，每项包含:
   - rule_id: 建议 ID (如 "sop_{{stage}}_{{category}}_{{n}}")
   - name: 规则名
   - stage: 适用阶段
   - condition: 触发条件 (JSON)
   - action: 执行动作 (JSON)
   - rationale: 理由
3. prompt_suggestions: Prompt 改进建议，每项包含:
   - stage: 适用阶段
   - suggestion: 具体建议
   - target_field: 目标字段
   - rationale: 理由
4. threshold_adjustments: 阈值调整建议
   - metric: 指标名
   - stage: 阶段
   - current: 当前值
   - recommended: 建议值
   - reason: 理由
4. routing_adjustments: 路由调整建议
   - character: 角色
   - voice: 声线
   - current_weight: 当前权重
   - recommended_weight: 建议权重
   - reason: 理由
5. confidence: 0-1，基于样本量和一致性

=== 输出格式要求 ===
必须输出合法 JSON，不要包含任何额外文本、解释或代码块标记。
"""

        return prompt

    def _call_llm(self, prompt: str) -> str:
        """调用 LLM 进行反思分析。"""
        try:
            client = self._get_llm_client()
            # 使用简单的文本生成
            response = client.call(
                prompt=prompt,
                response_model=str,  # 直接返回字符串
                temperature=0.1,
                max_tokens=4000,
            )
            return response if isinstance(response, str) else str(response)
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            # 返回兜底的空反思
            return json.dumps(
                {
                    "summary": "LLM 调用失败，使用兜底分析",
                    "root_causes": [],
                    "sop_rule_candidates": [],
                    "prompt_suggestions": [],
                    "threshold_adjustments": [],
                    "routing_adjustments": [],
                    "confidence": 0.1,
                }
            )

    def _parse_reflection(self, llm_response: str, stage: str) -> Dict[str, Any]:
        """解析 LLM 输出为结构化反思结果。"""
        try:
            # 尝试提取 JSON
            text = llm_response.strip()
            # 尝试提取 JSON 代码块
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            parsed = json.loads(text)
            # 确保必要字段存在
            defaults = {
                "summary": "",
                "root_causes": [],
                "sop_rule_candidates": [],
                "prompt_suggestions": [],
                "threshold_adjustments": [],
                "routing_adjustments": [],
                "confidence": 0.5,
            }
            for k, v in defaults.items():
                if k not in parsed:
                    parsed[k] = v
            return parsed
        except Exception as e:
            logger.error(f"Failed to parse reflection: {e}")
            return {
                "summary": f"解析失败: {e}",
                "root_causes": [],
                "sop_rule_candidates": [],
                "prompt_suggestions": [],
                "threshold_adjustments": [],
                "routing_adjustments": [],
                "confidence": 0.1,
            }

    def _empty_reflection(self, reason: str) -> Dict[str, Any]:
        return {
            "summary": reason,
            "root_causes": [],
            "sop_rule_candidates": [],
            "prompt_suggestions": [],
            "threshold_adjustments": [],
            "routing_adjustments": [],
            "confidence": 0.0,
            "stats": {},
            "sample_count": 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # ──────────────────────────────────────────────────────────────────────────
    # 公共入口
    # ──────────────────────────────────────────────────────────────────────────

    def reflect_on_corrections(
        self,
        corrections: List[Dict[str, Any]],
        stage: str,
        window_days: int = 7,
    ) -> Dict[str, Any]:
        """对纠错记录进行反思分析的公共入口。"""
        return self.reflect(corrections, stage, 7)

    def reflect_on_stage(
        self,
        stage: str,
        window_days: int = 7,
        max_samples: int = 200,
    ) -> Dict[str, Any]:
        """对指定 stage 的近期纠错记录进行反思。"""
        storage = get_storage()
        with storage.db.session() as session:
            from sqlalchemy import select

            from ..models import FeedbackRecord as FeedbackRecordModel

            cutoff = datetime.now(timezone.utc) - timedelta(days=7)
            records = (
                session.execute(
                    select(FeedbackRecordModel)
                    .where(
                        FeedbackRecordModel.stage == stage,
                        FeedbackRecordModel.created_at >= cutoff,
                        FeedbackRecordModel.processed.is_(True),
                    )
                    .limit(200)
                )
                .scalars()
                .all()
            )

            corrections = []
            for r in records:
                corrections.append(
                    {
                        "feedback_id": r.feedback_id,
                        "source": r.source,
                        "stage": r.stage,
                        "input_snapshot": r.input_snapshot,
                        "llm_output": r.llm_output,
                        "corrected_output": r.corrected_output,
                        "rationale": r.rationale,
                        "pattern_tags": r.pattern_tags,
                    }
                )

            return self.reflect(corrections, stage, 7)


# ──────────────────────────────────────────────────────────────────────────────
# 单例与便捷入口
# ──────────────────────────────────────────────────────────────────────────────

_reflection_engine: Optional["ReflectionEngine"] = None


def get_reflection_engine() -> "ReflectionEngine":
    global _reflection_engine
    if _reflection_engine is None:
        _reflection_engine = ReflectionEngine()
    return _reflection_engine


_reflection_engine: Optional["ReflectionEngine"] = None


def run_reflection(
    stage: str,
    corrections: Optional[List[Dict]] = None,
    window_days: int = 7,
) -> Dict[str, Any]:
    """执行反思分析的便捷入口。"""
    engine = get_reflection_engine()
    if corrections:
        return engine.reflect(corrections, stage, 7)
    else:
        return get_reflection_engine().reflect_on_stage(stage, window_days=7)


def get_reflection_engine() -> "ReflectionEngine":
    global _reflection_engine
    if _reflection_engine is None:
        _reflection_engine = ReflectionEngine()
    return _reflection_engine


_reflection_engine: Optional["ReflectionEngine"] = None


__all__ = [
    "ReflectionEngine",
    "run_reflection",
    "get_reflection_engine",
]
