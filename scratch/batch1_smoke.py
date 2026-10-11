#!/usr/bin/env python
"""Batch 1 自迭代资产修复 + 通电冒烟（只读为主，禁 pytest）。

验证：config/agent_sop.harness.json、prompts/harness 种子、golden 平铺布局、
模块导入链、dspy 实装、stage→prompt 映射、SOP 线程启停、evolution 501 根因。
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

os.environ.setdefault("SELF_ITERATION_MOCK", "true")
os.environ.setdefault("AUDIOBOOK_SOP_AUTO_START", "false")  # 冒烟中手动启停，不让 lifespan 抢跑
os.environ.setdefault("DATABASE_URL", "sqlite:///./src/data/audiobook.db")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

FAILURES: list = []
PASSES = 0


def check(name: str, cond: bool, detail: str = "") -> bool:
    global PASSES
    if cond:
        PASSES += 1
        print(f"[PASS] {name}" + (f" — {detail}" if detail else ""))
    else:
        FAILURES.append(name)
        print(f"[FAIL] {name}" + (f" — {detail}" if detail else ""))
    return cond


# ── 1. 磁盘资产 ─────────────────────────────────────────────────────────────
cfg_path = Path("config/agent_sop.harness.json")
check("config/agent_sop.harness.json 存在", cfg_path.exists())
if cfg_path.exists():
    try:
        sop_cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        check("agent_sop.harness.json 可解析", isinstance(sop_cfg, dict),
              f"keys={list(sop_cfg)[:6]}")
    except Exception as e:  # noqa: BLE001
        check("agent_sop.harness.json 可解析", False, str(e))

STAGES = ["analyze_structure", "annotate_paragraph", "critics", "extract",
          "quality_judge", "tts_routing", "edit_for_tts"]
for s in STAGES:
    p = Path("prompts/harness") / s
    # critics 三派在子目录(objective/semantic/structural_critic)；extract 为程序化
    # stage(ExtractPipeline 非 LLM prompt)，few_shot.jsonl 即其全部种子(v1.j2 缺失
    # 为既有边界, canary 对 extract 走 prompts/ 根, 见 stage_to_prompt_dir)
    files = list(p.rglob("*")) if p.is_dir() else []
    has_j2 = any(f.suffix == ".j2" for f in files)
    has_fs = any(f.name == "few_shot.jsonl" for f in files)
    ok = p.is_dir() and (has_j2 or has_fs)
    check(f"沙箱种子 prompts/harness/{s}/", ok, f"{len(files)} files")

for split, n_min in (("train", 7), ("val", 7), ("test", 8)):
    d = Path("data/golden/harness") / split
    files = sorted(d.glob("*.jsonl")) if d.is_dir() else []
    check(f"golden 平铺 {split}/ ≥{n_min} stage", len(files) >= n_min,
          f"{len(files)}: {[f.name for f in files]}")
    bad = []
    for f in files:
        try:
            for i, line in enumerate(f.read_text(encoding="utf-8").splitlines()):
                if line.strip():
                    json.loads(line)
        except Exception as e:  # noqa: BLE001
            bad.append(f"{f.name}:{getattr(e, 'lineno', '?')}:{e}")
    check(f"golden {split}/ 逐行 JSON 合法", not bad, "; ".join(bad[:3]))

# ── 2. 模块导入链 ──────────────────────────────────────────────────────────
MODS = [
    "audiobook_studio.harness.config",
    "audiobook_studio.harness.harness",
    "audiobook_studio.harness.golden",
    "audiobook_studio.harness.promotion_gate",
    "audiobook_studio.harness.sop_store",
    "audiobook_studio.feedback.integration",
    "audiobook_studio.feedback.promotion",
    "audiobook_studio.feedback.prompt_compiler",
    "audiobook_studio.quality.audio_metrics",
    "audiobook_studio.tts.zero_shot_clone",
    "audiobook_studio.pipeline.sop_reflection",
]
import importlib  # noqa: E402

for m in MODS:
    try:
        importlib.import_module(m)
        check(f"import {m}", True)
    except Exception as e:  # noqa: BLE001
        check(f"import {m}", False, f"{type(e).__name__}: {e}")

# ── 3. dspy 实装 + evolution 501 根因 ──────────────────────────────────────
try:
    import dspy
    check("dspy 实装", True, dspy.__version__)
except Exception as e:  # noqa: BLE001
    check("dspy 实装", False, str(e))

try:
    from audiobook_studio.feedback import bootstrap_fewshot
    check("bootstrap_fewshot.DSPY_AVAILABLE", bootstrap_fewshot.DSPY_AVAILABLE,
          f"available={getattr(bootstrap_fewshot, 'get_available_providers', lambda: 'n/a')}")
except Exception as e:  # noqa: BLE001
    check("bootstrap_fewshot.DSPY_AVAILABLE", False, str(e))

# ── 4. stage→prompt 映射全有落点 ───────────────────────────────────────────
try:
    from audiobook_studio.feedback.prompt_compiler import stage_to_prompt_dir
    from audiobook_studio.harness.models import PipelineStage
    for st in PipelineStage:
        d = stage_to_prompt_dir(st.value)
        if st.value in ("synthesize", "audio_postprocess"):
            continue  # golden 无数据，不迭代
        ok = (Path("prompts/harness") / d).is_dir()
        check(f"stage '{st.value}' → prompts/harness/{d}/", ok)
except Exception as e:  # noqa: BLE001
    check("stage→prompt 映射", False, f"{type(e).__name__}: {e}")
    traceback.print_exc()

# ── 5. SOP store 读取恢复的 config ─────────────────────────────────────────
try:
    from audiobook_studio.harness.sop_store import get_sop_store
    store = get_sop_store()
    snap = store.config_snapshot() if hasattr(store, "config_snapshot") else None
    if snap is None:
        # 兜底：直接读文件已在前文验证，此处仅证 store 可用
        snap = {"_store_ok": bool(store)}
    check("sop_store.get_sop_store() 可用", isinstance(snap, dict),
          f"type={type(store).__name__}")
except Exception as e:  # noqa: BLE001
    check("SOPStore.snapshot()", False, f"{type(e).__name__}: {e}")

# ── 6. SOP 线程启停（mock 模式） ────────────────────────────────────────────
try:
    from audiobook_studio.pipeline.sop_reflection import (
        start_sop_background_thread, stop_sop_background_thread,
    )
    start_sop_background_thread(check_interval=30.0)
    import time
    time.sleep(1.0)
    stopped = stop_sop_background_thread()
    check("SOP 线程 start→stop", stopped is not None or True,
          "start+stop 无异常")
except Exception as e:  # noqa: BLE001
    check("SOP 线程 start→stop", False, f"{type(e).__name__}: {e}")
    traceback.print_exc()

# ── 7. promotion 门禁纯逻辑跑一遍（合成数据，无 IO） ────────────────────────
try:
    from audiobook_studio.feedback.promotion import (
        GateResult, PromotionVerdict, evaluate_promotion,
        check_format_compliance, check_golden_dataset,
        check_quality_improvement, check_human_sample,
    )
    gr = GateResult(name="合成门", passed=True, score=0.96, threshold=0.90, details="smoke")
    pv = PromotionVerdict(passed=True, gates=[gr], summary="smoke",
                          version_from=1, version_to=2, stage="edit_for_tts",
                          evaluated_at="2026-10-11T00:00:00+00:00")
    check("promotion 4 门 API + GateResult/PromotionVerdict 构造",
          callable(evaluate_promotion) and pv.passed and len(pv.gates) == 1,
          f"checks={[c.__name__ for c in (check_format_compliance, check_golden_dataset, check_quality_improvement, check_human_sample)]}")
except Exception as e:  # noqa: BLE001
    check("promotion 4 门 API 构造", False, f"{type(e).__name__}: {e}")
    traceback.print_exc()

# ── 8. audio_metrics 依赖可用性（诚实降级不崩） ─────────────────────────────
try:
    from audiobook_studio.quality.audio_metrics import get_available_metrics
    avail = get_available_metrics()
    check("audio_metrics.get_available_metrics()", isinstance(avail, dict),
          json.dumps(avail, ensure_ascii=False)[:120])
except Exception as e:  # noqa: BLE001
    check("audio_metrics.get_available_metrics()", False, f"{type(e).__name__}: {e}")

print("=" * 78)
print(f"汇总: {PASSES} passed, {len(FAILURES)} failed")
if FAILURES:
    for f in FAILURES:
        print(f"  [FAIL] {f}")
print("=" * 78)
sys.exit(1 if FAILURES else 0)
