"""离线 DSPy/GEPA 实验：为「学习型候选生成」提供可复现的实验证据。

本模块把 feedback/bootstrap_fewshot 的真实 GEPA 多目标优化（角色识别 + Voice Design）
在离线（MockLM）或真实本地 LLM 模式下跑一遍，并把结果落盘到
``data/harness/learned_experiment.jsonl``，作为「learned 候选 ≠ rule-based 候选」的
实证记录。

离线说明（诚实起见）：
- 在 ``MOCK_LLM=true`` 下，GEPA 仍会完整执行（预算 500 / 早停 / Pareto 前沿），但
  MockLM 无法给出有意义的字符/语音准确率，故 ``improvement_ratio`` 等会退化为 0。
  该记录证明「集成链路端到端跑通」，不代表真实质量收益。
- 接入真实本地 LLM（如 Ollama，``MOCK_LLM`` 留空）后，这些指标才是真实收益。
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_STAGES: List[str] = [
    "annotate_paragraph",
    "edit_for_tts",
    "judge",
]


def _eval_mode() -> str:
    return "mock" if os.getenv("MOCK_LLM", "false").lower() in ("1", "true", "yes") else "real"


def _golden_test_exists(stage: str, golden_root: Path) -> bool:
    return (golden_root / "test" / f"{stage}.jsonl").exists()


def run_learned_experiment(
    stages: Optional[List[str]] = None,
    few_shot_path: str = "tests/golden/bootstrap_examples.json",
    out_path: Optional[str] = None,
    golden_root: Optional[Path] = None,
    prompts_root: Optional[Path] = None,
    run_fn: Optional[Callable[[Dict[str, Any]], Any]] = None,
    judge: Optional[Any] = None,
    k: int = 1,
) -> List[Dict[str, Any]]:
    """运行学习型候选生成的离线实验，返回每条 stage 的证据记录。

    Args:
        stages: 待实验的 stage 列表；默认 ``DEFAULT_STAGES``。
        few_shot_path: 传给 GEPA 的训练样本路径。
        out_path: 证据落盘路径；默认 ``data/harness/learned_experiment.jsonl``。
        golden_root: harness 金标根目录（用于可选的候选评估）。
        prompts_root: 候选 prompt 落盘根目录（测试可传入 tmp）。
        run_fn / judge: 可选，用于在有金标测试集时对 rule-based / learned 候选做评估。
        k: few-shot 示例数。

    Returns:
        证据记录列表（同时追加写入 ``out_path``）。
    """
    from ..feedback.bootstrap_fewshot import run_bootstrap_optimization
    from .prompt_evolution import PromptEvolutionEngine

    stages = list(stages or DEFAULT_STAGES)
    golden_root = Path(golden_root) if golden_root else Path("data") / "golden" / "harness"
    prompts_root = Path(prompts_root) if prompts_root else Path("prompts") / "harness"
    out_path = out_path or str(Path("data") / "harness" / "learned_experiment.jsonl")

    records: List[Dict[str, Any]] = []

    for stage in stages:
        record: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
            "eval_mode": _eval_mode(),
            "few_shot_path": few_shot_path,
        }

        # 1) 真实 GEPA 多目标优化（端到端证据）
        try:
            opt = run_bootstrap_optimization(stage, few_shot_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[learned_experiment] GEPA 优化失败 %s: %s", stage, exc)
            opt = None

        if opt is not None:
            m = getattr(opt, "metrics", None)
            record.update(
                {
                    "optimized_prompt_len": len(opt.optimized_prompt or ""),
                    "improvement_ratio": getattr(opt, "improvement_ratio", None),
                    "character_recognition_accuracy": getattr(m, "character_recognition_accuracy", None),
                    "voice_design_accuracy": getattr(m, "voice_design_accuracy", None),
                    "iterations_completed": getattr(opt, "iterations_completed", None),
                    "stopped_early": getattr(opt, "stopped_early", None),
                    "pareto_frontier_size": len(getattr(opt, "pareto_frontier", None) or []),
                }
            )
        else:
            record.update(
                {
                    "optimized_prompt_len": 0,
                    "improvement_ratio": None,
                    "character_recognition_accuracy": None,
                    "voice_design_accuracy": None,
                    "iterations_completed": None,
                    "stopped_early": None,
                    "pareto_frontier_size": 0,
                }
            )

        # 2) rule-based vs learned 候选编译（证明两条路径都产出候选，且 learned 有差异）
        try:
            rb = PromptEvolutionEngine().compile_candidate(stage, k=k, prompts_root=prompts_root, use_learned=False)
            record["rulebased_candidate_version"] = rb["version"]
            record["rulebased_learned_flag"] = rb.get("learned")
        except Exception as exc:  # noqa: BLE001
            logger.warning("[learned_experiment] rule-based 编译失败 %s: %s", stage, exc)
            record["rulebased_candidate_version"] = None

        try:
            ln = PromptEvolutionEngine().compile_candidate(stage, k=k, prompts_root=prompts_root, use_learned=True)
            record["learned_candidate_version"] = ln["version"]
            record["learned_learned_flag"] = ln.get("learned")
        except Exception as exc:  # noqa: BLE001
            logger.warning("[learned_experiment] learned 编译失败 %s: %s", stage, exc)
            record["learned_candidate_version"] = None

        # 3) 可选的候选评估（仅当 harness 金标 test 集存在）
        if run_fn is not None and judge is not None and _golden_test_exists(stage, golden_root):
            try:
                from .golden import evaluate_on_harness_golden

                rb_eval = evaluate_on_harness_golden(stage=stage, run_fn=run_fn, judge=judge, split="test")
                record["rulebased_eval_mean_score"] = rb_eval.get("mean_score")
                record["eval_case_count"] = rb_eval.get("case_count")
            except Exception as exc:  # noqa: BLE001
                logger.warning("[learned_experiment] 候选评估失败 %s: %s", stage, exc)
        else:
            record["rulebased_eval_mean_score"] = None
            record["eval_case_count"] = None

        records.append(record)
        logger.info("[learned_experiment] %s 完成：%s", stage, record)

    # 落盘
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    return records


def load_experiment_records(out_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """读取已落盘的实验证据。"""
    out_path = out_path or str(Path("data") / "harness" / "learned_experiment.jsonl")
    p = Path(out_path)
    if not p.exists():
        return []
    records = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records
