#!/usr/bin/env python3
"""P0.3.7 — 元门禁 CI 校验脚本（护住 reward-hacking 的尺度文件）。

执行手册 docs/EVOLUTION_ROADMAP.md P0.3 子任务 7：
  - 裁判 prompt / 评估集 / 指标定义文件对进化循环**只读**；
  - CI 校验这些文件本 Sprint 未被自动改动（被自动改动需人工复核，不得由进化循环放行）。

本脚本在 CI 中运行（也支持本地 `PYTHONPATH=src python scripts/verify_p03_meta_guard.py`），
对当前改动列表（相对 base 的 changed/added 文件）调用 promotion_gate.verify_meta_guard：

  退出码:
    0  clean —— 改动未触碰任何只读尺度文件（进化循环可正常通过门禁）
    3  touched —— 改动触及只读尺度文件，需人工复核（CI 不阻止，但标记需review，由调用方决定是否 fail）
    1  error —— 脚本自身出错

注意（红线 #3 SSOT）：本脚本只读、不写任何 docs。被触及的尺度文件的处置由人工/上层
CI policy 决定，而非本脚本自动 fail——避免误判"人工提交的正当宪法修订"为 reward hacking。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# 内置只读尺度清单（与 promotion_gate.META_GUARD_READONLY_PATHS 同源，避免跨模块漂移）
try:
    from audiobook_studio.feedback.promotion_gate import (  # noqa: E402
        META_GUARD_READONLY_PATHS,
        verify_meta_guard,
    )
except Exception as e:  # noqa: BLE001
    print(f"error: failed to import promotion_guard meta-guard: {e}")
    raise SystemExit(1)


def _changed_files() -> list[str]:
    """获取相对 base 的改动/新增文件列表。CI 优先 $BASE_SHA… 否则退回 working tree（本地）。"""
    base = os.environ.get("P03_META_BASE_SHA")
    if base:
        # GitHub Actions PR：base...HEAD
        try:
            out = subprocess.run(
                ["git", "diff", "--name-only", f"{base}...HEAD"],
                capture_output=True, text=True, check=True,
            )
            return [l for l in out.stdout.splitlines() if l.strip()]
        except Exception:  # noqa: BLE001
            pass
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            capture_output=True, text=True, check=True,
        )
        files: list[str] = []
        for line in out.stdout.splitlines():
            line = line.rstrip()
            if not line:
                continue
            # porcelain 形如 " M path" / "?? path" / "A  path"
            path = line[3:].strip()
            if path:
                files.append(path)
        return files
    except Exception as e:  # noqa: BLE001
        print(f"error: git status failed: {e}")
        raise SystemExit(1)


def main() -> int:
    changed = _changed_files()
    result = verify_meta_guard(changed)
    print(f"meta-guard: changed={len(changed)} touched={len(result['touched'])} clean={result['clean']}")
    if result["touched"]:
        print("⚠️  只读尺度文件被改动（需人工复核，进化循环不得自动放行）:")
        for f in result["touched"]:
            print(f"    - {f}")
        return 3
    print("✅ meta-guard clean: 尺度文件未被本次改动触碰")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
