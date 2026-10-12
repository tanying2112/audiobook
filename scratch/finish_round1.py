"""补完验证轮 1：Gate1 修复（空白规范化）后重跑 4 门 → 晋升 → 部署 live v1.j2 → A/B。

复刻 integration._handle_new_analysis 的晋升/部署/A-B 段，版本语义相同：
候选 = 当前最大版本 v43；基线 = live（deployed.txt served，未部署则 v1）。
"""
import json
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")
os.environ.setdefault("SELF_ITERATION_MOCK", "false")
os.environ.setdefault("FCC_LOCAL_API_KEY", "freecc")
os.environ.setdefault("DATABASE_URL", "sqlite:///./src/data/audiobook.db")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
for noisy in ("httpx", "LiteLLM", "urllib3"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

STAGE = "edit_for_tts"

from audiobook_studio.feedback.integration import SelfIterationLoop, _live_baseline_version
from audiobook_studio.feedback.prompt_upgrader import _load_current_prompt
from audiobook_studio.feedback.promotion_gate import evaluate_promotion
from audiobook_studio.feedback.deploy import promote_candidate
from audiobook_studio.harness.spotcheck import human_preference_score_for

_, new_version = _load_current_prompt(STAGE)
old_version = _live_baseline_version(STAGE)
print(f"[versions] candidate v{new_version} vs live v{old_version}")
t0 = time.time()

result = evaluate_promotion(
    stage=STAGE,
    old_version=old_version,
    new_version=new_version,
    human_samples=SelfIterationLoop._human_samples_for_gate(STAGE),
)
print(f"[gates] {result.summary}")
for g in result.gates:
    print(f"    {'✅' if g.passed else '❌'} {g.name}: {g.score:.3f} ≥ {g.threshold} | {g.details[:120]}")

if not result.passed:
    print("!! 未过门，退出")
    sys.exit(1)

gate_scores = {g.name: g.score for g in result.gates}
decision = promote_candidate(
    stage=STAGE,
    candidate_version=new_version,
    golden_dataset_pass_rate=gate_scores.get("黄金数据集通过率", 0.0),
    quality_score_ratio=gate_scores.get("质量 ≥ 旧版 102%", 0.0),
    format_compliance_rate=gate_scores.get("格式合规率", 0.0),
    human_preference_score=human_preference_score_for(STAGE, default=1.0),
    prompts_dir=Path("prompts"),
    auto_deploy=True,
)
print(f"[deploy] passed={decision.passed} deployed={decision.deployed} failed={decision.failed_criteria}")
print(f"[deploy] deployed.txt: {(Path('prompts')/STAGE/'deployed.txt').read_text().strip() if (Path('prompts')/STAGE/'deployed.txt').exists() else '<absent>'}")

loop = SelfIterationLoop.__new__(SelfIterationLoop)  # 仅复用 A/B 方法（无状态依赖）
print(f"[A/B] {STAGE}: v{old_version} vs v{new_version}")
ab = loop._run_ab_test_for_stage(STAGE, old_version, new_version)
print(
    f"[A/B] samples={ab.num_samples} A={ab.avg_score_a:.3f} B={ab.avg_score_b:.3f} "
    f"improvement={ab.improvement_pct:+.1f}% significant={ab.is_significant} "
    f"a_wins={ab.a_wins} b_wins={ab.b_wins} ties={ab.ties}"
)
print(f"[A/B] recommendation: {ab.recommendation}")
print(f"\n总耗时 {time.time()-t0:.0f}s")
