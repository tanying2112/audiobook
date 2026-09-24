"""B1 真实闭环验证 (S3.7) —— 确定性 mock 模式（本机无本地 LLM）。

B1 验收（docs/NEXT_STEPS.md）：
  若本机有本地 LLM (Kokoro / qwen)，跑 ``scripts/validate_self_iteration.py``
  真实闭环并产出 ≥10% 收益报告 + 人工复核提示；
  否则保留确定性 mock 并明确标注。

本环境检测：``is_kokoro_available()==False``（无权重）且无 qwen GGUF →
走“确定性 mock”分支。本脚本：
  * 明确打印 MODE 标签（MOCK/DETERMINISTIC，因无本地 LLM）；
  * 调用 canonical ``validate_self_iteration.py``（确定性角色感知合成，
    无网络 / 无付费）验证 S3.7 自迭代闭环；
  * 使用临时 config 副本，避免修改被跟踪的 ``config/agent_sop.json``；
  * 断言闭环产生 ≥10% 收益 + 需要人工复核（确定性测量的真实结果）。

若日后本机装上 Kokoro 权重或 qwen GGUF，本脚本会自动切换到
REAL (local LLM) 模式（仍复用同一 canonical 脚本）。
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
from shutil import copy as shutil_copy

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.audiobook_studio.tts.clone import is_kokoro_available  # noqa: E402

# ── 本地 LLM 检测（决定 REAL vs MOCK 分支）─────────────────────────────────
kokoro = is_kokoro_available()
qwen = Path(ROOT / "models" / "qwen.gguf").exists()
local_llm = kokoro or qwen

if local_llm:
    MODE = "REAL (local LLM: Kokoro/qwen available)"
else:
    MODE = "MOCK/DETERMINISTIC (no local LLM: Kokoro weights absent, no qwen GGUF)"


def main() -> int:
    print("=" * 64)
    print(f"B1 MODE: {MODE}")
    print(f"  Kokoro available : {kokoro}")
    print(f"  qwen GGUF present: {qwen}")
    print("=" * 64)
    if not local_llm:
        print("⚠️  本环境无本地 LLM，按验收走“确定性 mock”分支：")
        print("    运行确定性自迭代闭环（角色感知合成，无网络/无付费），")
        print("    并明确标注为 MOCK（非本地 LLM 驱动的真实闭环）。")
        print("-" * 64)

    # 用临时 config 副本，避免修改被跟踪的 config/agent_sop.json
    with tempfile.TemporaryDirectory() as td:
        tmp_cfg = Path(td) / "agent_sop.json"
        shutil_copy(ROOT / "config" / "agent_sop.json", tmp_cfg)
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "validate_self_iteration.py"),
             "--config", str(tmp_cfg)],
            capture_output=True, text=True,
        )
        # 原样回显 canonical 脚本输出
        sys.stdout.write(proc.stdout)
        if proc.returncode != 0:
            sys.stderr.write(proc.stderr)
            return proc.returncode

    # 从输出中解析关键指标，做确定性断言
    out = proc.stdout
    import re

    gain = re.search(r"gain_pct:\s*([\d.]+)", out)
    human = "requires_human_review: True" in out
    sop_updated = "sop_updated: True" in out
    gain_val = float(gain.group(1)) if gain else 0.0

    print("-" * 64)
    print(f"[B1] gain_pct={gain_val:.1f}%  sop_updated={sop_updated}  "
          f"requires_human_review={human}")
    assert sop_updated, "自迭代闭环须更新 SOP"
    assert gain_val > 10.0, f"确定性闭环收益须 >10%（实测 {gain_val:.1f}%）"
    assert human, "须提示需要人工复核"
    print("B1_OK: 确定性自迭代闭环验证通过（gain>10% + 人工复核提示），"
          "已明确标注为 MOCK/DETERMINISTIC（本机无本地 LLM）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
