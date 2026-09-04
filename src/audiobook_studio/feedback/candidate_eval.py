"""M2 — 评判升级：在冻结留出集（test）上做 候选 vs 基线 的实证评判。

复用 ``held_out_eval.HeldOutDataset``（冻结、不可改的标尺）做评估载体，并提供两类评判器：

* ``DeterministicJudge`` —— 纯本地的确定性打分（输出 vs 期望的结构/数值/通过率比对），
  不触网、不依赖 LLM，保证离线可运行与可复现，也作为在线 ensemble 失败时的兜底。
* ``EnsembleJudge`` —— 在线时用 ``llm_judge.LLMJudgeEnsemble`` 多模型盲评（faithfulness /
  naturalness / instruction_following / no_hallucination），失败自动降级到 ``DeterministicJudge``。

外部只需提供 ``run_fn(input_dict) -> output``（跑某版本 prompt 的真实 stage），本模块负责把它包成
``HeldOutDataset.evaluate_candidate`` 需要的 ``Callable[[HeldOutCase], float]``，并返回冻结的
``CandidateEvalResult``（含 mean_score / baseline_mean / effect_size / beat_baseline_by_025）。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .held_out_eval import CandidateEvalResult, HeldOutCase, HeldOutDataset

logger = logging.getLogger(__name__)

# 冻结留出集默认位置：data/golden/test/<stage>/<stage>.jsonl
DEFAULT_TEST_GOLDEN_ROOT = Path("data/golden/test")


def _to_dict(obj: Any) -> Dict[str, Any]:
    """把 pydantic/dataclass/dict/对象 统一成可比较的 dict。"""
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return dict(obj)
    model_dump = getattr(obj, "model_dump", None)
    if callable(model_dump):
        try:
            return dict(model_dump(mode="json"))
        except (TypeError, ValueError):
            return dict(model_dump())
    fields = getattr(obj, "__dataclass_fields__", None)
    if fields is not None:
        from dataclasses import asdict

        return dict(asdict(obj))
    if hasattr(obj, "__dict__"):
        return dict(vars(obj))
    return {}


def score_output_vs_expected(expected: Any, output: Any) -> float:
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

    return sum(parts) / len(parts)


class DeterministicJudge:
    """确定性评判器：不触网，离线可复现。"""

    def score(self, input_data: Any, output: Any, expected: Any, stage: str) -> float:
        return score_output_vs_expected(expected, output)


# LLMJudgeEnsemble 防御式导入：未安装 / 在线不可用时，EnsembleJudge 自动退化为确定性评判。
try:
    from .llm_judge import LLMJudgeEnsemble

    _ENSEMBLE_AVAILABLE = True
except Exception:  # noqa: BLE001
    LLMJudgeEnsemble = None  # type: ignore[assignment]
    _ENSEMBLE_AVAILABLE = False


class EnsembleJudge:
    """在线多模型盲评评判器；不可用时降级到 DeterministicJudge。

    把「期望输出」作为 A、把「候选输出」作为 B 交给 ensemble，返回候选相对期望的
    归一化偏好占比（score_b / (score_a + score_b)），作为 0-1 相似度。
    """

    def __init__(self, models: Optional[List[str]] = None) -> None:
        self._fallback = DeterministicJudge()
        self._ensemble: Optional[Any] = None
        if _ENSEMBLE_AVAILABLE and models:
            try:
                self._ensemble = LLMJudgeEnsemble(models=models)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"EnsembleJudge: 初始化 LLMJudgeEnsemble 失败，降级确定性评判: {e}")
                self._ensemble = None

    @property
    def online(self) -> bool:
        return self._ensemble is not None

    def score(self, input_data: Any, output: Any, expected: Any, stage: str) -> float:
        if self._ensemble is None:
            return self._fallback.score(input_data, output, expected, stage)
        try:
            res = self._ensemble.judge(
                input_data=_to_dict(input_data),
                output_a=_to_dict(expected),
                output_b=_to_dict(output),
                stage=stage,
            )
            denom = (res.score_a + res.score_b) or 0.0
            # res 来自动态导入的 ensemble（可能被判为 Any），显式转 float 以保严格类型
            score_b = float(res.score_b)
            score_a = float(res.score_a)
            denom = (score_a + score_b) or 0.0
            return (score_b / denom) if denom > 0 else 0.5
        except Exception as e:  # noqa: BLE001
            logger.warning(f"EnsembleJudge: 在线评判失败，降级确定性评判: {e}")
            return self._fallback.score(input_data, output, expected, stage)


def run_candidate_on_held_out(
    stage: str,
    run_fn: Callable[[Dict[str, Any]], Any],
    baseline_fn: Optional[Callable[[Dict[str, Any]], Any]] = None,
    *,
    golden_root: Optional[Path] = None,
    candidate_id: str = "candidate",
    baseline_id: str = "baseline",
    judge: Optional[Any] = None,
) -> CandidateEvalResult:
    """在冻结的 test 留出集上评估候选 prompt（可对比基线）。

    Args:
        stage: 评估的阶段（对应 ``data/golden/test/<stage>``）。
        run_fn: ``input_dict -> output``，跑「候选」prompt 版本的真实 stage。
        baseline_fn: 同上，跑「基线」prompt 版本；为 None 时只评估候选无 baseline。
        golden_root: 留出集根目录，默认 ``data/golden/test``。
        judge: 评判器（默认 ``DeterministicJudge``）。

    Returns:
        冻结的 ``CandidateEvalResult``（含 mean_score / baseline_mean / effect_size）。
    """
    root = Path(golden_root) if golden_root is not None else DEFAULT_TEST_GOLDEN_ROOT
    dataset = HeldOutDataset(stage, golden_root=root)
    j = judge or DeterministicJudge()

    def candidate_fn(case: HeldOutCase) -> float:
        out = run_fn(dict(case.input))
        return j.score(dict(case.input), out, dict(case.expected_output), case.stage)

    base_fn: Optional[Callable[[HeldOutCase], float]] = None
    if baseline_fn is not None:

        def base_fn_inner(case: HeldOutCase) -> float:
            out = baseline_fn(dict(case.input))
            return j.score(dict(case.input), out, dict(case.expected_output), case.stage)

        base_fn = base_fn_inner

    return dataset.evaluate_candidate(
        candidate_fn,
        candidate_id=candidate_id,
        baseline_fn=base_fn,
        baseline_id=baseline_id,
    )
