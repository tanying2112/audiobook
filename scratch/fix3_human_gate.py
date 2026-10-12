"""Fix 3：人工门出处画像 + SELF_ITERATION_HUMAN_GATE_STRICT 严格模式。

披露局限 (3)：无人工抽检记录时人工门按默认策略放行（default=1.0）。
修复：默认策略保留（生产其余 3 项硬门仍全量实证），但 (a) 出处在日志与
GateResult 可见（N 条真实记录 vs 默认策略），(b) 可用环境变量切换
fail-closed——运维一句配置即可把「人工缺位即放行」改成「人工缺位即拒绝」。
"""
from pathlib import Path

# ── 1) spotcheck.py：严格模式 + 出处画像 ──
p = Path("src/audiobook_studio/harness/spotcheck.py")
src = p.read_text(encoding="utf-8")

old = """from __future__ import annotations

import json
import logging
import threading"""
new = """from __future__ import annotations

import json
import logging
import os
import threading"""
assert src.count(old) == 1
src = src.replace(old, new)

old = '''def reset_spot_checks(path: Path = SPOTCHECK_PATH) -> None:'''
new = '''# 人工门严格模式：无抽检记录时 fail-closed（默认 false 维持既有默认策略，
# 生产语义不变；设置 SELF_ITERATION_HUMAN_GATE_STRICT=true 即拒绝人工缺位的晋升）。
HUMAN_GATE_STRICT_ENV = "SELF_ITERATION_HUMAN_GATE_STRICT"


def human_gate_strict() -> bool:
    """人工门严格模式开关（环境变量驱动，默认关闭）。"""
    return os.getenv(HUMAN_GATE_STRICT_ENV, "false").lower() not in ("false", "0", "no")


def resolve_human_default() -> float:
    """人工门默认分：严格模式 0.0（fail-closed），默认策略 1.0（放行）。"""
    return 0.0 if human_gate_strict() else 1.0


def human_spotcheck_summary(
    stage: str,
    since: Optional[str] = None,
    path: Path = SPOTCHECK_PATH,
) -> Dict[str, Any]:
    """人工门数据源画像：真实抽检记录数/均分 vs 默认策略（出处可审计）。"""
    recs = load_spot_checks(stage=stage, since=since, path=path)
    if recs:
        mean = sum(float(r["score"]) for r in recs) / len(recs)
        return {"n_records": len(recs), "mean": mean, "source": "records"}
    return {"n_records": 0, "mean": None, "source": "default_policy"}


def reset_spot_checks(path: Path = SPOTCHECK_PATH) -> None:'''
assert src.count(old) == 1
src = src.replace(old, new)
p.write_text(src, encoding="utf-8")
print("spotcheck.py OK")

# ── 2) integration.py：_human_samples_for_gate 严格模式 + 出处分默认 ──
p = Path("src/audiobook_studio/feedback/integration.py")
src = p.read_text(encoding="utf-8")

old = "from ..harness.spotcheck import human_preference_score_for"
new = "from ..harness.spotcheck import human_preference_score_for, resolve_human_default"
assert src.count(old) == 1
src = src.replace(old, new)

old = "                            human_preference_score=human_preference_score_for(stage, default=1.0),"
new = "                            human_preference_score=human_preference_score_for(stage, default=resolve_human_default()),"
assert src.count(old) == 1
src = src.replace(old, new)

old = '''    @staticmethod
    def _human_samples_for_gate(stage: str) -> List[bool]:
        from ..harness.spotcheck import load_spot_checks

        records = load_spot_checks(stage=stage)
        if records:
            samples = [float(r["score"]) >= 0.8 for r in records]
            logger.info(f"[SelfIteration] {stage}: 使用 {len(samples)} 条真实人工抽检评分入门禁")
            return samples
        logger.info(f"[SelfIteration] {stage}: 无人工抽检记录，人工门按 harness 默认策略放行")
        return [True]'''
new = '''    @staticmethod
    def _human_samples_for_gate(stage: str) -> List[bool]:
        from ..harness.spotcheck import human_gate_strict, load_spot_checks

        records = load_spot_checks(stage=stage)
        if records:
            samples = [float(r["score"]) >= 0.8 for r in records]
            logger.info(f"[SelfIteration] {stage}: 使用 {len(samples)} 条真实人工抽检评分入门禁")
            return samples
        # 人工缺位：默认策略放行（其余 3 项硬门仍全量实证）；严格模式 fail-closed，
        # 返回空样本集 → check_human_sample 判不通过并如实标注「尚无人工抽样结果」。
        if human_gate_strict():
            logger.warning(
                f"[SelfIteration] {stage}: 无人工抽检记录且 {human_gate_strict.__module__}"
                " SELF_ITERATION_HUMAN_GATE_STRICT=true —— 人工门 fail-closed"
            )
            return []
        logger.info(
            f"[SelfIteration] {stage}: 无人工抽检记录，人工门按默认策略放行"
            "（出处：default=1.0；设 SELF_ITERATION_HUMAN_GATE_STRICT=true 可改 fail-closed）"
        )
        return [True]'''
assert src.count(old) == 1
src = src.replace(old, new)
p.write_text(src, encoding="utf-8")
print("integration.py OK")
