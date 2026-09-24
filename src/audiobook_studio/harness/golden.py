"""金标数据集管理：在 harness 存储之上提供三集(train/val/test)隔离的样本管理。

薄封装：底层复用 ``harness.storage.Storage`` 的双写（SQLite 元数据 + JSONL 明细），
并暴露迭代/测试所需的 ``ingest_corrections`` / ``append_sample`` / ``load_samples``
/ ``get_stats`` 接口。这是把缺失的 ``harness.golden`` 模块补齐，使其与
``harness.harness`` 及集成测试契约对齐。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional

from .storage import get_storage

logger = logging.getLogger(__name__)

DEFAULT_TEST_GOLDEN_ROOT = Path("data/golden/harness")
DEFAULT_PROMPTS_DIR = Path("prompts")


@dataclass
class GoldenStats:
    """三集样本统计（属性访问，供测试/看板使用）。"""

    train_count: int = 0
    val_count: int = 0
    test_count: int = 0
    total_count: int = 0


class GoldenDatasetManager:
    """三集隔离的金标数据集管理。"""

    def __init__(self, storage: Optional[Any] = None):
        self._storage = storage or get_storage()

    # ── 写入 ────────────────────────────────────────────────────────────────
    def ingest_corrections(self, corrections: List[Dict[str, Any]], split: str, stage: str) -> int:
        """把纠错记录转为金标样本并回流到指定 split；返回实际新增条数。"""
        added = 0
        for c in corrections:
            record = {
                "stage": stage,
                "input": {
                    "field": c.get("field"),
                    "original_value": c.get("original_value"),
                    "context": c.get("context", {}),
                    "paragraph_index": c.get("paragraph_index"),
                    "chapter_index": c.get("chapter_index"),
                },
                "output": {"corrected_value": c.get("corrected_value")},
                "source": "correction",
            }
            if self._storage.append_golden_sample(split, stage, record):
                added += 1
        return added

    def append_sample(self, stage: str, split: str, sample: Dict[str, Any]) -> bool:
        """追加单条样本到指定 split；重复 hash 返回 False（去重拦截）。"""
        record = dict(sample)
        record.setdefault("stage", stage)
        return self._storage.append_golden_sample(split, stage, record)

    # ── 读取 ────────────────────────────────────────────────────────────────
    def load_samples(self, stage: str, split: str) -> List[Any]:
        """加载某 split/stage 下的样本，以 ``SimpleNamespace`` 暴露 ``.sample_hash``。"""
        records = self._storage.jsonl.load_all_list(split, stage)
        return [SimpleNamespace(**r) for r in records]

    def get_stats(self) -> GoldenStats:
        counts = self._storage.get_golden_stats()
        return GoldenStats(
            train_count=counts.get("train", 0),
            val_count=counts.get("val", 0),
            test_count=counts.get("test", 0),
            total_count=counts.get("total", 0),
        )


def append_golden_sample(split: str, stage: str, record: Dict[str, Any]) -> bool:
    """模块级便捷函数：追加一条金标样本到指定 split。"""
    return GoldenDatasetManager().append_sample(stage, split, record)


def evaluate_on_harness_golden(
    stage: str,
    run_fn: Callable[[Dict[str, Any]], Any],
    judge,
    *,
    baseline_fn: Optional[Callable[[Dict[str, Any]], Any]] = None,
    split: str = "test",
) -> Dict[str, Any]:
    """在 harness 自有留出集（平铺布局 ``data/golden/harness/{split}/{stage}.jsonl``）
    上评估候选 vs 基线，实现 harness 自洽：不借用 feedback 的 ``run_candidate_on_held_out``
    （其读取嵌套布局 ``data/golden/{split}/{stage}/``），避免两套件共用工作树时的数据耦合。

    返回与反馈侧 ``CandidateEvalResult`` 等价的聚合字典
    （``case_count / mean_score / baseline_mean / effect_size``）。
    """
    mgr = GoldenDatasetManager()
    samples = mgr.load_samples(stage, split)

    def _score_one(sample, fn) -> float:
        rec = sample.__dict__ if hasattr(sample, "__dict__") else dict(sample)
        inp = dict(rec.get("input") or {})
        exp = rec.get("expected_output")
        if exp is None:
            exp = rec.get("output") or {}
        if not isinstance(exp, dict):
            exp = {"value": exp}
        try:
            out = fn(inp)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[harness-eval] run_fn 抛错，该例置 0: %s", exc)
            return 0.0
        try:
            s = float(judge.score(inp, out, exp, stage))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[harness-eval] judge 抛错，该例置 0: %s", exc)
            return 0.0
        if s != s:  # NaN
            return 0.0
        return max(0.0, min(1.0, s))

    cand = [_score_one(s, run_fn) for s in samples]
    mean = sum(cand) / len(cand) if cand else 0.0
    baseline_mean: Optional[float] = None
    effect: Optional[float] = None
    if baseline_fn is not None:
        base = [_score_one(s, baseline_fn) for s in samples]
        baseline_mean = sum(base) / len(base) if base else 0.0
        effect = mean - baseline_mean
    return {
        "case_count": len(samples),
        "mean_score": mean,
        "baseline_mean": baseline_mean,
        "effect_size": effect,
    }
