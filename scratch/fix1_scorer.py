"""Fix 1: score_output_vs_expected 增加 stage 产品字段比较（edited_text 等）。

修复已披露局限 (1)：edit 阶段 Gate2 退化为置信-邻近度。
"""
import re
from pathlib import Path

p = Path("src/audiobook_studio/feedback/candidate_eval.py")
src = p.read_text(encoding="utf-8")

# ── 1) 导入 difflib ──
old = """from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional"""
new = """from __future__ import annotations

import difflib
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple"""
assert src.count(old) == 1
src = src.replace(old, new)

# ── 2) 重写 score_output_vs_expected：加权维度 + stage 产品字段 ──
old = '''def score_output_vs_expected(expected: Any, output: Any) -> float:
    """把候选输出与期望输出比对，给出 0-1 的确定性相似度。

    综合三项（等权平均）：
    1. 通过/失败一致性：期望与输出是否同为 pass / fail（基于 ``needs_regeneration``）。
    2. 数值维度接近度：对期望中的数值字段（0-1 尺度），按平均绝对差映射到 1-diff。
    3. 问题标签重叠度（Jaccard）：``issues`` 列表的重合比例。
    若无任何可比维度，回退到键名重叠度。
    """
    exp: Dict[str, Any] = _to_dict(expected)
    out: Dict[str, Any] = _to_dict(output)
    if not exp:
        return 0.0
    if not out:
        return 0.0

    parts: List[float] = []

    # 1) 通过/失败一致性
    if "needs_regeneration" in exp and "needs_regeneration" in out:
        exp_pass = not bool(exp["needs_regeneration"])
        out_pass = not bool(out["needs_regeneration"])
        parts.append(1.0 if exp_pass == out_pass else 0.0)

    # 2) 数值维度接近度（假设尺度 0-1）
    num_keys = [k for k, v in exp.items() if isinstance(v, (int, float)) and not isinstance(v, bool)]
    diffs: List[float] = []
    for k in num_keys:
        ov = out.get(k)
        if isinstance(ov, (int, float)) and not isinstance(ov, bool):
            diffs.append(abs(float(exp[k]) - float(ov)))
    if diffs:
        avg_diff = sum(diffs) / len(diffs)
        parts.append(max(0.0, 1.0 - avg_diff))

    # 3) 问题标签重叠度（Jaccard）
    if "issues" in exp and isinstance(exp["issues"], list):
        ei = {str(x) for x in exp["issues"]}
        oi_raw = out.get("issues")
        oi = {str(x) for x in oi_raw} if isinstance(oi_raw, list) else set()
        union = ei | oi
        parts.append(len(ei & oi) / len(union) if union else 1.0)

    if not parts:
        # 兜底：键名重叠度
        ek = set(exp.keys())
        ok = set(out.keys())
        union = ek | ok
        parts.append(len(ek & ok) / len(union) if union else 0.5)

    return sum(parts) / len(parts)'''
new = '''# 各 stage 的「产品文本/列表」字段声明：Gate2 的实质比较维度按 stage 显式声明，
# 而非按字段类型猜。这是 2026-10 马拉松复盘披露的局限修复——此前 edit 阶段的
# TtsEditOutput 唯一数值字段是 confidence，score_output_vs_expected 对它只剩
# 置信-邻近度一个可比维度，edited_text（真实产品）从不参与比较，导致
# r9-r30 每轮「黄金数据集通过率 1.000」恒假阳。未声明 stage 维持原行为
# （needs_regeneration / 数值 / issues / 键名兜底），rationale 等自由文本
# 依旧不比——真实 LLM 不可能逐字复现金标措辞，比了反而恒假阴。
STAGE_PRIMARY_TEXT_FIELDS: Dict[str, Tuple[str, ...]] = {
    "edit": ("edited_text",),
    "edit_for_tts": ("edited_text",),
}
STAGE_LIST_FIELDS: Dict[str, Tuple[str, ...]] = {
    "edit": ("changes_made", "forbidden_content_removed"),
    "edit_for_tts": ("changes_made", "forbidden_content_removed"),
}
# 产品文本字段权重：3（主导分量）。文本是 stage 的真实产出，编辑质量 90% 由它
# 决定；数值校准（confidence）与标签列表等权为 1，只能作次要校准项。
PRIMARY_TEXT_WEIGHT = 3.0


def _normalize_text(s: Any) -> str:
    """文本归一化：压空白后小写。标点保留（TTS 编辑常以标点为产品差异点）。"""
    return "".join(str(s).split()).lower() if s is not None else ""


def _text_similarity(a: Any, b: Any) -> float:
    """归一化文本的 SequenceMatcher 相似度（0-1）。"""
    na, nb = _normalize_text(a), _normalize_text(b)
    if not na and not nb:
        return 1.0
    if not na or not nb:
        return 0.0
    return difflib.SequenceMatcher(None, na, nb).ratio()


def score_output_vs_expected(expected: Any, output: Any, stage: Optional[str] = None) -> float:
    """把候选输出与期望输出比对，给出 0-1 的确定性相似度（可按 stage 加权）。

    维度与权重：
    1. 通过/失败一致性（needs_regeneration 等布尔一致），权重 1。
    2. 数值维度接近度（0-1 尺度，如 confidence），权重 1。
    3. ``issues`` 列表 Jaccard，权重 1。
    4. stage 声明的产品列表字段（如 ``changes_made``）Jaccard，权重 1。
    5. stage 声明的产品文本字段（如 ``edited_text``）归一化文本相似度，
       权重 ``PRIMARY_TEXT_WEIGHT``（主导）——产品文本错误（如改写崩坏、
       编辑规则未应用）直接压垮分数，置信度再接近也救不回来。
    若无任何可比维度，回退到键名重叠度（权重 1）。
    """
    exp: Dict[str, Any] = _to_dict(expected)
    out: Dict[str, Any] = _to_dict(output)
    if not exp:
        return 0.0
    if not out:
        return 0.0

    # (score, weight) 二元组列表；最终按权重平均
    parts: List[Tuple[float, float]] = []

    # 1) 通过/失败一致性（期望中的全部布尔字段）
    for k, v in exp.items():
        if isinstance(v, bool):
            parts.append((1.0 if bool(out.get(k)) == bool(v) else 0.0, 1.0))

    # 2) 数值维度接近度（假设尺度 0-1）
    num_keys = [k for k, v in exp.items() if isinstance(v, (int, float)) and not isinstance(v, bool)]
    diffs: List[float] = []
    for k in num_keys:
        ov = out.get(k)
        if isinstance(ov, (int, float)) and not isinstance(ov, bool):
            diffs.append(abs(float(exp[k]) - float(ov)))
    if diffs:
        avg_diff = sum(diffs) / len(diffs)
        parts.append((max(0.0, 1.0 - avg_diff), 1.0))

    # 3) 问题标签重叠度（Jaccard）
    if "issues" in exp and isinstance(exp["issues"], list):
        ei = {str(x) for x in exp["issues"]}
        oi_raw = out.get("issues")
        oi = {str(x) for x in oi_raw} if isinstance(oi_raw, list) else set()
        union = ei | oi
        parts.append((len(ei & oi) / len(union) if union else 1.0, 1.0))

    # 3b) stage 声明的产品列表字段（Jaccard）——edit 的 changes_made 等
    stage_key = stage or ""
    for k in STAGE_LIST_FIELDS.get(stage_key, ()):
        ev = exp.get(k)
        if not isinstance(ev, list):
            continue
        ei = {str(x) for x in ev}
        oi_raw = out.get(k)
        oi = {str(x) for x in oi_raw} if isinstance(oi_raw, list) else set()
        union = ei | oi
        parts.append((len(ei & oi) / len(union) if union else 1.0, 1.0))

    # 5) stage 声明的产品文本字段（主导权重）——edit 的 edited_text 等
    for k in STAGE_PRIMARY_TEXT_FIELDS.get(stage_key, ()):
        if k not in exp:
            continue
        parts.append((_text_similarity(exp[k], out.get(k, "")), PRIMARY_TEXT_WEIGHT))

    if not parts:
        # 兜底：键名重叠度
        ek = set(exp.keys())
        ok = set(out.keys())
        union = ek | ok
        parts.append((len(ek & ok) / len(union) if union else 0.5, 1.0))

    total_w = sum(w for _, w in parts)
    return sum(s * w for s, w in parts) / total_w'''
assert src.count(old) == 1
src = src.replace(old, new)

# ── 3) DeterministicJudge.score 透传 stage ──
old = '''class DeterministicJudge:
    """确定性评判器：不触网，离线可复现。"""

    def score(self, input_data: Any, output: Any, expected: Any, stage: str) -> float:
        return score_output_vs_expected(expected, output)'''
new = '''class DeterministicJudge:
    """确定性评判器：不触网，离线可复现。"""

    def score(self, input_data: Any, output: Any, expected: Any, stage: str) -> float:
        return score_output_vs_expected(expected, output, stage=stage)'''
assert src.count(old) == 1
src = src.replace(old, new)

p.write_text(src, encoding="utf-8")
print("candidate_eval.py OK")

# ── 4) promotion.py：Gate2 调用透传 stage ──
p = Path("src/audiobook_studio/feedback/promotion.py")
src = p.read_text(encoding="utf-8")
old = "            similarity = score_output_vs_expected(expected_output, actual_output)"
new = "            similarity = score_output_vs_expected(expected_output, actual_output, stage=stage)"
assert src.count(old) == 1
src = src.replace(old, new)
p.write_text(src, encoding="utf-8")
print("promotion.py OK")

# ── 5) integration.py：canary 调用透传 stage ──
p = Path("src/audiobook_studio/feedback/integration.py")
src = p.read_text(encoding="utf-8")
old = """                    similarity = score_output_vs_expected(expected_output, new_output)
                    baseline_similarity = score_output_vs_expected(expected_output, old_output)"""
new = """                    similarity = score_output_vs_expected(expected_output, new_output, stage=stage)
                    baseline_similarity = score_output_vs_expected(expected_output, old_output, stage=stage)"""
assert src.count(old) == 1
src = src.replace(old, new)
p.write_text(src, encoding="utf-8")
print("integration.py OK")

# ── 6) offline_judge.py：三处调用透传 stage ──
p = Path("src/audiobook_studio/feedback/offline_judge.py")
src = p.read_text(encoding="utf-8")
old = '''        """与 M2 评判器同接口：候选输出 vs 期望的确定性相似度（0-1）。"""
        return score_output_vs_expected(expected, output)'''
new = '''        """与 M2 评判器同接口：候选输出 vs 期望的确定性相似度（0-1）。"""
        return score_output_vs_expected(expected, output, stage=stage)'''
assert src.count(old) == 1
src = src.replace(old, new)
src = src.replace(
    "            return score_output_vs_expected(expected, output)",
    "            return score_output_vs_expected(expected, output, stage=stage)",
)
p.write_text(src, encoding="utf-8")
print("offline_judge.py OK")
