"""Similarity and quality metrics computation for promotion gate.

包含：
- 输出相似度计算 (_compute_output_similarity)
- 字符 n-gram 相似度 (_char_ngram_similarity)
- 文本质量指标 (_compute_text_quality_metrics)
- 音频质量指标 (_compute_audio_quality_metrics)
- 结构质量指标 (_compute_structure_quality_metrics)
- 综合质量分数聚合 (_aggregate_quality_score)
"""

import math
from collections import Counter
from difflib import SequenceMatcher
from typing import Any, Dict


def _char_ngram_similarity(text_a: str, text_b: str, n: int = 2) -> float:
    """Compute character n-gram similarity (fallback for semantic similarity)."""

    def get_ngrams(text: str) -> Counter[str]:
        return Counter(text[i : i + n] for i in range(len(text) - n + 1))

    vec_a = get_ngrams(text_a)
    vec_b = get_ngrams(text_b)

    all_grams = set(vec_a.keys()) | set(vec_b.keys())
    dot_product = sum(vec_a[g] * vec_b[g] for g in all_grams)

    magnitude_a = math.sqrt(sum(v**2 for v in vec_a.values()))
    magnitude_b = math.sqrt(sum(v**2 for v in vec_b.values()))

    if magnitude_a == 0 or magnitude_b == 0:
        return 0.0

    return dot_product / (magnitude_a * magnitude_b)


def _compute_output_similarity(actual: Dict[str, Any], expected: Dict[str, Any]) -> float:
    """Compute similarity between actual and expected output (0-1).

    Uses recursive comparison for nested structures.
    """

    def compare_values(a: Any, b: Any) -> float:
        if type(a) != type(b):  # noqa: E721
            return 0.0

        if isinstance(a, dict):
            if not a and not b:
                return 1.0
            keys = set(a.keys()) | set(b.keys())
            if not keys:
                return 1.0
            scores = []
            for k in keys:
                if k in a and k in b:
                    scores.append(compare_values(a[k], b[k]))
                else:
                    scores.append(0.0)
            return sum(scores) / len(scores) if scores else 1.0

        elif isinstance(a, list):
            if not a and not b:
                return 1.0
            # For lists, compare element by element up to min length
            max_len = max(len(a), len(b))
            if max_len == 0:
                return 1.0
            scores = []
            for i in range(max_len):
                if i < len(a) and i < len(b):
                    scores.append(compare_values(a[i], b[i]))
                else:
                    scores.append(0.0)
            return sum(scores) / max_len

        elif isinstance(a, str):
            if not a and not b:
                return 1.0
            # Use sequence matcher for string similarity
            return SequenceMatcher(None, a, b).ratio()

        elif isinstance(a, (int, float)) and isinstance(b, (int, float)):
            if a == b:
                return 1.0
            # For numeric, use relative difference
            max_val = max(abs(a), abs(b), 1)
            diff = abs(a - b) / max_val
            return max(0.0, 1.0 - diff)

        elif isinstance(a, bool) and isinstance(b, bool):
            return 1.0 if a == b else 0.0

        else:
            return 1.0 if a == b else 0.0

    return compare_values(actual, expected)


def _compute_text_quality_metrics(
    actual_output: Dict[str, Any],
    expected_output: Dict[str, Any],
    input_data: Dict[str, Any],
) -> Dict[str, float]:
    """Compute quality metrics for text-based stages (edit, annotate, analyze)."""
    metrics = {}

    # 1. Output similarity to expected (base metric)
    metrics["output_similarity"] = _compute_output_similarity(actual_output, expected_output)

    # 2. For edit stage: check edited_text quality
    if "edited_text" in actual_output and "edited_text" in expected_output:
        edited_text = actual_output["edited_text"]
        expected_text = expected_output["edited_text"]
        metrics["text_similarity"] = _compute_output_similarity({"text": edited_text}, {"text": expected_text})

        # Semantic coherence (if we have multiple paragraphs, but we only have one here)
        # Use fallback character n-gram similarity
        metrics["semantic_coherence"] = _char_ngram_similarity(edited_text, expected_text)

        # Check if changes_made are reasonable
        if "changes_made" in actual_output:
            metrics["change_count"] = len(actual_output["changes_made"])
            # Penalize too many or too few changes
            expected_changes = len(expected_output.get("changes_made", []))
            if expected_changes > 0:
                metrics["change_ratio"] = min(metrics["change_count"] / max(expected_changes, 1), 2.0)
            else:
                metrics["change_ratio"] = 1.0 if metrics["change_count"] == 0 else 0.5

    # 3. Confidence score from output
    if "confidence" in actual_output:
        metrics["confidence"] = float(actual_output["confidence"])

    return metrics


def _compute_audio_quality_metrics(
    actual_output: Dict[str, Any],
    expected_output: Dict[str, Any],
    input_data: Dict[str, Any],
) -> Dict[str, float]:
    """Compute quality metrics for audio-based stages (synthesize, quality)."""
    metrics = {}

    # Base output similarity
    metrics["output_similarity"] = _compute_output_similarity(actual_output, expected_output)

    # For quality_check stage, check quality judgment scores
    if "overall_score" in actual_output and "overall_score" in expected_output:
        metrics["overall_score_match"] = 1.0 - abs(actual_output["overall_score"] - expected_output["overall_score"])

        # Check individual quality dimensions
        for dim in [
            "speaker_clarity",
            "emotion_match",
            "prosody_naturalness",
            "text_audio_alignment",
        ]:
            if dim in actual_output and dim in expected_output:
                metrics[f"{dim}_match"] = 1.0 - abs(actual_output[dim] - expected_output[dim])

    return metrics


def _compute_structure_quality_metrics(
    actual_output: Dict[str, Any],
    expected_output: Dict[str, Any],
    input_data: Dict[str, Any],
) -> Dict[str, float]:
    """Compute quality metrics for structure analysis stage."""
    metrics = {}
    metrics["output_similarity"] = _compute_output_similarity(actual_output, expected_output)

    # Check key structural elements
    for key in [
        "book_meta",
        "character_voice_map",
        "emotion_snapshots",
        "story_line_summary",
        "global_style_notes",
    ]:
        if key in actual_output and key in expected_output:
            metrics[f"{key}_similarity"] = _compute_output_similarity(actual_output[key], expected_output[key])

    return metrics


def _aggregate_quality_score(metrics: Dict[str, float], stage_type: str) -> float:
    """Aggregate multiple quality metrics into a single score."""
    if not metrics:
        return 0.0

    # Weighted aggregation based on stage type
    if stage_type == "text_edit":
        weights = {
            "output_similarity": 0.3,
            "text_similarity": 0.3,
            "semantic_coherence": 0.2,
            "change_ratio": 0.1,
            "confidence": 0.1,
        }
    elif stage_type == "text_annotation":
        weights = {
            "output_similarity": 0.4,
            "semantic_coherence": 0.3,
            "confidence": 0.3,
        }
    elif stage_type == "structure_analysis":
        weights = {
            "output_similarity": 0.5,
        }
        # Add weights for structural elements if present
        for key in metrics:
            if key.endswith("_similarity") and key != "output_similarity":
                weights[key] = 0.5 / max(len([k for k in metrics if k.endswith("_similarity")]), 1)
    elif stage_type == "audio_synthesis" or stage_type == "audio_quality":
        weights = {
            "output_similarity": 0.4,
            "overall_score_match": 0.3,
        }
        for key in metrics:
            if key.endswith("_match") and key not in weights:
                weights[key] = 0.3 / max(len([k for k in metrics if k.endswith("_match")]), 1)
    else:
        weights = {"output_similarity": 1.0}

    # Normalize weights
    total_weight = sum(weights.get(k, 0) for k in metrics.keys())
    if total_weight == 0:
        return 0.0

    score = 0.0
    for metric_name, value in metrics.items():
        weight = weights.get(metric_name, 0)
        score += (weight / total_weight) * value

    return score
