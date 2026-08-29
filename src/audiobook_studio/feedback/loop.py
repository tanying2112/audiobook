"""M0 — 生产修正/质检结果回流为金标数据集（golden 回流）。

将生产运行中产生的用户修正（``sop_reflection.CorrectionBatch``）、流水线反馈
（``feedback.collector`` 的反馈记录）规范化为 ``data/golden/{split}/{stage}.jsonl``
样本，带 schema 校验、去重与版本戳。回流后的金标数据供后续闭环使用：

* ``feedback/canary._load_golden_examples`` 加载（train/val/test 拆分）
* ``feedback/bootstrap_fewshot`` 在 train 上编译候选提示词
* ``feedback/held_out_eval`` 在冻结的 test 上做实证门禁

这是「马具迭代」闭环的第一环：让生产结果真正回流成可学习的金标，而非仅把
人工修正写回 ``agent_sop.json`` 的 ``voice_bindings``（确定性回填）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field

from ..pipeline.sop_reflection import CorrectionBatch, UserCorrection

logger = logging.getLogger(__name__)

GOLDEN_ROOT_DEFAULT = Path("data/golden")
VALID_SPLITS = ("train", "val", "test")


class GoldenSample(BaseModel):
    """金标样本 schema（与 data/golden/{split}/{stage}.jsonl 对齐）。"""

    stage: str = Field(..., description="Pipeline stage 名（extract/analyze/annotate/edit/...）")
    input: Any = Field(..., description="Stage 输入")
    output: Any = Field(..., description="采纳输出 / 期望输出")
    rubric: Optional[str] = None
    expected: Optional[Any] = None
    source: str = "unknown"
    version: int = 1
    sample_hash: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def model_post_init(self, __context: Any) -> None:
        if not self.sample_hash:
            self.sample_hash = self.compute_hash()

    def compute_hash(self) -> str:
        payload = json.dumps(
            {"stage": self.stage, "input": self.input, "output": self.output},
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def to_jsonl(self) -> str:
        return json.dumps(self.model_dump(mode="json"), ensure_ascii=False)


def _golden_dir(golden_root: Path, split: str, stage: str) -> Path:
    return golden_root / split / stage


def _load_samples(path: Path) -> List[GoldenSample]:
    if not path.exists():
        return []
    samples: List[GoldenSample] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            samples.append(GoldenSample(**json.loads(line)))
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            logger.warning(f"skip malformed golden line in {path}: {e}")
    return samples


def _write_samples_atomic(path: Path, samples: List[GoldenSample]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".jsonl.tmp")
    tmp.write_text("\n".join(s.to_jsonl() for s in samples) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def append_golden_sample(
    stage: str,
    split: str,
    sample: Union[GoldenSample, Dict[str, Any]],
    golden_root: Path = GOLDEN_ROOT_DEFAULT,
) -> bool:
    """将一个金标样本追加到 ``data/golden/{split}/{stage}.jsonl``。

    带去重（按 input+output 的 hash）。返回是否实际新增。
    """
    if split not in VALID_SPLITS:
        raise ValueError(f"invalid split {split!r}; expected one of {VALID_SPLITS}")
    if isinstance(sample, dict):
        sample = GoldenSample(**sample)
    elif not isinstance(sample, GoldenSample):
        raise TypeError(f"sample must be GoldenSample or dict, got {type(sample).__name__}")

    sample = sample.model_copy()
    target = _golden_dir(golden_root, split, stage)
    file_path = target / f"{stage}.jsonl"
    existing = _load_samples(file_path)
    if any(s.sample_hash == sample.sample_hash for s in existing):
        logger.debug(f"skip duplicate {stage}/{split} hash={sample.sample_hash}")
        return False
    existing.append(sample)
    _write_samples_atomic(file_path, existing)
    logger.info(f"appended golden sample -> {split}/{stage} (total={len(existing)})")
    return True


def correction_to_sample(corr: UserCorrection, stage: str = "edit") -> GoldenSample:
    """将单条 TTS 参数级用户修正归一化为 edit/synthesize 阶段金标样本。"""
    input_ctx = {
        "paragraph_index": corr.paragraph_index,
        "chapter_index": corr.chapter_index,
        "field": corr.field,
        "original_value": corr.original_value,
        **corr.context,
    }
    return GoldenSample(
        stage=stage,
        input=input_ctx,
        output={"field": corr.field, "value": corr.corrected_value},
        source="user_correction",
        rubric=(f"用户将 {corr.field} 从 {corr.original_value} 修正为 {corr.corrected_value}"),
    )


def corrections_to_golden(
    batch: CorrectionBatch,
    split: str = "val",
    stage: str = "edit",
    golden_root: Path = GOLDEN_ROOT_DEFAULT,
) -> int:
    """将一批 ``CorrectionBatch`` 回流为金标样本，返回实际新增条数。"""
    added = 0
    for corr in batch.corrections:
        if append_golden_sample(stage, split, correction_to_sample(corr, stage), golden_root):
            added += 1
    return added


def feedback_record_to_sample(record: Any, stage: Optional[str] = None) -> Optional[GoldenSample]:
    """将（鸭子类型的）流水线反馈记录转为金标样本；无法转换则返回 None。"""
    stage = stage or getattr(record, "stage", None)
    if not stage:
        return None
    inp = getattr(record, "input", None) or {}
    out = getattr(record, "output", None) or getattr(record, "corrected_output", None)
    if out is None:
        return None
    return GoldenSample(
        stage=stage,
        input=inp,
        output=out,
        source="feedback_record",
        rubric=getattr(record, "rubric", None),
    )


def ingest_corrections(
    collector: Any,
    split: str = "val",
    stage: str = "edit",
    max_drain: int = 200,
    golden_root: Path = GOLDEN_ROOT_DEFAULT,
) -> int:
    """从 ``CorrectionCollector`` 抽干当前队列并回流为金标样本。"""
    batch = collector.get_batch(max_size=max_drain)
    if not batch:
        return 0
    cb = CorrectionBatch(
        corrections=batch,
        genre="default",
        project_id=0,
        collected_at=datetime.now(timezone.utc).isoformat(),
    )
    return corrections_to_golden(cb, split=split, stage=stage, golden_root=golden_root)


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="回流生产修正为金标数据集 (M0)")
    parser.add_argument("--split", default="val", choices=VALID_SPLITS)
    parser.add_argument("--stage", default="edit")
    parser.add_argument("--golden-root", default=str(GOLDEN_ROOT_DEFAULT))
    parser.add_argument(
        "--drain-collector",
        action="store_true",
        help="从全局 CorrectionCollector 抽干并回流",
    )
    parser.add_argument(
        "--from-jsonl",
        help="从修正 jsonl（每行一个 UserCorrection 字典）读取并回流",
    )
    args = parser.parse_args(argv)
    golden_root = Path(args.golden_root)

    if args.drain_collector:
        from ..pipeline.sop_reflection import get_correction_collector

        n = ingest_corrections(get_correction_collector(), args.split, args.stage, golden_root=golden_root)
        print(f"ingested {n} corrections -> {args.split}/{args.stage}")
        return

    if args.from_jsonl:
        added = 0
        with open(args.from_jsonl, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                corr = UserCorrection(**json.loads(line))
                if append_golden_sample(args.stage, args.split, correction_to_sample(corr, args.stage), golden_root):
                    added += 1
        print(f"ingested {added} samples from {args.from_jsonl} -> {args.split}/{args.stage}")
        return

    parser.error("must specify --drain-collector or --from-jsonl")


if __name__ == "__main__":
    main()
