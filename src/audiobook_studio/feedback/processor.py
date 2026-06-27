"""
E2 — 差异分析 Agent

分析 FeedbackRecord 中的 llm_output vs corrected_output 差异，
提取 pattern_tags，生成可操作的改进建议。
"""

import json
import logging
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from ..models import FeedbackRecord as FeedbackRecordModel

logger = logging.getLogger(__name__)

# ── LLM 语义分析器（懒加载，避免循环导入）────────────────────────────────────
_llm_analyzer = None


def _get_llm_analyzer():
    """懒加载 LLMFeedbackAnalyzer，避免初始化时强制创建 router."""
    global _llm_analyzer
    if _llm_analyzer is None:
        try:
            from .llm_analyzer import LLMFeedbackAnalyzer
            _llm_analyzer = LLMFeedbackAnalyzer()
            logger.info("LLMFeedbackAnalyzer 初始化成功")
        except Exception as e:
            logger.warning(f"LLMFeedbackAnalyzer 初始化失败，将使用关键词匹配降级: {e}")
            _llm_analyzer = False  # 标记为不可用
    return _llm_analyzer if _llm_analyzer is not False else None

# ── Known pattern tag taxonomy ────────────────────────────────────────────────

PATTERN_TAXONOMY = {
    # Text editing patterns
    "dialogue_attribution": "错标/漏标对话归属",
    "emotion_too_mild": "情感强度不足",  
    "emotion_too_strong": "情感强度过高",
    "emotion_wrong": "情感类型错误",
    "speaker_wrong": "说话人识别错误",
    "text_colloquial": "文本过于书面化，需口语化",
    "text_formal": "文本过于口语化，需书面化",
    "pause_missing": "缺少必要停顿",
    "pause_too_long": "停顿过长",
    "sfx_missing": "缺少场景音效标记",
    "sfx_wrong": "场景音效类型错误",
    # Quality patterns
    "clipping": "音频削波失真",
    "silence": "异常静音段",
    "low_volume": "音量过低",
    "duration_mismatch": "时长与预期不符",
    "prosody_robotic": "韵律不自然 (机器人感)",
    "prosody_flat": "语调平淡",
    # Structure patterns
    "chapter_split_wrong": "章节划分错误",
    "character_missing": "遗漏角色定义",
    "summary_incomplete": "故事概述不完整",
}


@dataclass
class DiffAnalysisResult:
    """单条反馈的差异分析结果."""

    feedback_id: str
    stage: str
    pattern_tags: List[str]
    diff_summary: str
    similarity_score: float  # 0-1, lower = more difference
    key_differences: List[str]
    # ── LLM 语义分析扩展字段 ──
    semantic_summary: Optional[str] = None
    root_cause: Optional[str] = None
    actionable_instruction: Optional[str] = None
    severity: Optional[str] = None  # "high" | "medium" | "low"
    confidence: Optional[float] = None  # 0-1
    analysis_source: str = "keyword"  # "llm" | "keyword"


@dataclass 
class AggregateAnalysis:
    """聚合多个反馈的统计结果."""

    total_analyzed: int
    pattern_frequency: Dict[str, int]  # pattern_tag → count
    stage_distribution: Dict[str, int]  # stage → count
    top_patterns: List[Tuple[str, int]]  # sorted by frequency
    recommendations: List[str]
    generated_at: str


def _compute_text_similarity(a: str, b: str) -> float:
    """计算两段文本的相似度 (0-1)."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _extract_key_differences(
    llm_output: Dict[str, Any],
    corrected_output: Dict[str, Any],
) -> List[str]:
    """提取两字典间的关键差异."""
    diffs: List[str] = []
    all_keys = set(llm_output.keys()) | set(corrected_output.keys())

    for key in all_keys:
        llm_val = llm_output.get(key)
        cor_val = corrected_output.get(key)

        if llm_val is None and cor_val is not None:
            diffs.append(f"LLM 缺失字段 '{key}'")
        elif llm_val is not None and cor_val is None:
            diffs.append(f"LLM 多余字段 '{key}'")
        elif llm_val != cor_val:
            if isinstance(llm_val, str) and isinstance(cor_val, str):
                sim = _compute_text_similarity(llm_val, cor_val)
                if sim < 0.8:
                    diffs.append(
                        f"字段 '{key}' 文本差异大 (相似度 {sim:.2f}): "
                        f"LLM='{llm_val[:60]}...' → 修正='{cor_val[:60]}...'"
                    )
            else:
                diffs.append(
                    f"字段 '{key}' 值不同: {llm_val} → {cor_val}"
                )

    return diffs


def _infer_pattern_tags(
    stage: str,
    llm_output: Dict[str, Any],
    corrected_output: Dict[str, Any],
    rationale: str,
    key_diffs: List[str],
) -> List[str]:
    """从差异和修改理由推断 pattern_tags."""
    tags: List[str] = []
    rationale_lower = rationale.lower()

    # Universal patterns (apply to all stages)
    if any(kw in rationale_lower for kw in ["对话", "dialogue", "归属", "角色"]):
        tags.append("dialogue_attribution")
    if any(kw in rationale_lower for kw in ["情感", "情绪", "感情"]):
        if "强烈" in rationale_lower or "不足" in rationale_lower or "太淡" in rationale_lower:
            tags.append("emotion_too_mild")
        elif "过度" in rationale_lower or "过强" in rationale_lower or "太强" in rationale_lower:
            tags.append("emotion_too_strong")
        else:
            tags.append("emotion_wrong")
    if any(kw in rationale_lower for kw in ["角色", "说话人", "speaker", "旁白"]):
        tags.append("speaker_wrong")
    if any(kw in rationale_lower for kw in ["停顿", "pause", "停顿"]):
        if "缺少" in rationale_lower or "加" in rationale_lower or "需要" in rationale_lower:
            tags.append("pause_missing")
        else:
            tags.append("pause_too_long")
    if any(kw in rationale_lower for kw in ["音效", "sfx", "场景"]):
        if "缺少" in rationale_lower or "加" in rationale_lower or "需要" in rationale_lower:
            tags.append("sfx_missing")
        else:
            tags.append("sfx_wrong")
    if any(kw in rationale_lower for kw in ["机器人", "机械", "不自然", "生硬"]):
        tags.append("prosody_robotic")
    if any(kw in rationale_lower for kw in ["平淡", "flat", "单调"]):
        tags.append("prosody_flat")

    # Stage-specific patterns
    if stage in ("edit_for_tts", "annotate", "translate"):
        if any(kw in rationale_lower for kw in ["口语", "书面", "自然", "翻译"]):
            llm_text = str(llm_output.get("edited_text", llm_output.get("text", "")))
            cor_text = str(corrected_output.get("edited_text", corrected_output.get("text", "")))
            if len(llm_text) > len(cor_text):
                tags.append("text_colloquial")
            else:
                tags.append("text_formal")

    elif stage == "quality_judge":
        if any(kw in rationale_lower for kw in ["削波", "clipping", "失真"]):
            tags.append("clipping")
        if any(kw in rationale_lower for kw in ["静音", "silence"]):
            tags.append("silence")
        if any(kw in rationale_lower for kw in ["音量", "volume", "过低"]):
            tags.append("low_volume")
        if any(kw in rationale_lower for kw in ["时长", "duration"]):
            tags.append("duration_mismatch")

    # Deduplicate
    return list(set(tags))


def analyze_single_feedback(
    record: FeedbackRecordModel,
) -> DiffAnalysisResult:
    """分析单条反馈记录.

    优先使用 LLM 语义分析（LLMFeedbackAnalyzer），失败时降级到关键词匹配（_infer_pattern_tags）。
    """
    llm_output = record.llm_output or {}
    corrected_output = record.corrected_output or {}

    key_diffs = _extract_key_differences(llm_output, corrected_output)

    # Compute overall similarity
    similarities: List[float] = []
    for key in set(llm_output.keys()) & set(corrected_output.keys()):
        llm_val = llm_output.get(key)
        cor_val = corrected_output.get(key)
        if isinstance(llm_val, str) and isinstance(cor_val, str):
            similarities.append(_compute_text_similarity(llm_val, cor_val))
        elif isinstance(llm_val, (int, float)) and isinstance(cor_val, (int, float)):
            similarities.append(1.0 if llm_val == cor_val else 0.0)

    avg_similarity = sum(similarities) / len(similarities) if similarities else 1.0

    # ── 优先尝试 LLM 语义分析 ──────────────────────────────────────────────
    pattern_tags: List[str] = []
    semantic_summary: Optional[str] = None
    root_cause: Optional[str] = None
    actionable_instruction: Optional[str] = None
    severity: Optional[str] = None
    confidence: Optional[float] = None
    analysis_source = "keyword"  # 默认降级模式

    analyzer = _get_llm_analyzer()
    if analyzer is not None:
        try:
            fa = analyzer.analyze(
                stage=record.stage,
                llm_output=llm_output,
                corrected_output=corrected_output,
                rationale=record.rationale or "",
                key_differences=key_diffs,
            )
            pattern_tags = fa.pattern_tags
            semantic_summary = fa.semantic_summary
            root_cause = fa.root_cause
            actionable_instruction = fa.actionable_instruction
            severity = fa.severity
            confidence = fa.confidence
            analysis_source = "llm"
            logger.debug(f"LLM 语义分析成功: {record.feedback_id} → {pattern_tags}")
        except Exception as e:
            logger.warning(
                f"LLM 语义分析失败，降级到关键词匹配: {record.feedback_id} — {e}"
            )
            pattern_tags = _infer_pattern_tags(
                stage=record.stage,
                llm_output=llm_output,
                corrected_output=corrected_output,
                rationale=record.rationale or "",
                key_diffs=key_diffs,
            )
    else:
        # LLM 分析器不可用，直接使用关键词匹配
        pattern_tags = _infer_pattern_tags(
            stage=record.stage,
            llm_output=llm_output,
            corrected_output=corrected_output,
            rationale=record.rationale or "",
            key_diffs=key_diffs,
        )

    # Generate diff summary
    diff_summary_parts = [f"Stage: {record.stage}"]
    if key_diffs:
        diff_summary_parts.append(f"Key diffs ({len(key_diffs)}):")
        diff_summary_parts.extend(f"  - {d}" for d in key_diffs[:5])
    if pattern_tags:
        diff_summary_parts.append(f"Patterns: {', '.join(pattern_tags)}")
    if semantic_summary:
        diff_summary_parts.append(f"Summary: {semantic_summary}")
    if root_cause:
        diff_summary_parts.append(f"Root cause: {root_cause}")
    if actionable_instruction:
        diff_summary_parts.append(f"Action: {actionable_instruction}")
    diff_summary_parts.append(f"Analysis source: {analysis_source}")

    diff_summary = "\n".join(diff_summary_parts)

    return DiffAnalysisResult(
        feedback_id=record.feedback_id,
        stage=record.stage,
        pattern_tags=pattern_tags,
        diff_summary=diff_summary,
        similarity_score=avg_similarity,
        key_differences=key_diffs,
        semantic_summary=semantic_summary,
        root_cause=root_cause,
        actionable_instruction=actionable_instruction,
        severity=severity,
        confidence=confidence,
        analysis_source=analysis_source,
    )


def analyze_batch(
    db: Session,
    project_id: Optional[int] = None,
    limit: int = 500,
) -> AggregateAnalysis:
    """批量分析未处理的反馈记录."""
    from .collector import list_unprocessed_feedback, mark_feedback_processed

    records = list_unprocessed_feedback(db, project_id=project_id, limit=limit)
    if not records:
        return AggregateAnalysis(
            total_analyzed=0,
            pattern_frequency={},
            stage_distribution={},
            top_patterns=[],
            recommendations=["没有未处理的反馈记录"],
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    pattern_counter: Counter = Counter()
    stage_counter: Counter = Counter()
    all_patterns: List[str] = []

    for record in records:
        result = analyze_single_feedback(record)
        stage_counter[result.stage] += 1

        for tag in result.pattern_tags:
            pattern_counter[tag] += 1
            all_patterns.append(tag)

        # Mark as processed with analysis results
        mark_feedback_processed(
            db,
            feedback_id=record.feedback_id,
            pattern_tags=result.pattern_tags,
            diff_summary=result.diff_summary,
        )

    db.commit()

    # Generate recommendations
    top_patterns = pattern_counter.most_common(10)
    recommendations = _generate_recommendations(top_patterns, stage_counter)

    logger.info(
        f"Batch analysis complete: {len(records)} records, "
        f"{len(pattern_counter)} unique patterns, "
        f"top: {top_patterns[:3]}"
    )

    return AggregateAnalysis(
        total_analyzed=len(records),
        pattern_frequency=dict(pattern_counter),
        stage_distribution=dict(stage_counter),
        top_patterns=top_patterns,
        recommendations=recommendations,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


def _generate_recommendations(
    top_patterns: List[Tuple[str, int]],
    stage_dist: Dict[str, int],
) -> List[str]:
    """基于分析结果生成改进建议."""
    recs: List[str] = []

    if not top_patterns:
        return ["未检测到显著模式"]

    for pattern, count in top_patterns[:5]:
        description = PATTERN_TAXONOMY.get(pattern, pattern)
        recs.append(
            f"高频模式 [{pattern}] ({count}次): {description}"
        )

    # Stage-specific recommendations
    for stage, count in stage_dist.items():
        if count >= 5:
            recs.append(
                f"环节 '{stage}' 有 {count} 条反馈，建议优先优化该环节的 Prompt"
            )

    return recs


def get_trend_report(
    db: Session,
    project_id: Optional[int] = None,
    days: int = 7,
) -> Dict[str, Any]:
    """生成趋势报告: 指定天数内的反馈统计."""
    from datetime import datetime, timedelta, timezone

    since = datetime.now(timezone.utc) - timedelta(days=days)
    query = db.query(FeedbackRecordModel).filter(
        FeedbackRecordModel.created_at >= since
    )
    if project_id:
        query = query.filter(FeedbackRecordModel.project_id == project_id)

    records = query.all()
    pattern_counter: Counter = Counter()
    stage_counter: Counter = Counter()
    source_counter: Counter = Counter()

    for r in records:
        stage_counter[r.stage] += 1
        source_counter[r.source] += 1
        for tag in (r.pattern_tags or []):
            pattern_counter[tag] += 1

    return {
        "period_days": days,
        "total_feedback": len(records),
        "pattern_frequency": dict(pattern_counter.most_common(15)),
        "stage_distribution": dict(stage_counter),
        "source_distribution": dict(source_counter),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
