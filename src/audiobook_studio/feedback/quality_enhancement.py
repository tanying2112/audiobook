"""
E7 — 质量增强模块

包含:
1. 语义连贯性检查 (Sentence-BERT + 黄金数据统计)
2. 情感验证报告
3. 动态难度权重
4. 免费资源健康指数
5. 误报质量问题追踪
"""

import json
import logging
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# 1. 语义连贯性检查
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class SemanticCoherenceResult:
    """语义连贯性检查结果."""
    scores: List[float]
    mean_score: float
    std_score: float
    anomalies: List[int]  # 异常段落索引 (mean±2σ 之外)
    is_coherent: bool
    details: str = ""


def check_semantic_coherence(
    paragraphs: List[str],
    golden_stats: Optional[Dict[str, float]] = None,
) -> SemanticCoherenceResult:
    """检查段落间语义连贯性.

    使用简单的 TF-IDF + Cosine similarity 模拟 Sentence-BERT。
    如果 golden_stats 提供了均值/标准差，用 mean±2σ 判定异常。

    Args:
        paragraphs: 段落文本列表
        golden_stats: 黄金数据统计, 如 {"mean": 0.6, "std": 0.15}

    Returns:
        SemanticCoherenceResult
    """
    if len(paragraphs) < 2:
        return SemanticCoherenceResult(
            scores=[1.0] if paragraphs else [],
            mean_score=1.0,
            std_score=0.0,
            anomalies=[],
            is_coherent=True,
            details="段落数不足 2，跳过连贯性检查",
        )

    # Compute pairwise similarity
    scores: List[float] = []
    for i in range(len(paragraphs) - 1):
        sim = _cosine_similarity(paragraphs[i], paragraphs[i + 1])
        scores.append(sim)

    mean_score = sum(scores) / len(scores)
    variance = sum((s - mean_score) ** 2 for s in scores) / len(scores)
    std_score = math.sqrt(variance)

    # Detect anomalies using golden stats or sample stats
    if golden_stats:
        threshold_mean = golden_stats.get("mean", mean_score)
        threshold_std = golden_stats.get("std", std_score) * 2
        lower_bound = threshold_mean - threshold_std
        upper_bound = threshold_mean + threshold_std
    else:
        # Use sample statistics with generous bounds
        lower_bound = max(0.0, mean_score - 2 * std_score)
        upper_bound = min(1.0, mean_score + 2 * std_score)

    anomalies = [
        i for i, s in enumerate(scores)
        if s < lower_bound or s > upper_bound
    ]

    is_coherent = len(anomalies) < len(scores) * 0.3  # < 30% 异常

    return SemanticCoherenceResult(
        scores=scores,
        mean_score=mean_score,
        std_score=std_score,
        anomalies=anomalies,
        is_coherent=is_coherent,
        details=(
            f"共 {len(paragraphs)} 段落, {len(scores)} 个相邻对, "
            f"平均相似度 {mean_score:.3f}±{std_score:.3f}, "
            f"异常段落索引: {anomalies[:10]}{'...' if len(anomalies) > 10 else ''}"
        ),
    )


def _cosine_similarity(text_a: str, text_b: str) -> float:
    """计算两段文本的余弦相似度 (基于字符 n-gram)."""
    # Build char-level 2-gram sets (simplified TF-IDF)
    def get_ngrams(text: str, n: int = 2) -> Counter:
        return Counter(text[i:i + n] for i in range(len(text) - n + 1))

    vec_a = get_ngrams(text_a)
    vec_b = get_ngrams(text_b)

    # Compute dot product
    all_grams = set(vec_a.keys()) | set(vec_b.keys())
    dot_product = sum(vec_a[g] * vec_b[g] for g in all_grams)

    magnitude_a = math.sqrt(sum(v ** 2 for v in vec_a.values()))
    magnitude_b = math.sqrt(sum(v ** 2 for v in vec_b.values()))

    if magnitude_a == 0 or magnitude_b == 0:
        return 0.0

    return dot_product / (magnitude_a * magnitude_b)


# ═══════════════════════════════════════════════════════════════════════════
# 2. 情感验证 + 报告
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class ValidationReport:
    """验证报告."""

    total_segments: int
    emotion_distribution: Dict[str, int]
    other_emotions_count: int
    unexpected_emotions: List[Tuple[str, int]]
    validation_summary: str
    generated_at: str = ""


# Valid emotion enums for Chinese audiobooks
_VALID_EMOTIONS = {
    "neutral", "happy", "sad", "angry", "fearful",
    "surprised", "disgusted", "contemptuous",
    "anxious", "excited", "calm", "warm",
    "proud", "hopeful", "grateful", "lonely",
    "nostalgic", "playful", "serious", "sarcastic",
    "other",  # "other" 作为合法兜底枚举
}


def validate_emotions(
    annotations: List[Dict[str, Any]],
    valid_emotions: Optional[set] = None,
) -> ValidationReport:
    """验证情感标注集合.

    Args:
        annotations: 段落标注列表 (每项含 "emotion" 字段)
        valid_emotions: 合法情感集合 (默认使用 _VALID_EMOTIONS)

    Returns:
        ValidationReport 报告
    """
    emotions = valid_emotions or _VALID_EMOTIONS
    emotion_counter: Counter = Counter()
    other_count = 0
    unexpected: List[Tuple[str, int]] = []

    for ann in annotations:
        emotion = ann.get("emotion", "neutral")
        emotion_counter[emotion] += 1

        if emotion == "other":
            other_count += 1
        elif emotion not in emotions:
            unexpected.append((emotion, 1))

    total = len(annotations)

    # Aggregate unexpected emotions
    unexpected_agg: Dict[str, int] = {}
    for name, count in unexpected:
        unexpected_agg[name] = unexpected_agg.get(name, 0) + count

    unexpected_sorted = sorted(unexpected_agg.items(), key=lambda x: -x[1])

    pct = other_count / max(total, 1) * 100
    validation_summary = (
        f"验证 {total} 个标注, "
        f"{len(emotion_counter)} 种情感类型, "
        f"'other' 出现 {other_count} 次 ({pct:.1f}%), "
    )
    if unexpected_sorted:
        validation_summary += (
            f"非法情感类型: "
            f"{', '.join(f'{e}({c})' for e, c in unexpected_sorted[:5])}"
        )
    else:
        validation_summary += "所有情感类型合法"

    return ValidationReport(
        total_segments=total,
        emotion_distribution=dict(emotion_counter.most_common()),
        other_emotions_count=other_count,
        unexpected_emotions=unexpected_sorted,
        validation_summary=validation_summary,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


# ═══════════════════════════════════════════════════════════════════════════
# 3. 动态难度权重
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class DifficultyWeights:
    """动态难度权重."""
    weights: Dict[str, float]

    def get_weight(self, category: str, default: float = 1.0) -> float:
        return self.weights.get(category, default)


# Default difficulty weights
_DEFAULT_DIFFICULTY_WEIGHTS = {
    "emotion_intensity": 1.5,
    "dialogue_count": 1.2,
    "speaker_count": 1.3,
    "text_length": 1.0,
    "vocabulary_rarity": 1.4,
    "cultural_reference": 1.6,
    "narrative_complexity": 1.3,
}


def _compute_text_difficulty(text: str) -> Dict[str, float]:
    """计算文本的各项难度指标."""
    # Character-level entropy (vocabulary richness)
    char_freq: Counter = Counter(text)
    total_chars = len(text)
    entropy = -sum(
        (c / total_chars) * math.log(c / total_chars)
        for c in char_freq.values()
        if c > 0
    )

    # Sentence length
    sentences = [s.strip() for s in text.replace("!", "。").replace("?", "。").split("。") if s.strip()]
    avg_sentence_len = sum(len(s) for s in sentences) / max(len(sentences), 1)

    # Punctuation diversity
    punct = sum(1 for c in text if c in "，。！？；：、""''（）—…")
    punct_ratio = punct / max(total_chars, 1)

    return {
        "text_length": total_chars,
        "entropy": entropy,
        "avg_sentence_len": avg_sentence_len,
        "punct_ratio": punct_ratio,
        "sentence_count": len(sentences),
    }


def grade_difficulty(
    text: str,
    weights: Optional[DifficultyWeights] = None,
) -> Dict[str, Any]:
    """评估文本难度并按权重加权."""
    w = weights or DifficultyWeights(_DEFAULT_DIFFICULTY_WEIGHTS)
    metrics = _compute_text_difficulty(text)

    # Normalize metrics to 0-1 range
    length_score = min(metrics["text_length"] / 5000, 1.0)
    entropy_score = min(metrics["entropy"] / 5.0, 1.0)
    sentence_score = min(metrics["avg_sentence_len"] / 100, 1.0)

    weighted = {
        "text_length": length_score * w.get_weight("text_length"),
        "vocabulary_rarity": entropy_score * w.get_weight("vocabulary_rarity"),
        "narrative_complexity": sentence_score * w.get_weight("narrative_complexity"),
    }

    total_weight = sum(weighted.values())
    num_dims = len(weighted)
    overall = total_weight / num_dims if num_dims > 0 else 0.5

    # Difficulty level
    if overall < 0.4:
        level = "easy"
    elif overall < 0.7:
        level = "medium"
    else:
        level = "hard"

    return {
        "level": level,
        "overall_score": overall,
        "weighted_dimensions": weighted,
        "raw_metrics": metrics,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 4. 免费资源健康指数
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class FreeTierHealth:
    """免费资源健康状态."""
    healthy: bool
    cpu_count: int
    memory_gb: float
    disk_free_gb: float
    uptime_hours: float
    load_avg: Tuple[float, float, float]
    score: float  # 0-100
    warnings: List[str] = field(default_factory=list)


def get_free_tier_health() -> FreeTierHealth:
    """获取当前环境的健康指数 (0-100)."""
    import os
    import platform

    warnings: List[str] = []

    # CPU
    cpu_count = os.cpu_count() or 1
    cpu_score = min(cpu_count / 4, 1.0) * 30  # max 30 points

    # Memory (via psutil if available, else /proc/meminfo)
    memory_gb = 0.0
    try:
        import psutil
        mem = psutil.virtual_memory()
        memory_gb = mem.total / (1024 ** 3)
        mem_score = min(memory_gb / 4, 1.0) * 30
        if mem.percent > 90:
            warnings.append(f"内存使用率过高: {mem.percent:.0f}%")
    except ImportError:
        # Fallback: try reading from sysctl on macOS
        try:
            import subprocess
            result = subprocess.run(
                ["sysctl", "hw.memsize"],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                memory_bytes = int(result.stdout.split(":")[1].strip())
                memory_gb = memory_bytes / (1024 ** 3)
            else:
                memory_gb = 2.0  # conservative default
        except Exception:
            memory_gb = 2.0
        mem_score = min(memory_gb / 4, 1.0) * 30

    # Disk
    disk_free_gb = 0.0
    try:
        import shutil
        total, used, free = shutil.disk_usage("/")
        disk_free_gb = free / (1024 ** 3)
        disk_score = min(disk_free_gb / 10, 1.0) * 20  # max 20 points
        if disk_free_gb < 2:
            warnings.append(f"磁盘空间不足: {disk_free_gb:.1f} GB")
    except Exception:
        disk_score = 10

    # Uptime
    uptime_hours = 0.0
    try:
        if platform.system() == "Darwin":
            import subprocess
            result = subprocess.run(
                ["sysctl", "kern.boottime"],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                # Parse "kern.boottime: { sec = 123456, usec = 0 }"
                import re
                match = re.search(r"sec = (\d+)", result.stdout)
                if match:
                    boot_secs = int(match.group(1))
                    uptime_hours = (datetime.now().timestamp() - boot_secs) / 3600
        elif platform.system() == "Linux":
            with open("/proc/uptime") as f:
                uptime_secs = float(f.read().split()[0])
                uptime_hours = uptime_secs / 3600
    except Exception:
        pass

    uptime_score = min(uptime_hours / 24, 1.0) * 20  # max 20 points (first 24h)

    # Load average
    try:
        import os
        load = os.getloadavg()
        load_avg = (load[0], load[1], load[2])
        # penalize if load > cpu_count
        if load[0] > cpu_count * 1.5:
            warnings.append(f"系统负载过高: {load[0]:.1f} (CPU={cpu_count})")
    except (AttributeError, OSError):
        load_avg = (0.0, 0.0, 0.0)

    total_score = min(cpu_score + mem_score + disk_score + uptime_score, 100)
    healthy = total_score >= 40 and len(warnings) == 0

    return FreeTierHealth(
        healthy=healthy,
        cpu_count=cpu_count,
        memory_gb=round(memory_gb, 1),
        disk_free_gb=round(disk_free_gb, 1),
        uptime_hours=round(uptime_hours, 1),
        load_avg=load_avg,
        score=round(total_score, 1),
        warnings=warnings,
    )


# ═══════════════════════════════════════════════════════════════════════════
# 5. 误报质量问题追踪
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class FalsePositiveIssue:
    """误报质量问题记录."""
    issue_id: str
    segment_id: str
    issue_type: str
    description: str
    false_positive_reason: str
    reported_by: str  # "human" | "auto"
    created_at: str


@dataclass
class FalsePositiveTracker:
    """误报质量追踪器."""
    issues: List[FalsePositiveIssue] = field(default_factory=list)

    def record_false_positive(
        self,
        segment_id: str,
        issue_type: str,
        description: str,
        reason: str,
        reported_by: str = "human",
    ) -> FalsePositiveIssue:
        """记录一条误报."""
        import uuid

        issue = FalsePositiveIssue(
            issue_id=str(uuid.uuid4()),
            segment_id=segment_id,
            issue_type=issue_type,
            description=description,
            false_positive_reason=reason,
            reported_by=reported_by,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self.issues.append(issue)
        logger.info(
            f"False positive recorded: {issue_type} on {segment_id}: {reason[:60]}"
        )
        return issue

    def get_false_positive_rate(
        self,
        total_issues: int,
        issue_type: Optional[str] = None,
    ) -> float:
        """计算误报率."""
        if total_issues == 0:
            return 0.0

        if issue_type:
            fp_count = sum(
                1 for i in self.issues if i.issue_type == issue_type
            )
        else:
            fp_count = len(self.issues)

        return fp_count / total_issues

    def get_adjusted_quality_score(
        self,
        raw_score: float,
        total_issues: int,
        issue_type: Optional[str] = None,
    ) -> float:
        """根据误报率调整质量分数."""
        fp_rate = self.get_false_positive_rate(total_issues, issue_type)
        penalty = fp_rate * 0.2  # 每 10% 误报扣 2 分
        return max(0.0, min(1.0, raw_score - penalty))

    def get_high_fp_issues(self, threshold: float = 0.2) -> Counter:
        """获取高频误报类型 (错误率 > threshold)."""
        type_counts: Counter = Counter()
        type_fp: Counter = Counter()

        for issue in self.issues:
            type_counts[issue.issue_type] += 1
            type_fp[issue.issue_type] += 1

        high_fp: Counter = Counter()
        for issue_type, count in type_fp.items():
            total = type_counts.get(issue_type, 1)
            fp_rate = count / total
            if fp_rate > threshold:
                high_fp[issue_type] = count

        return high_fp


# Global false positive tracker
_fp_tracker: Optional[FalsePositiveTracker] = None


def get_false_positive_tracker() -> FalsePositiveTracker:
    """获取全局误报追踪器单例."""
    global _fp_tracker
    if _fp_tracker is None:
        _fp_tracker = FalsePositiveTracker()
    return _fp_tracker
