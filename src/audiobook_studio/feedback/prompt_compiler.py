"""M3 — 编译主路径：在 golden train 上把高质样本编译为候选提示词（few-shot）。

设计原则（红线 #3 SSOT + 不训练模型）：
* 不依赖 dspy。dspy 未装时，本模块用确定性的「top-K 金标样例」编译法生成候选
  prompt：取 train 集中质量最高的 K 条样本（judge/quality 阶段按 overall_score 与
  是否通过筛选，其余阶段默认全部视为金标），嵌入到 active prompt 模板之后。
* 候选只**写入** ``prompts/<dir>/v{N+1}.j2``，**不晋升**；晋升由 M4 的 PromotionGate 决定。
* 全程确定性、可复现：同输入同输出，不触网、不调用 LLM。

实际可替换：若 ``bootstrap_fewshot`` 的 DSPy 优化器可用，可在外部用其产出候选文本后，
直接调用 :func:`write_candidate_prompt` 落盘，本模块负责版本化与降级编译。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .canary import _load_golden_examples, _pipeline_stage_to_prompt_dir

logger = logging.getLogger(__name__)

DEFAULT_PROMPTS_DIR = Path("prompts")
DEFAULT_GOLDEN_ROOT = Path("data/golden")

# golden stage 名 → prompts/ 目录名（补齐 canary 映射未覆盖的 judge/quality/translate 等）。
_STAGE_TO_PROMPT_DIR: Dict[str, str] = {
    "extract": "extract",
    "analyze": "analyze_structure",
    "annotate": "annotate_paragraph",
    "edit": "edit_for_tts",
    "judge": "quality_judge",
    "quality": "quality_judge",
    "quality_judge": "quality_judge",
    "translate": "translate",
    "synthesize": "tts_routing",
}


def stage_to_prompt_dir(stage: str) -> str:
    """把 golden stage 名解析为 prompts/ 目录名。"""
    if stage in _STAGE_TO_PROMPT_DIR:
        return _STAGE_TO_PROMPT_DIR[stage]
    # 回落到 canary 映射（edit/annotate/analyze/extract/quality/synthesize 已覆盖）
    return _pipeline_stage_to_prompt_dir(stage)


def _output_of(sample: Dict[str, Any]) -> Any:
    return sample.get("output", sample.get("expected_output"))


def _goodness(sample: Dict[str, Any], stage: str) -> float:
    """金标样本质量分（0-1），用于挑选 few-shot 示例。"""
    out = _output_of(sample)
    if isinstance(out, dict):
        if "needs_regeneration" in out:
            # judge/quality：通过且分数高者优先
            if out.get("needs_regeneration"):
                return 0.0
            try:
                return float(out.get("overall_score", 1.0))
            except (TypeError, ValueError):
                return 1.0
        # 其余阶段：有非空输出即视为金标（满分）
        if out:
            return 1.0
    return 0.5


def select_fewshot_examples(train_samples: List[Dict[str, Any]], k: int, stage: str) -> List[Dict[str, Any]]:
    """确定性挑选 top-K 金标样本（质量降序，同分按 sample_hash 升序）。"""
    indexed = list(enumerate(train_samples))
    indexed.sort(
        key=lambda iv: (
            -_goodness(iv[1], stage),
            str(iv[1].get("sample_hash", json.dumps(iv[1], sort_keys=True, ensure_ascii=False))),
        )
    )
    return [s for _, s in indexed[:k]]


def _format_example(sample: Dict[str, Any], stage: str) -> str:
    inp = sample.get("input", {})
    out = _output_of(sample)
    return (
        "### 样例\n"
        f"输入:\n{json.dumps(inp, ensure_ascii=False, indent=2)}\n"
        f"输出:\n{json.dumps(out, ensure_ascii=False, indent=2)}"
    )


def _read_active_prompt(prompt_dir: str, prompts_root: Path) -> tuple[int, Optional[str]]:
    """读取某 prompt 目录中当前生效（最大版本号）的模板。"""
    d = prompts_root / prompt_dir
    if not d.is_dir():
        return 0, None
    versions = []
    for f in d.glob("v*.j2"):
        try:
            versions.append(int(f.stem[1:]))
        except ValueError:
            continue
    if not versions:
        return 0, None
    v = max(versions)
    return v, (d / f"v{v}.j2").read_text(encoding="utf-8")


@dataclass
class CandidatePrompt:
    """M3 编译产出的候选 prompt（尚未晋升）。"""

    stage: str
    prompt_dir: str
    version: int
    prompt_text: str
    exemplars: List[Dict[str, Any]] = field(default_factory=list)
    base_version: int = 0
    train_used: int = 0
    selection_note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stage": self.stage,
            "prompt_dir": self.prompt_dir,
            "version": self.version,
            "base_version": self.base_version,
            "train_used": self.train_used,
            "exemplar_count": len(self.exemplars),
            "selection_note": self.selection_note,
        }


def compile_candidate_prompt(
    stage: str,
    *,
    k: int = 3,
    golden_root: Optional[Path] = None,
    prompts_root: Optional[Path] = None,
    base_prompt: Optional[str] = None,
    exemplars: Optional[List[Dict[str, Any]]] = None,
) -> CandidatePrompt:
    """在 golden train 上编译候选 prompt（仅编译，不落盘）。

    Args:
        stage: golden stage 名（extract/analyze/annotate/edit/judge/quality/...）。
        k: 选取的 few-shot 示例数。
        golden_root: 金标根目录，默认 ``data/golden``。
        prompts_root: prompts 根目录，默认 ``prompts``。
        base_prompt: 若提供则作为基础模板，否则读取该 stage 当前 active 模板。
        exemplars: 若提供则跳过 train 选取，直接使用给定示例（测试/外部优化器注入）。
    """
    # 注：golden_root 为预留参数，当前 _load_golden_examples 从仓库相对路径
    # (data/golden) 读取；未来若需自定义根目录可在此注入。
    root = prompts_root or DEFAULT_PROMPTS_DIR
    prompt_dir = stage_to_prompt_dir(stage)

    if exemplars is None:
        train = _load_golden_examples(stage, "train") or []
        exemplars = select_fewshot_examples(train, k, stage)

    if base_prompt is None:
        base_v, base_text = _read_active_prompt(prompt_dir, root)
        base_prompt = base_text if base_text is not None else _default_skeleton(stage)
        base_version = base_v
    else:
        base_version = _read_active_prompt(prompt_dir, root)[0]

    fewshot_block = "\n\n".join(_format_example(e, stage) for e in exemplars)
    prompt_text = (
        f"{base_prompt}\n\n" f"# 自迭代编译的参考样例 (train 金标 top-{len(exemplars)})\n" f"{fewshot_block}\n"
    )

    # 新候选版本号 = 当前最大版本 + 1（目录不存在时从 v1 起）
    next_version = (_read_active_prompt(prompt_dir, root)[0] + 1) or 1

    note = (
        f"从 train 金标选取 {len(exemplars)} 条 top-K 示例编译候选" if exemplars is not None else "使用注入示例编译候选"
    )

    return CandidatePrompt(
        stage=stage,
        prompt_dir=prompt_dir,
        version=next_version,
        prompt_text=prompt_text,
        exemplars=exemplars,
        base_version=base_version,
        train_used=len(exemplars),
        selection_note=note,
    )


def write_candidate_prompt(
    stage: str,
    *,
    k: int = 3,
    golden_root: Optional[Path] = None,
    prompts_root: Optional[Path] = None,
    base_prompt: Optional[str] = None,
    exemplars: Optional[List[Dict[str, Any]]] = None,
) -> CandidatePrompt:
    """编译并落盘候选 prompt 到 ``prompts/<dir>/v{N+1}.j2``（不晋升）。"""
    cp = compile_candidate_prompt(
        stage,
        k=k,
        golden_root=golden_root,
        prompts_root=prompts_root,
        base_prompt=base_prompt,
        exemplars=exemplars,
    )
    root = prompts_root or DEFAULT_PROMPTS_DIR
    target = root / cp.prompt_dir / f"v{cp.version}.j2"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(cp.prompt_text, encoding="utf-8")
    logger.info(f"[M3] 候选 prompt 落盘 {target} (base=v{cp.base_version}, 示例={len(cp.exemplars)})")
    return cp


def _default_skeleton(stage: str) -> str:
    return (
        f"你是一个音频书生成流水线的「{stage}」阶段助手。\n"
        "请根据输入产出符合 schema 的结构化结果。\n"
        "严格只输出 JSON，不要任何解释性文字。"
    )
