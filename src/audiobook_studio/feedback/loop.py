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
        sample_obj = GoldenSample(**sample)
    elif isinstance(sample, GoldenSample):
        sample_obj = sample
    else:
        raise TypeError(f"sample must be GoldenSample or dict, got {type(sample).__name__}")

    sample_obj = sample_obj.model_copy()
    target = _golden_dir(golden_root, split, stage)
    file_path = target / f"{stage}.jsonl"
    existing = _load_samples(file_path)
    if any(s.sample_hash == sample_obj.sample_hash for s in existing):
        logger.debug(f"skip duplicate {stage}/{split} hash={sample_obj.sample_hash}")
        return False
    existing.append(sample_obj)
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


def _coerce_dict(obj: Any) -> Any:
    """把 pydantic/dataclass/dict/对象 统一成可 JSON 序列化的 dict 或原值。"""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: _coerce_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_coerce_dict(v) for v in obj]
    model_dump = getattr(obj, "model_dump", None)
    if callable(model_dump):
        try:
            return _coerce_dict(model_dump(mode="json"))
        except (TypeError, ValueError):
            return _coerce_dict(model_dump())
    # dataclass
    fields = getattr(obj, "__dataclass_fields__", None)
    if fields is not None:
        from dataclasses import asdict

        return _coerce_dict(asdict(obj))
    if isinstance(obj, BaseModel):
        return _coerce_dict(obj.model_dump())
    if hasattr(obj, "__dict__"):
        return {k: _coerce_dict(v) for k, v in vars(obj).items()}
    return obj


def quality_judgment_to_sample(
    judgment: Any,
    *,
    annotation: Any = None,
    reference_text: str = "",
    audio_description: Optional[str] = None,
    stage: str = "judge",
    source: str = "quality_check",
) -> GoldenSample:
    """将单条质检判定（QualityJudgment）归一化为 judge/quality 阶段金标样本。

    质检模块（``pipeline.quality_check``）对每段音频产出 ``QualityJudgment``：
    ``needs_regeneration``（pass/fail）+ 各维度得分 + ``issues``（原因）+ ``fix_suggestions``。
    回流时把「输入（段落标注 + 音频描述 + 参考文本）→ 期望输出（判定本身）」固化成
    judge 阶段金标，使评判者自身的 verdict 成为可学习、可回归的金标数据。
    """
    needs_regen = bool(getattr(judgment, "needs_regeneration", False))
    passed = not needs_regen
    issues = list(getattr(judgment, "issues", []) or [])
    reasons = "; ".join(str(i) for i in issues) if issues else ("PASS" if passed else "FAIL")
    rubric = (
        f"quality_check verdict: {'PASS' if passed else 'FAIL'} "
        f"(overall={getattr(judgment, 'overall_score', None)}); reasons={reasons}"
    )
    inp: Dict[str, Any] = {
        "segment_id": getattr(judgment, "segment_id", None),
        "paragraph_annotation": _coerce_dict(annotation) if annotation is not None else None,
        "audio_description": audio_description or "",
        "reference_text": reference_text or "",
    }
    out = _coerce_dict(judgment)
    return GoldenSample(
        stage=stage,
        input=inp,
        output=out,
        source=source,
        rubric=rubric,
    )


def quality_judgments_to_golden(
    judgments: List[Any],
    annotations: Optional[List[Any]] = None,
    reference_texts: Optional[List[str]] = None,
    audio_descriptions: Optional[List[Optional[str]]] = None,
    *,
    split: str = "val",
    stage: str = "judge",
    golden_root: Path = GOLDEN_ROOT_DEFAULT,
) -> int:
    """将一批质检判定回流为 judge 阶段金标样本，返回实际新增条数。

    ``annotations`` / ``reference_texts`` 与 ``judgments`` 一一对应（可选）。
    ``audio_descriptions`` 与 ``judgments`` 一一对应（可选），用于富化 judge 样本输入。
    """
    added = 0
    for idx, judgment in enumerate(judgments):
        annotation = annotations[idx] if annotations and idx < len(annotations) else None
        reference_text = reference_texts[idx] if reference_texts and idx < len(reference_texts) else ""
        audio_description = audio_descriptions[idx] if audio_descriptions and idx < len(audio_descriptions) else None
        sample = quality_judgment_to_sample(
            judgment,
            annotation=annotation,
            reference_text=reference_text,
            audio_description=audio_description,
            stage=stage,
        )
        if append_golden_sample(stage, split, sample, golden_root):
            added += 1
    return added


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
    parser.add_argument(
        "--from-qc-jsonl",
        help="从质检判定 jsonl 回流为 judge 样本（每行 {judgment, annotation?, reference_text?, audio_description?}）",
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

    if args.from_qc_jsonl:
        added = 0
        with open(args.from_qc_jsonl, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                judgment = rec["judgment"]
                sample = quality_judgment_to_sample(
                    judgment,
                    annotation=rec.get("annotation"),
                    reference_text=rec.get("reference_text", ""),
                    audio_description=rec.get("audio_description"),
                    stage=args.stage,
                )
                if append_golden_sample(args.stage, args.split, sample, golden_root):
                    added += 1
        print(f"ingested {added} quality judgments from {args.from_qc_jsonl} -> {args.split}/{args.stage}")
        return

    parser.error("must specify --drain-collector or --from-jsonl")


if __name__ == "__main__":
    main()
