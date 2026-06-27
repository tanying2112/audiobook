"""LLM 语义分析器 — 用 LLM 替代关键词匹配分析反馈.

替代 processor.py 的 _infer_pattern_tags() 关键词匹配。
通过 router.call(stage="judge") 调用 LLM 进行语义级差异分析，
理解修改的深层原因，提取可复用的改进模式。

降级策略：LLM 不可用时回退到 processor._infer_pattern_tags() 关键词匹配。
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..llm import LLMRouter, create_router
from ..schemas import FeedbackAnalysis

logger = logging.getLogger(__name__)


class LLMFeedbackAnalyzer:
    """LLM 驱动的反馈语义分析器.

    用 LLM 理解人工修正的深层原因，替代关键词匹配。
    输出 FeedbackAnalysis 结构化结果，包含：
    - pattern_tags（不限于预定义 tag）
    - semantic_summary（语义级摘要）
    - severity（严重程度）
    - actionable_instruction（可直接写入 prompt 的改进指令）
    - root_cause（根因分析）
    - confidence（置信度）
    """

    def __init__(
        self,
        router: Optional[LLMRouter] = None,
        prompt_dir: Optional[str] = None,
    ):
        self.router = router or create_router()

        # Setup Jinja2 environment (same pattern as other pipelines)
        if prompt_dir is None:
            prompt_dir = Path(__file__).parent.parent.parent.parent / "prompts"
        self.prompt_dir = Path(prompt_dir)

        self.jinja_env = Environment(
            loader=FileSystemLoader(str(self.prompt_dir)),
            autoescape=select_autoescape(),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self.jinja_env.filters["tojson"] = json.dumps

    def analyze(
        self,
        stage: str,
        llm_output: Dict[str, Any],
        corrected_output: Dict[str, Any],
        rationale: str,
        key_differences: Optional[List[str]] = None,
    ) -> FeedbackAnalysis:
        """用 LLM 分析单条反馈的语义.

        Args:
            stage: 发生反馈的管线环节
            llm_output: LLM 原始输出
            corrected_output: 人工修正后的输出
            rationale: 人工填写的修改理由
            key_differences: 已检测的差异列表（可选，辅助 LLM 理解）

        Returns:
            FeedbackAnalysis 结构化分析结果

        Raises:
            Exception: LLM 调用失败时抛出，调用方应捕获并降级到关键词匹配
        """
        if key_differences is None:
            key_differences = []

        prompt = self._build_prompt(
            stage=stage,
            llm_output=llm_output,
            corrected_output=corrected_output,
            rationale=rationale,
            key_differences=key_differences,
        )

        messages = [
            {
                "role": "system",
                "content": (
                    "你是有声书质量分析专家。分析人工修正反馈的深层原因，"
                    "提取可复用的改进模式。输出严格符合 JSON schema 的结构化结果。"
                ),
            },
            {"role": "user", "content": prompt},
        ]

        try:
            result = self.router.call(
                stage="judge",
                response_model=FeedbackAnalysis,
                messages=messages,
            )
            analysis = result.output
            logger.info(
                f"LLM 语义分析完成: stage={stage}, "
                f"tags={analysis.pattern_tags}, "
                f"severity={analysis.severity}, "
                f"confidence={analysis.confidence}"
            )
            return analysis
        except Exception as e:
            logger.error(f"LLM 语义分析失败，将降级到关键词匹配: {e}")
            raise

    def _build_prompt(
        self,
        stage: str,
        llm_output: Dict[str, Any],
        corrected_output: Dict[str, Any],
        rationale: str,
        key_differences: List[str],
    ) -> str:
        """构建分析提示词."""
        template = self.jinja_env.get_template("feedback_analysis/v1.j2")

        schema_json = FeedbackAnalysis.model_json_schema()

        return template.render(
            schema_json=schema_json,
            stage=stage,
            llm_output=llm_output,
            corrected_output=corrected_output,
            rationale=rationale,
            key_differences=key_differences,
        )

    def analyze_mock(
        self,
        stage: str,
        llm_output: Dict[str, Any],
        corrected_output: Dict[str, Any],
        rationale: str,
        key_differences: Optional[List[str]] = None,
    ) -> FeedbackAnalysis:
        """Mock 模式分析（用于测试和离线开发）.

        不调用 LLM，返回基于关键词的简单分析结果。
        用于验证集成路径和降级逻辑。
        """
        if key_differences is None:
            key_differences = []

        # 简单的关键词推断（与 processor._infer_pattern_tags 类似但输出 FeedbackAnalysis）
        tags: List[str] = []
        rationale_lower = rationale.lower()

        if any(kw in rationale_lower for kw in ["对话", "dialogue", "归属"]):
            tags.append("dialogue_attribution")
        if any(kw in rationale_lower for kw in ["情感", "情绪", "感情"]):
            if "不足" in rationale:
                tags.append("emotion_too_mild")
            elif "过度" in rationale or "过强" in rationale:
                tags.append("emotion_too_strong")
            else:
                tags.append("emotion_wrong")
        if any(kw in rationale_lower for kw in ["角色", "说话人", "speaker"]):
            tags.append("speaker_wrong")
        if any(kw in rationale_lower for kw in ["停顿", "pause"]):
            tags.append("pause_missing")
        if any(kw in rationale_lower for kw in ["机器人", "机械", "不自然"]):
            tags.append("prosody_robotic")

        return FeedbackAnalysis(
            pattern_tags=list(set(tags)),
            semantic_summary=f"[Mock] 基于关键词匹配的初步分析: {rationale[:100]}",
            severity="medium",
            actionable_instruction="",
            root_cause="[Mock] 需 LLM 分析根因",
            confidence=0.5,
        )
