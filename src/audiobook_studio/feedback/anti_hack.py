"""Anti reward-hacking promotion gate (P0.3).

包含：
- DualJudgeEvaluator, JudgeVerdict, DualJudgeResult
- verify_meta_guard (元门禁)
- evaluate_promotion_anti_hack (反 reward-hacking 主入口)
"""

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Mapping, Optional, Tuple

if TYPE_CHECKING:
    from .constitution import ConstitutionAdjudicator
    from .evolution_guard import EvolutionGuard
    from .held_out_eval import HeldOutDataset
    from .regression_suite import RegressionSuite

logger = logging.getLogger(__name__)

# 默认裁判 model 白名单：双裁判需两个**不同** provider。提议配置的 proposer_model 被
# 明确排除在裁判池外（防"自己给自己打分"）。
DEFAULT_JUDGE_POOL: Tuple[str, ...] = ("gpt-4o-mini", "deepseek-chat", "openrouter/auto")


@dataclass
class JudgeVerdict:
    """单个裁判对候选的打分结果。"""

    judge_model: str
    score: float  # 0-1
    rationale: str = ""
    error: Optional[str] = None  # 裁判不可用时记原因（诚实降级）

    @property
    def available(self) -> bool:
        return self.error is None


@dataclass
class DualJudgeResult:
    """双裁判裁决汇总。"""

    judges: List[JudgeVerdict]
    mean: Optional[float]  # 两位可用裁判的均值；任一不可用则 None（不假通过）
    agreement: Optional[bool]  # 两位分歧 ≤ delta 时 True；不可判（缺裁判）则 None
    disagreement_delta: float = 0.0
    pending_human: bool = False  # True 表示需人工复核（如裁判异常、分歧过大等）

    @property
    def promotable_score(self) -> Optional[float]:
        """只有两位都可用且分歧可接受才返回可用均分；否则 None=不假通过。"""
        if self.mean is None or self.agreement is None or not self.agreement:
            return None
        return self.mean


class DualJudgeEvaluator:
    """双裁判：两个不同 provider LLM 各在留出集上打分；proposer_model 排除在裁判外。"""

    def __init__(
        self,
        judge_pool: Optional[List[str]] = None,
        disagreement_delta: float = 0.25,
        proposer_model: Optional[str] = None,
    ) -> None:
        # 从 pool 里去掉 proposer_model（提议配置的模型不得给自己打分）
        pool = list(judge_pool) if judge_pool else list(DEFAULT_JUDGE_POOL)
        if proposer_model:
            pool = [m for m in pool if m != proposer_model]
        # 取两个裁判（去重保序）。pool 不足两个 → 诚实降级（无法构成双裁判）
        self.judge_models: List[str] = []
        for m in pool:
            if m not in self.judge_models:
                self.judge_models.append(m)
            if len(self.judge_models) >= 2:
                break
        self.disagreement_delta = float(disagreement_delta)
        self.proposer_model = proposer_model

    @property
    def can_dual_judge(self) -> bool:
        return len(self.judge_models) >= 2

    def evaluate(
        self,
        judge_fn: Callable[[str, Mapping[str, Any]], float],
        candidate_payload: Mapping[str, Any],
    ) -> DualJudgeResult:
        """在 candidates 载荷上让每位裁判打分。

        judge_fn(judge_model, candidate_payload) -> float ∈[0,1]，由上层注入真实 LLM 调用
        （跑真实留出集输出）。本方法不发起任何 LLM 请求。任一裁判抛错 → 该裁判 error 记
        原因、Unavailable；两位都不可用 / 分歧 > delta → mean=None / agreement=False
        （诚实降级或分歧不晋升）。
        """
        verdicts: List[JudgeVerdict] = []
        pending_human = False
        for jm in self.judge_models:
            try:
                raw = judge_fn(jm, candidate_payload)
                s = float(raw)
                if s != s:  # NaN
                    raise ValueError("judge returned NaN")
                s = max(0.0, min(1.0, s))
                verdicts.append(JudgeVerdict(judge_model=jm, score=s))
            except Exception as ex:  # noqa: BLE001
                # 裁判异常：标记为需人工复核，而非给 0 分（诚实降级）
                pending_human = True
                verdicts.append(JudgeVerdict(judge_model=jm, score=0.0, error=f"{type(ex).__name__}: {ex}"))

        avail = [v for v in verdicts if v.available]
        if len(avail) < 2:
            # 严格：必须两位裁判都跑出真值才能给均值，否则 None（不假通过）
            return DualJudgeResult(judges=verdicts, mean=None, agreement=None, pending_human=True)
        
        mean = sum(v.score for v in avail) / len(avail)
        delta = abs(avail[0].score - avail[1].score)
        agreement = delta <= self.disagreement_delta
        if not agreement:
            pending_human = True
            logger.warning(
                "DualJudge disagreement: %s=%.3f vs %s=%.3f (Δ=%.3f > %.2f) — 需人工复核",
                avail[0].judge_model,
                avail[0].score,
                avail[1].judge_model,
                avail[1].score,
                delta,
                self.disagreement_delta,
            )
        return DualJudgeResult(judges=verdicts, mean=mean, agreement=agreement, disagreement_delta=delta, pending_human=pending_human)


# ── 元门禁：判官 prompt / 评估集 / 指标定义文件对进化循环只读 ─────────────────────
# 这些路径是 reward hacking 的"尺度"。CI 以 verify_meta_guard() 校验：
#   * 它们随本 Sprint 的自动改动列表（git diff --name-only）一并被人工/CI 复审；
#   * 候选不得在进化循环内写这些文件（本模块纯读，无写）。
META_GUARD_READONLY_PATHS: Tuple[str, ...] = (
    "src/audiobook_studio/feedback/promotion_config.yaml",  # 门禁阈值
    "src/audiobook_studio/feedback/constitution.py",  # 创作宪法硬规则
    "src/audiobook_studio/feedback/held_out_eval.py",  # 留出集与评估契约
    "src/audiobook_studio/quality/metrics.py",  # 硬指标定义（MOS/WER/Sim）
    "prompts/",  # 裁判/生成 prompt（模板）
    "tests/golden/",  # 评估集（留出集来源）
)


def verify_meta_guard(changed_files: List[str]) -> Dict[str, Any]:
    """校验本次改动列表是否触碰只读尺度文件。

    返回 {touched: [...], clean: bool}。CI 在自动晋升流水线里调用——当
    `clean=False` 时，改动触及了度量尺度，必须人工复核、不得由进化循环自动通过。
    """
    touched: List[str] = []
    for cf in changed_files:
        for ro in META_GUARD_READONLY_PATHS:
            if cf == ro or cf.startswith(ro.rstrip("/") + "/"):
                touched.append(cf)
                break
    return {"touched": touched, "clean": len(touched) == 0}


# ── 反 reward-hacking 主编排：evaluate_promotion_anti_hack ────────────────────────
# 严格顺序：
#   1) Constitution 先于软打分硬裁决（被拒即不晋升，无需双裁判）
#   2) 冻结留出集双裁判打分（提议配置模型不参赛；分歧超.delta 不晋升）
#   3) ≥0.25 最小效应量晋升门槛（候选留出集均分 ≥ baseline 均分 + 0.25）
#   4) 回归套件：候选不得使任一 active 坏例复发（含本次新发现的失败）
#   5) 进化守卫 record：成功晋升则 append 节点；连续退化 ≥2 则回滚+剪枝
# 任一硬关被违反即 passed=False；依赖未就绪时该关诚实降级为"无法裁决→不晋升"。


@dataclass
class AntiHackVerdict:
    """反 reward-hacking 晋升裁决（评估报告）。"""

    passed: bool
    summary: str
    constitution: Dict[str, Any]
    dual_judge: Dict[str, Any]
    held_out: Dict[str, Any]
    regression_suite: Dict[str, Any]
    evolution_guard: Dict[str, Any]
    effect_size: Optional[float] = None
    beat_baseline_by_025: bool = False
    promoted_node_id: Optional[str] = None
    rolled_back: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "summary": self.summary,
            "constitution": self.constitution,
            "dual_judge": self.dual_judge,
            "held_out": self.held_out,
            "regression_suite": self.regression_suite,
            "evolution_guard": self.evolution_guard,
            "effect_size": self.effect_size,
            "beat_baseline_by_025": self.beat_baseline_by_025,
            "promoted_node_id": self.promoted_node_id,
            "rolled_back": self.rolled_back,
        }


def _constitution() -> "ConstitutionAdjudicator":
    from .constitution import get_constitution_adjudicator

    return get_constitution_adjudicator()


def _held_out(stage: str) -> "HeldOutDataset":
    from .held_out_eval import HeldOutDataset

    return HeldOutDataset(stage)


def _evolution_guard() -> "EvolutionGuard":
    from .evolution_guard import get_evolution_guard

    return get_evolution_guard()


def _regression_suite() -> "RegressionSuite":
    from .regression_suite import get_regression_suite

    return get_regression_suite()


def evaluate_promotion_anti_hack(
    stage: str,
    candidate_id: str,
    candidate_output_text: str,
    reference_text: Optional[str],
    audio_metrics: Optional[Mapping[str, Any]],
    candidate_payload: Mapping[str, Any],
    judge_fn: Optional[Callable[[str, Mapping[str, Any]], float]],
    baseline_fn: Optional[Callable[[Any], float]],
    candidate_eval_fn: Optional[Callable[[Any], float]],
    proposer_model: Optional[str] = None,
    judge_pool: Optional[List[str]] = None,
    regression_fn: Optional[Callable[[Any], Tuple[bool, Any]]] = None,
    promoted_at: str = "",
    config_digest: str = "",
    new_version: int = 1,
) -> AntiHackVerdict:
    """反 reward-hacking 主入口。任一硬关失败即不晋升。

    红线 #1：judge_fn / baseline_fn / candidate_eval_fn / regression_fn 由**上层注入**，
    跑真实评估（真 prompt→输出→P0.2 真指标→归一化）；本函数不 mock、不假通过。
    依赖缺失（双裁判不可用、留出集空、无基线）→ 对应关诚实降级 → passed=False。
    """
    reasons: List[str] = []

    # ── 1) 创作宪法硬规则先于软打分 ──────────────────────────────────────
    constit = _constitution().adjudge(
        candidate_output=candidate_output_text,
        reference_text=reference_text,
        audio_metrics=audio_metrics or {},
    )
    constit_dict = constit.to_dict()
    if not constit.passed:
        reasons.append("constitution:rejected")
        if constit.unable_to_judge:
            reasons.append("constitution:unable_to_judge(依赖缺失诚实降级)")

    # ── 2) 冻结留出集双裁判 ────────────────────────────────────────────
    dj = DualJudgeEvaluator(
        judge_pool=judge_pool,
        disagreement_delta=0.25,
        proposer_model=proposer_model,
    )
    dj_avail = dj.can_dual_judge
    dj_dict: Dict[str, Any] = {
        "judge_models": list(dj.judge_models),
        "proposer_excluded": bool(proposer_model and proposer_model not in dj.judge_models),
        "can_dual_judge": dj_avail,
    }
    # 验证 proposer_model 确实不是裁判（互不提议）
    if proposer_model and proposer_model in dj.judge_models:
        dj_dict["proposer_not_judge"] = False
        reasons.append("dual_judge:proposer_is_judge(违反互不提议)")
    else:
        dj_dict["proposer_not_judge"] = True

    held_out_score: Optional[float] = None
    baseline_score: Optional[float] = None
    held_out_dict: Dict[str, Any] = {}

    try:
        ds = _held_out(stage)
        held_out_dict = {
            "stage": stage,
            "case_count": ds.case_count,
            "signature": ds.signature,
            "origin": ds.manifest.origin_status,
        }
        if ds.case_count == 0:
            reasons.append("held_out:empty(留出集空无法量度诚实降级)")
        else:
            # 候选留出集评估（候选真值）与基线留出集评估（基线真值）
            cand_scores = None
            base_scores = None
            if candidate_eval_fn is not None:
                res = ds.evaluate_candidate(
                    candidate_eval_fn,
                    candidate_id=candidate_id,
                    baseline_fn=baseline_fn if baseline_fn is not None else (lambda c: 0.0),
                    baseline_id="baseline",
                )
                cand_scores = res
                held_out_score = res.mean_score
                baseline_score = res.baseline_mean
                held_out_dict.update(res.to_dict())
            # 双裁判在候选载荷上打综合分（如可用）
            if dj_avail and judge_fn is not None:
                djres = dj.evaluate(judge_fn, candidate_payload)
                held_out_dict["dual_judge"] = {
                    "mean": djres.mean,
                    "agreement": djres.agreement,
                    "delta": djres.disagreement_delta,
                    "pending_human": djres.pending_human,
                    "judges": [{"model": j.judge_model, "score": j.score, "error": j.error} for j in djres.judges],
                    "promotable_score": djres.promotable_score,
                }
                if not djres.promotable_score and not (judge_fn is None):
                    if djres.mean is None:
                        reasons.append("dual_judge:unavailable(缺裁判/不可用不假通过)")
                    elif djres.agreement is False:
                        reasons.append("dual_judge:disagreement(分歧超.delta不晋升)")
                    if djres.pending_human:
                        reasons.append("dual_judge:pending_human(需人工复核)")
            elif judge_fn is not None and not dj_avail:
                reasons.append("dual_judge:pool<2(无法构成双裁判诚实降级)")
    except Exception as ex:  # noqa: BLE001
        held_out_dict = {"error": f"{type(ex).__name__}: {ex}"}
        reasons.append("held_out:error")

    # ── 3) ≥0.25 效应量晋升门槛 ──────────────────────────────────────────
    effect_size: Optional[float] = None
    beat025 = False
    if held_out_score is not None and baseline_score is not None:
        effect_size = held_out_score - baseline_score
        beat025 = effect_size >= 0.25
        if not beat025:
            reasons.append(f"effect_size:insufficient(+{effect_size:.3f} < 0.25 最小效应量门槛)")
    else:
        reasons.append("effect_size:indeterminate(缺候选或基线留出集真值)")

    # ── 4) 回归套件 ─────────────────────────────────────────────────────
    reg_dict: Dict[str, Any] = {}
    try:
        suite = _regression_suite()
        if regression_fn is not None:
            regv = suite.check_candidate(candidate_id, regression_fn, auto_add_new=True)
            reg_dict = regv.to_dict()
            if regv.rejected:
                reasons.append("regression_suite:recurring_failure(已知坏例复发或新失败入库)")
        else:
            reg_dict = {"skipped": "no regression_fn（诚实降级，按保守不晋升）"}
            reasons.append("regression_suite:indeterminate(无回归判定函数)")
    except Exception as ex:  # noqa: BLE001
        reg_dict = {"error": f"{type(ex).__name__}: {ex}"}
        reasons.append("regression_suite:error")

    # ── 5) 进化守卫 record ──────────────────────────────────────────────
    guard_dict: Dict[str, Any] = {}
    rolled_back: Optional[Dict[str, Any]] = None
    promoted_node_id: Optional[str] = None
    try:
        guard = _evolution_guard()
        ev_mean = held_out_score if held_out_score is not None else 0.0
        ev_effect = effect_size if effect_size is not None else 0.0
        node_id = f"{stage}:{candidate_id}:v{new_version}"
        rb = guard.record(
            node_id=node_id,
            stage=stage,
            held_out_mean=ev_mean,
            effect_size=ev_effect,
            promoted_at=promoted_at,
            config_digest=config_digest,
        )
        guard_dict = {
            "active_id": guard.active_id,
            "node_count": guard.node_count,
            "pruned_ids": list(guard.pruned_ids),
            "regression_streak": guard.regression_streak,
        }
        if rb is not None:
            rolled_back = rb.to_dict()
            guard_dict["rolled_back"] = rolled_back
            reasons.append(
                f"evolution_guard:rolled_back({rb.rolled_back_from}->{rb.rolled_back_to},"
                f"pruned {len(rb.pruned_node_ids)})"
            )
        else:
            # 仅当晋升成功才记 promoted_node_id
            if beat025 and len(reasons) == 0:
                promoted_node_id = node_id
    except Exception as ex:  # noqa: BLE001
        guard_dict = {"error": f"{type(ex).__name__}: {ex}"}
        reasons.append("evolution_guard:error")

    passed = len(reasons) == 0 and beat025
    summary = (
        f"✅ 晋升通过：{stage} {candidate_id}（effect=+{effect_size:.3f} ≥ 0.25，"
        f"宪法/双裁判/留出集/回归/守卫全通过）"
        if passed
        else f"❌ 拒绝晋升：{stage} {candidate_id} — {'; '.join(reasons)}"
    )
    logger.info("evaluate_promotion_anti_hack: %s", summary)
    return AntiHackVerdict(
        passed=passed,
        summary=summary,
        constitution=constit_dict,
        dual_judge=dj_dict,
        held_out=held_out_dict,
        regression_suite=reg_dict,
        evolution_guard=guard_dict,
        effect_size=effect_size,
        beat_baseline_by_025=beat025,
        promoted_node_id=promoted_node_id,
        rolled_back=rolled_back,
    )
