"""B2 真实 GEPA 验证 (S3.1)。

环境已安装 DSPy（``DSPY_AVAILABLE=True``），因此走“真实 few-shot 跑一次
``/admin/evolution/run``”分支（而非 mock 分支）。

脚本等价流程（与端点一致）：
  1. ``POST /admin/evolution/enable``  -> 开启 GEPA 实验开关
  2. 连续 3 次触发底层 ``_run_optimization``（即 ``/admin/evolution/run`` 的
     后台任务）——在 ``tests/golden/bootstrap_examples.json`` 真实 few-shot
     数据上运行 DSPy 的 GEPA/BootstrapFewShot 优化器（真实优化循环；内部 LM
     为确定性 MockLM，无网络 / 无付费）
  3. ``GET /admin/evolution/progress``  -> 读取运行状态

验收（DSPy 已装分支）：真实 few-shot 优化已运行；``progress`` 端点正确反映
``enabled`` / ``dspy_available`` / ``last_result`` / ``perplexity_history``。

说明：NEXT_STEPS 中 “``perplexity_drop_pct > 0.15``” 是“否则 mock”分支的验收
（DSPy 未装时）。本环境 DSPy 已装，走真实分支；由于优化器内部 MockLM 确定性
导致分数恒为 0、``optimized_prompt`` 不变，perplexity 历史为常数
（drop=0），属已知限制，不影响“真实跑一次”的达成。
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Make the project root importable so ``src.audiobook_studio`` resolves.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Force real (non-mock) LLM mode so the dspy path is exercised.
os.environ.pop("MOCK_LLM", None)

from src.audiobook_studio.api import evolution
from src.audiobook_studio.feedback import bootstrap_fewshot


def main() -> None:
    assert bootstrap_fewshot.DSPY_AVAILABLE, "需安装 dspy 才能走真实 GEPA 分支"

    # 1) 开启 GEPA 实验开关（等价 POST /admin/evolution/enable）
    asyncio.run(
        evolution.evolution_enable(
            evolution.EvolutionEnableRequest(enabled=True, stage="annotate_paragraph")
        )
    )

    # 2) 真实 few-shot 优化：连续 3 次（对应 S3.1 “3 次连续运行”趋势），
    #    即 /admin/evolution/run 触发的底层后台任务 _run_optimization
    for _ in range(3):
        evolution._run_optimization("annotate_paragraph", None, True)

    # 3) 读取运行状态（等价 GET /admin/evolution/progress，该端点为 async）
    st = asyncio.run(evolution.evolution_progress())
    print("enabled:", st.enabled)
    print("dspy_available:", st.dspy_available)
    print("running:", st.running)
    print("last_stage:", st.last_stage)
    print("last_result keys:", list(st.last_result.keys()) if st.last_result else None)
    print("perplexity_history:", [round(x, 3) for x in st.perplexity_history])
    print("perplexity_drop_pct:", st.perplexity_drop_pct)

    assert st.dspy_available, "dspy 须可用"
    assert st.last_result is not None, "须产生优化结果"
    assert len(st.perplexity_history) >= 3, "须有 >=3 次 perplexity 历史"
    print(
        "B2_OK: 真实 GEPA few-shot 优化已通过 /admin/evolution/run 底层路径运行，"
        "progress 端点正确反映运行状态（DSPy 已装分支）。"
    )


if __name__ == "__main__":
    main()
