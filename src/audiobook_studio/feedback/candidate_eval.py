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

import difflib
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

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


# 各 stage 的「产品文本/列表」字段声明：Gate2 的实质比较维度按 stage 显式声明，
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
    return sum(s * w for s, w in parts) / total_w


def example_passes_gate(
    expected: Any, output: Any, stage: Optional[str] = None, threshold: float = 0.85
) -> bool:
    """单例金标门判定：stage 声明了产品文本字段时，以文本相似度 ≥ threshold 为准。

    为什么不用综合相似度过 0.85：2026-10 校准实测（live v43 × 24 条真实金标），
    正确输出的综合分被 ``changes_made`` 措辞差异（精确串 Jaccard≈0，如
    「删除冗余修饰」vs「冗余修饰删减」）与置信度校准拉到 0.73-0.83 全线
    不达标，而其产品文本相似度 0.84-1.00。门的问题形态是「产品文本对不对」，
    判定必须锚定产品本身；标签措辞与置信度只是佐证，已计入综合分供参考，
    不作硬门（否则门对正确输出恒假阴，对措辞复读机恒假阳）。无产品文本
    字段的 stage（judge/quality 等）维持综合分判定，行为不变。
    """
    exp: Dict[str, Any] = _to_dict(expected)
    out: Dict[str, Any] = _to_dict(output)
    for k in STAGE_PRIMARY_TEXT_FIELDS.get(stage or "", ()):
        if k in exp:
            return _text_similarity(exp[k], out.get(k, "")) >= threshold
    return score_output_vs_expected(exp, out, stage=stage) >= threshold


class DeterministicJudge:
    """确定性评判器：不触网，离线可复现。"""

    def score(self, input_data: Any, output: Any, expected: Any, stage: str) -> float:
        return score_output_vs_expected(expected, output, stage=stage)


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
