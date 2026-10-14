"""Fix 4 配套：环内 PR 自动化的运维环境变量开关。

接入点在 SelfIterationLoop.__init__——PR 机制修复（plumbing scoped commit +
HTTPS/gh credential push）后，auto_pr 真正具备生产能力，需要不改代码即可
关停/改基线的运维开关：
  SELF_ITERATION_AUTO_PR     未设置→构造参数默认；设置→显式开/关
  SELF_ITERATION_AUTO_MERGE  同上
  SELF_ITERATION_PR_BASE     未设置→构造参数默认；设置→覆盖 PR 基线分支
"""
from pathlib import Path

p = Path("src/audiobook_studio/feedback/integration.py")
src = p.read_text(encoding="utf-8")

# ── 1) import os ──
old = """import json
import logging
import threading
from datetime import datetime, timezone"""
new = """import json
import logging
import os
import threading
from datetime import datetime, timezone"""
assert src.count(old) == 1
src = src.replace(old, new)

# ── 2) _env_flag 辅助函数（模块级，_log_self_iteration_event 之前） ──
old = '''logger = logging.getLogger(__name__)


def _log_self_iteration_event(event_type: str, data: Dict[str, Any]) -> None:'''
new = '''logger = logging.getLogger(__name__)


def _env_flag(name: str, default: bool) -> bool:
    """环境变量布尔开关：未设置时沿用传入默认值，显式设置时覆盖。"""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("false", "0", "no", "off")


def _log_self_iteration_event(event_type: str, data: Dict[str, Any]) -> None:'''
assert src.count(old) == 1
src = src.replace(old, new)

# ── 3) __init__：环境变量覆盖 ──
old = """        self.canary_percentage = canary_percentage
        self.enable_auto_pr = enable_auto_pr
        self.enable_auto_merge = enable_auto_merge
        self.auto_deploy = auto_deploy
        self.pr_base_branch = pr_base_branch
        self.ci_timeout_seconds = ci_timeout_seconds"""
new = """        self.canary_percentage = canary_percentage
        # 环内 PR 运维开关（2026-10 修复后 PR 机制真实可用，故提供不改代码的
        # 关停/改基线手段）：SELF_ITERATION_AUTO_PR / SELF_ITERATION_AUTO_MERGE
        # / SELF_ITERATION_PR_BASE，未设置时沿用构造参数默认。
        self.enable_auto_pr = _env_flag("SELF_ITERATION_AUTO_PR", enable_auto_pr)
        self.enable_auto_merge = _env_flag("SELF_ITERATION_AUTO_MERGE", enable_auto_merge)
        self.auto_deploy = auto_deploy
        self.pr_base_branch = os.getenv("SELF_ITERATION_PR_BASE") or pr_base_branch
        self.ci_timeout_seconds = ci_timeout_seconds"""
assert src.count(old) == 1
src = src.replace(old, new)

p.write_text(src, encoding="utf-8")
print("integration.py env flags OK")
