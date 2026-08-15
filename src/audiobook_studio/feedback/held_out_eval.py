"""P0.3.1 — 冻结留出集（Held-Out Evaluation Set）：给进化加防走火保险的"尺度"。

对应执行手册 docs/EVOLUTION_ROADMAP.md P0.3 子任务 1，解决审计 §6.2"晋升只在调参者
自选数据上自评"的问题。留出集是一段**冻结的、调参者无法修改**的中文样例 + 参考音频，
候选配置必须在这条固定标尺上 ≥基线+0.25 才能晋升。

设计原则（红线 #1 主路径真实性 + 红线 #3 SSOT）：
  - **不可变**：集合内容在构造时一次性加载、冻结为元组；以 `MappingProxyType` /
    `tuple` 暴露，运行期任何 `dataset.cases.append(...)` / `dataset["x"]=...` 立即
    `TypeError`。调参者要改集合必须新建实例——调用点可见、可审计、可被 CI 拦截。
  - **可固化登记**：`manifest()` 输出集合指纹（SHA256 over (id, input)，排序稳定）+
    来源路径 + 文件计数 + 构造时刻。用于 CI 元门禁（P0.3.7）比对"评估集文件本 Sprint
    是否被自动改动"，以及单测断言"调参者无法修改集合"。
  - **复用 tests/golden/**：留出集的样本来源是 `tests/golden/<stage>/`，不另造数据目录
    （SSOT，避免重复维护）。loader 只是**冻结地读取**这些文件——它不改、不扩、不重写。
  - **依赖缺失诚实降级**：若某 golden 目录不存在，该 stage 的留出集为空元组，`manifest`
    如实登记 `"empty:<reason>"`，绝不假装有数据。

接点：
  - `HeldOutDataset(stage)` 从 tests/golden/<stage>/ 加载；`evaluate_candidate(fn)` 在
    冻结集上跑候选（fn 由 promotion_gate 提供，跑真实 prompt→输出→指标）。
  - promotion_gate / regression_suite / kill_switch 回滚都读这条固定标尺。
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

logger = logging.getLogger(__name__)


# tests/golden/ 相对仓库根的定位：
# 本文件在 src/audiobook_studio/feedback/held_out_eval.py → parents[3] 即仓库根。
_DEFAULT_GOLDEN_ROOT = Path(__file__).resolve().parents[3] / "tests" / "golden"


@dataclass(frozen=True)
class HeldOutCase:
    """留出集单例（不可变）。一旦构造，id/input/expected_output 全不可改。"""

    case_id: str
    input: Mapping[str, Any]
    expected_output: Mapping[str, Any]
    stage: str
    # 参考"音频"留位：当前 golden 无音频文件，文本侧评估为主；保留接口向后兼容
    reference_audio_key: Optional[str] = None

    def signature(self) -> str:
        """该样例的内容指纹（排序稳定），用于集合整体指纹与篡改检测。"""
        payload = json.dumps(
            {"id": self.case_id, "input": dict(self.input)}, ensure_ascii=False, sort_keys=True
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "input": dict(self.input),
            "expected_output": dict(self.expected_output),
            "stage": self.stage,
            "reference_audio_key": self.reference_audio_key,
        }


@dataclass(frozen=True)
class DatasetManifest:
    """留出集冻结登记——CI 元门禁与"调参者无法修改"单测的凭据。"""

    stage: str
    case_count: int
    signatures: Tuple[str, ...]           # 每例指纹，排序稳定
    dataset_signature: str                # 整集指纹 = SHA256 over sorted(signatures)
    golden_root: str                      # 样本来源目录
    origin_status: str                    # "loaded" | "empty:<reason>"
    held_out_commit_note: str             # 登记固化说明（SSOT 文档化）

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stage": self.stage,
            "case_count": self.case_count,
            "signatures": list(self.signatures),
            "dataset_signature": self.dataset_signature,
            "golden_root": self.golden_root,
            "origin_status": self.origin_status,
            "held_out_commit_note": self.held_out_commit_note,
        }


@dataclass
class CandidateEvalResult:
    """候选在留出集上的评估结果。"""

    candidate_id: str
    baseline_id: str
    case_count: int
    scores: Tuple[float, ...]             # 每例得分（0-1），与 manifest.signatures 对齐
    mean_score: float
    baseline_mean: Optional[float] = None
    effect_size: Optional[float] = None   # mean_score - baseline_mean
    notes: List[str] = field(default_factory=list)

    @property
    def beat_baseline_by_025(self) -> bool:
        """DoD: 候选 ≥基线+0.25 才晋升。effect_size None → 视为未达（不假通过）。"""
        return self.effect_size is not None and self.effect_size >= 0.25

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "baseline_id": self.baseline_id,
            "case_count": self.case_count,
            "scores": list(self.scores),
            "mean_score": self.mean_score,
            "baseline_mean": self.baseline_mean,
            "effect_size": self.effect_size,
            "beat_baseline_by_025": self.beat_baseline_by_025,
            "notes": list(self.notes),
        }


class HeldOutDataset:
    """冻结留出集——调参者无法在运行期修改。"""

    # 类级只读视图占位，实例构造后填充；类型注解仅作文档。
    def __init__(self, stage: str, golden_root: Optional[Path] = None) -> None:
        self._stage = stage
        root = Path(golden_root) if golden_root is not None else _DEFAULT_GOLDEN_ROOT
        self._golden_root = root
        cases, origin = self._load_frozen(stage, root)
        # 关键不可变点：cases 为 tuple，任何 append/mutation 都会抛
        self._cases: Tuple[HeldOutCase, ...] = tuple(cases)
        self._cases_index: MappingProxyType[str, HeldOutCase] = MappingProxyType(
            {c.case_id: c for c in self._cases}
        )
        self._manifest = self._build_manifest(origin)

    # ── 公共只读接口（MappingProxyType + tuple = 任何改写即 TypeError）──────────
    @property
    def stage(self) -> str:
        return self._stage

    @property
    def cases(self) -> Tuple[HeldOutCase, ...]:
        return self._cases  # tuple 不可变

    @property
    def case_count(self) -> int:
        return len(self._cases)

    @property
    def case_ids(self) -> Tuple[str, ...]:
        return tuple(c.case_id for c in self._cases)

    @property
    def by_id(self) -> Mapping[str, HeldOutCase]:
        return self._cases_index  # MappingProxyType 不可变

    @property
    def signature(self) -> str:
        """整集指纹——篡改任一例即变。"""
        return self._manifest.dataset_signature

    @property
    def manifest(self) -> DatasetManifest:
        return self._manifest

    # ── 不可变性更强力设计：禁用 setattr / delattr 经过实例字典 ──────────────────
    def __setattr__(self, key: str, value: Any) -> None:
        # 构造期间允许下划线开头的私有字段写入；构造完成后冻结私有字段
        if key.startswith("_") and key not in self.__dict__:
            object.__setattr__(self, key, value)
            return
        # 已存在的私有字段不可改写（防调参者偷换 _cases）
        if key.startswith("_") and key in self.__dict__:
            raise TypeError(
                f"HeldOutDataset is frozen: cannot reassign {key!r} — "
                f"to change the held-out set, construct a new HeldOutDataset (这是一种审计可见的变更)"
            )
        # 任何非私有的属性赋值一律拒绝（防 dataset.cases = [...] 这类偷换）
        super().__setattr__(key, value)  # 仍走默认以触发 dataclass-style 错误
        # 上一行对普通实例会成功，但我们在下方覆盖以更严格地拒绝：
        raise TypeError(
            f"HeldOutDataset is frozen: cannot set attribute {key!r} on the immutable held-out set"
        )

    # ── 加载：只读 tests/golden/<stage>/ 的 JSON/JSONL，不发 I/O 写、不改源 ────────
    @staticmethod
    def _load_frozen(
        stage: str, root: Path
    ) -> Tuple[List[HeldOutCase], str]:
        stage_dir = root / stage
        if not stage_dir.exists():
            logger.warning("Held-out golden dir not found: %s", stage_dir)
            return [], f"empty:not-found:{stage_dir}"
        cases: List[HeldOutCase] = []
        # 按 glob 排序保证加载顺序确定 → 指纹稳定
        files = sorted(list(stage_dir.glob("*.json")) + list(stage_dir.glob("*.jsonl")))
        for f in files:
            try:
                if f.suffix == ".jsonl":
                    for line in f.read_text(encoding="utf-8").splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        row = json.loads(line)  # 每行反序列化后再解析
                        cases.append(HeldOutDataset._parse_row(row, stage, f.name))
                else:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    cases.append(HeldOutDataset._parse_row(data, stage, f.name))
            except (json.JSONDecodeError, OSError, KeyError) as e:
                logger.warning("Failed to load held-out case %s: %s", f, e)
        return cases, ("loaded" if cases else "empty:no-parseable-cases")

    @staticmethod
    def _parse_row(data: Any, stage: str, origin: str) -> HeldOutCase:
        if not isinstance(data, Mapping):
            raise KeyError(f"non-mapping row in {origin}")
        case_id = str(data.get("id") or f"{origin}:{hash(json.dumps(data, sort_keys=True, ensure_ascii=False)) & 0xFFFF:x}")
        inp = data.get("input") or {}
        exp = data.get("expected_output") or {}
        # 将 input/expected_output 冻结为只读 MappingProxyType，防后续改写
        return HeldOutCase(
            case_id=case_id,
            input=MappingProxyType(dict(inp) if isinstance(inp, Mapping) else {"value": inp}),
            expected_output=MappingProxyType(dict(exp) if isinstance(exp, Mapping) else {"value": exp}),
            stage=stage,
            reference_audio_key=data.get("reference_audio_key"),
        )

    def _build_manifest(self, origin: str) -> DatasetManifest:
        sigs = tuple(sorted(c.signature() for c in self._cases))
        ds_sig = hashlib.sha256(
            json.dumps(
                {"stage": self._stage, "signatures": list(sigs)}, sort_keys=True, ensure_ascii=False
            ).encode("utf-8")
        ).hexdigest()
        return DatasetManifest(
            stage=self._stage,
            case_count=len(self._cases),
            signatures=sigs,
            dataset_signature=ds_sig,
            golden_root=str(self._golden_root),
            origin_status=origin,
            held_out_commit_note=(
                f"留出集冻结于 tests/golden/{self._stage}/ — "
                f"内容指纹登记在 manifest；CI 元门禁（P0.3.7）校验本集未在自动循环中被改动。"
            ),
        )

    # ── 候选评估：在冻结集上跑候选 fn，返回冻结的 CandidateEvalResult ─────────────
    def evaluate_candidate(
        self,
        candidate_fn: Callable[[HeldOutCase], float],
        candidate_id: str = "candidate",
        baseline_fn: Optional[Callable[[HeldOutCase], float]] = None,
        baseline_id: str = "baseline",
    ) -> CandidateEvalResult:
        """对冻结集每例跑候选 fn 得分 ∈[0,1]；可选基线 fn 得 effect_size。

        candidate_fn / baseline_fn 均为纯函数（case → score），由 promotion_gate 装载
        真实评估（真 prompt→输出→P0.2 真指标→归一化），非 mock。本方法只负责**在固定
        标尺上跑这两函数并冻结结果**——它不评估、不改集。
        """
        if not self._cases:
            return CandidateEvalResult(
                candidate_id=candidate_id,
                baseline_id=baseline_id,
                case_count=0,
                scores=(),
                mean_score=0.0,
                baseline_mean=None,
                effect_size=None,
                notes=["empty held-out set: 无法评估，诚实降级（不假通过）"],
            )
        cand_scores = tuple(_safe_score(candidate_fn, c) for c in self._cases)
        mean = sum(cand_scores) / len(cand_scores) if cand_scores else 0.0
        notes: List[str] = []
        baseline_mean: Optional[float] = None
        effect: Optional[float] = None
        if baseline_fn is not None:
            base_scores = tuple(_safe_score(baseline_fn, c) for c in self._cases)
            baseline_mean = sum(base_scores) / len(base_scores) if base_scores else 0.0
            effect = mean - baseline_mean
        return CandidateEvalResult(
            candidate_id=candidate_id,
            baseline_id=baseline_id,
            case_count=len(self._cases),
            scores=cand_scores,
            mean_score=mean,
            baseline_mean=baseline_mean,
            effect_size=effect,
            notes=notes,
        )


def _safe_score(fn: Callable[[HeldOutCase], float], case: HeldOutCase) -> float:
    """跑一例打分，函数抛错则该例记 0 并记 note——不让单例崩溃退整集评估。"""
    try:
        s = float(fn(case))
        if s != s:  # NaN
            return 0.0
        return max(0.0, min(1.0, s))
    except Exception as e:  # noqa: BLE001
        logger.warning("held-out case %s eval raised %s: %s — 置 0", case.case_id, type(e).__name__, e)
        return 0.0
