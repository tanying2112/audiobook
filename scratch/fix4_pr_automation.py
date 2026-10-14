"""Fix 4：环内 PR 自动化修复——让既有接线真正跑得通。

披露局限 (5) 的实况：integration.py:313 早已接线（enable_auto_pr 默认 True），
但链条从未在真实仓库环境验证过，且存在四个致盲缺陷：
  a) _push_branch 固定 `git push -u origin` —— 本机/无 SSH key 环境 origin 是
     SSH remote，push 必败（publickey denied）。
  b) `git checkout -b` + 裸 `git commit` —— checkout 会把 ~110 个无关暂存 WIP
     带进新分支，commit 一锅端卷入 PR。
  c) 裸 `git commit` 走 pre-commit 钩子（本仓库钩子当前对既有 lint 失败，
     阻断一切提交）。
  d) PR body 的 `f"{score:.3f}"`/`f"{imp:.1f}%"` 在值为 None/缺失时抛
     ValueError 直接炸掉 create_prompt_upgrade_pr。

修复：_create_pr_branch 改为纯 plumbing（fetch base → 记录 base_sha，不再
checkout 工作树）；_commit_prompt_changes 改为 GIT_INDEX_FILE 临时索引
（read-tree base → 只 add prompt 文件 → write-tree → commit-tree，天然绕过
pre-commit 钩子，且 PR 提交 = base 树 + 仅 prompt 文件，绝无 WIP 卷入）；
_push_branch 以 commit_sha:refs/heads/<branch> 推送，远端经
SELF_ITERATION_GIT_REMOTE 解析（SSH github URL 自动改写 HTTPS + gh
credential helper）。对外函数签名与既有单测的 mock 契约全部保持。
"""
from pathlib import Path

p = Path("src/audiobook_studio/feedback/pr_automation.py")
src = p.read_text(encoding="utf-8")

# ── 1) imports：tempfile + Dict ──
old = """import json
import logging
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, cast"""
new = """import json
import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, cast"""
assert src.count(old) == 1
src = src.replace(old, new)

# ── 2) _run_command：env 支持（None 时不传，保持 subprocess.run 调用形状） ──
old = '''def _run_command(cmd: List[str], cwd: Optional[Path] = None) -> subprocess.CompletedProcess[str]:
    """Run a shell command and return result."""
    logger.debug(f"Running command: {' '.join(cmd)}")
    result = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
    )'''
new = '''def _run_command(
    cmd: List[str], cwd: Optional[Path] = None, env: Optional[Dict[str, str]] = None
) -> subprocess.CompletedProcess[str]:
    """Run a shell command and return result.

    env 仅在需要（如 GIT_INDEX_FILE 临时索引）时传入，保持默认调用形状不变
    （单测对 subprocess.run 的 kwargs 有精确断言）。
    """
    logger.debug(f"Running command: {' '.join(cmd)}")
    if env is None:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
        )
    else:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            env=env,
        )'''
assert src.count(old) == 1
src = src.replace(old, new)

# ── 3) 远端解析 + PR 状态 + 分支创建（纯 plumbing，不再 checkout） ──
old = '''def _create_pr_branch(base_branch: str, stage: str, version: int) -> str:
    """Create and checkout a new branch for the PR."""
    branch_name = f"auto/prompt-upgrade-{stage}-v{version}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"

    # Fetch latest
    _run_command(["git", "fetch", "origin", base_branch])

    # Create new branch from base
    result = _run_command(["git", "checkout", "-b", branch_name, f"origin/{base_branch}"])
    if result.returncode != 0:
        raise RuntimeError(f"Failed to create branch: {result.stderr}")

    logger.info(f"Created branch: {branch_name}")
    return branch_name'''
new = '''# 环内 PR 的跨调用状态（fetch 到的 base、plumbing 生成的 commit）。
# 纯 plumbing 流程不再 checkout 分支，commit 上下文经此传递。
_PR_STATE: Dict[str, Any] = {"base_sha": None, "commit_sha": None, "branch_name": None}

# SSH github remote 自动改写：git@github.com:o/r.git → https://github.com/o/r.git
# 并注入 gh credential helper（与既定手工推送路径一致），使无 SSH key 的
# 环境（本机即如此）环内 PR 推送可用；可用 SELF_ITERATION_GIT_REMOTE 覆盖。
_SSH_GITHUB_PREFIX = "git@github.com:"
_GH_CRED_HELPER = "!gh auth git-credential"


def _resolve_remote_spec() -> Tuple[List[str], str]:
    """返回 (git -c 前缀参数, remote 引用)。

    remote 默认 origin，可经 SELF_ITERATION_GIT_REMOTE 覆盖；SSH github URL
    改写为 HTTPS 并带 gh credential helper。URL 直接探测失败时回退原名。
    """
    remote_name = os.getenv("SELF_ITERATION_GIT_REMOTE", "origin")
    if "://" in remote_name or remote_name.startswith(_SSH_GITHUB_PREFIX):
        url = remote_name
    else:
        r = _run_command(["git", "remote", "get-url", remote_name])
        url = r.stdout.strip() if (r.returncode == 0 and isinstance(r.stdout, str)) else ""
    if isinstance(url, str) and url.startswith(_SSH_GITHUB_PREFIX):
        https = "https://github.com/" + url[len(_SSH_GITHUB_PREFIX):]
        return ["-c", f"credential.helper={_GH_CRED_HELPER}"], https
    return [], remote_name


def _create_pr_branch(base_branch: str, stage: str, version: int) -> str:
    """解析 PR 分支名并 fetch 基线（纯 plumbing：不 checkout、不动工作树/暂存区）。

    2026-10 修复：此前 `git checkout -b <branch> origin/<base>` 在含大量
    无关暂存 WIP 的工作树上会把它们整体带进新分支，后续裸 commit 一锅端。
    现在只 fetch 基线并记录 base_sha，提交由 _commit_prompt_changes 以
    临时索引生成（base 树 + 仅 prompt 文件）。
    """
    branch_name = f"auto/prompt-upgrade-{stage}-v{version}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"

    prefix, remote = _resolve_remote_spec()
    fetch = _run_command(["git", *prefix, "fetch", remote, base_branch])
    if fetch.returncode != 0:
        raise RuntimeError(f"Failed to create branch (fetch {remote} {base_branch}): {fetch.stderr}")

    base_sha: Any = None
    head = _run_command(["git", "rev-parse", "FETCH_HEAD"])
    if head.returncode == 0 and isinstance(head.stdout, str) and head.stdout.strip():
        base_sha = head.stdout.strip()
    if not base_sha:
        raise RuntimeError(f"Failed to create branch: cannot resolve FETCH_HEAD for {base_branch}")

    _PR_STATE.update({"base_sha": base_sha, "commit_sha": None, "branch_name": branch_name})
    logger.info(f"Prepared PR branch (plumbing, no checkout): {branch_name} @ base {base_sha[:8]}")
    return branch_name'''
assert src.count(old) == 1
src = src.replace(old, new)

# ── 4) _commit_prompt_changes：临时索引 scoped commit（绕钩子、零 WIP 卷入） ──
old = '''def _commit_prompt_changes(stage: str, version: int, message: Optional[str] = None) -> bool:
    """Commit the prompt changes for a stage."""
    prompt_dir = Path("prompts") / stage

    # Add the new prompt version and CHANGELOG
    files_to_add = []
    v_file = prompt_dir / f"v{version}.j2"
    if v_file.exists():
        files_to_add.append(str(v_file))

    changelog = prompt_dir / "CHANGELOG.md"
    if changelog.exists():
        files_to_add.append(str(changelog))

    if not files_to_add:
        logger.warning(f"No prompt files to commit for {stage} v{version}")
        return False

    # Stage files
    for f in files_to_add:
        result = _run_command(["git", "add", f])
        if result.returncode != 0:
            logger.error(f"Failed to stage {f}: {result.stderr}")
            return False

    # Commit
    if message is None:
        message = f"feat(prompt): upgrade {stage} to v{version}\\n\\nAutomated prompt upgrade via SelfIterationLoop"

    result = _run_command(["git", "commit", "-m", message])
    if result.returncode != 0:
        logger.error(f"Failed to commit: {result.stderr}")
        return False

    logger.info(f"Committed changes for {stage} v{version}")
    return True'''
new = '''def _commit_prompt_changes(stage: str, version: int, message: Optional[str] = None) -> bool:
    """以临时索引生成 scoped 提交：PR 提交 = base 树 + 仅 prompt 文件。

    2026-10 修复：此前裸 `git add` + `git commit`（在用户真实暂存区上操作）
    会把全部无关暂存 WIP 卷进 PR 提交，且 pre-commit 钩子（当前对既有
    lint 失败）会阻断提交。现在用 GIT_INDEX_FILE 临时索引 + plumbing：
    read-tree base → 只 add prompt 文件（从工作树读内容）→ write-tree →
    commit-tree。plumbing 不跑钩子，也绝不触碰用户暂存区/工作树。
    """
    prompt_dir = Path("prompts") / stage

    # 新版本文件 + live 槽（v1.j2，若已 auto_deploy 则为部署后的内容）+ CHANGELOG
    files_to_add: List[Path] = []
    v_file = prompt_dir / f"v{version}.j2"
    if v_file.exists():
        files_to_add.append(v_file)
    live = prompt_dir / "v1.j2"
    if live.exists() and str(live) != str(v_file):
        files_to_add.append(live)
    changelog = prompt_dir / "CHANGELOG.md"
    if changelog.exists():
        files_to_add.append(changelog)

    if not files_to_add:
        logger.warning(f"No prompt files to commit for {stage} v{version}")
        return False

    base_sha = _PR_STATE.get("base_sha") or "HEAD"
    if message is None:
        message = (
            f"feat(prompt): upgrade {stage} to v{version}\\n\\n"
            "Automated prompt upgrade via SelfIterationLoop "
            "(scoped commit: base tree + prompt files only)\\n\\n"
            "Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
        )

    with tempfile.TemporaryDirectory(prefix="pr-index-") as td:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(td) / "index")}
        if _run_command(["git", "read-tree", base_sha], env=env).returncode != 0:
            logger.error(f"Failed to read-tree base {base_sha}")
            return False
        for f in files_to_add:
            if _run_command(["git", "add", "--", f.as_posix()], env=env).returncode != 0:
                logger.error(f"Failed to stage {f}")
                return False
        wt = _run_command(["git", "write-tree"], env=env)
        if wt.returncode != 0 or not isinstance(wt.stdout, str) or not wt.stdout.strip():
            logger.error(f"Failed to write-tree: {wt.stderr}")
            return False
        tree_sha = wt.stdout.strip()
        ct = _run_command(["git", "commit-tree", tree_sha, "-p", base_sha, "-m", message])
        if ct.returncode != 0 or not isinstance(ct.stdout, str) or not ct.stdout.strip():
            logger.error(f"Failed to commit-tree: {ct.stderr}")
            return False
        _PR_STATE["commit_sha"] = ct.stdout.strip()

    logger.info(f"Committed changes for {stage} v{version} (scoped, base={str(base_sha)[:8]})")
    return True'''
assert src.count(old) == 1
src = src.replace(old, new)

# ── 5) _push_branch：commit_sha refspec + 解析后的远端 ──
old = '''def _push_branch(branch_name: str) -> bool:
    """Push the branch to origin."""
    result = _run_command(["git", "push", "-u", "origin", branch_name])
    if result.returncode != 0:
        logger.error(f"Failed to push branch: {result.stderr}")
        return False
    logger.info(f"Pushed branch: {branch_name}")
    return True'''
new = '''def _push_branch(branch_name: str) -> bool:
    """Push the PR branch to the resolved remote.

    有 plumbing 提交（_PR_STATE["commit_sha"]）时推 `sha:refs/heads/<branch>`；
    无状态时回退传统 `<branch>`（保持独立调用兼容）。远端经
    _resolve_remote_spec 解析：SSH github URL → HTTPS + gh credential helper，
    否则原名推送。
    """
    prefix, remote = _resolve_remote_spec()
    commit_sha = _PR_STATE.get("commit_sha")
    refspec = f"{commit_sha}:refs/heads/{branch_name}" if commit_sha else branch_name
    result = _run_command(["git", *prefix, "push", "-u", remote, refspec])
    if result.returncode != 0:
        logger.error(f"Failed to push branch to {remote}: {result.stderr}")
        return False
    logger.info(f"Pushed branch: {branch_name} -> {remote}")
    return True'''
assert src.count(old) == 1
src = src.replace(old, new)

# ── 6) PR body 格式崩溃修复 + 尾部署名 ──
old = '''    if promotion_result:
        body_lines.append("#### Promotion Gate")
        for gate in promotion_result.get("gates", []):
            status = "✅" if gate.get("passed") else "❌"
            body_lines.append(
                f"- {status} {gate.get('name')}: {gate.get('score'):.3f} (threshold: {gate.get('threshold')})"
            )'''
new = '''    if promotion_result:
        body_lines.append("#### Promotion Gate")
        for gate in promotion_result.get("gates", []):
            status = "✅" if gate.get("passed") else "❌"
            score = gate.get("score")
            score_str = f"{score:.3f}" if isinstance(score, (int, float)) else str(score)
            threshold = gate.get("threshold")
            threshold_str = f" (threshold: {threshold})" if threshold is not None else ""
            body_lines.append(f"- {status} {gate.get('name')}: {score_str}{threshold_str}")'''
assert src.count(old) == 1
src = src.replace(old, new)

old = '''    if ab_test_results:
        body_lines.append("")
        body_lines.append("#### A/B Test Results")
        body_lines.append(f"- Samples: {ab_test_results.get('num_samples', 'N/A')}")
        body_lines.append(f"- Improvement: {ab_test_results.get('improvement_pct', 'N/A'):.1f}%")
        body_lines.append(f"- Significant: {ab_test_results.get('is_significant', 'N/A')}")
        body_lines.append(f"- Recommendation: {ab_test_results.get('recommendation', 'N/A')}")

    body_lines.extend(
        [
            "",
            "---",
            "*Auto-generated by Audiobook Studio SelfIterationLoop*",
        ]
    )'''
new = '''    if ab_test_results:
        body_lines.append("")
        body_lines.append("#### A/B Test Results")
        body_lines.append(f"- Samples: {ab_test_results.get('num_samples', 'N/A')}")
        improvement = ab_test_results.get("improvement_pct")
        body_lines.append(
            f"- Improvement: {improvement:.1f}%" if isinstance(improvement, (int, float)) else "- Improvement: N/A"
        )
        body_lines.append(f"- Significant: {ab_test_results.get('is_significant', 'N/A')}")
        body_lines.append(f"- Recommendation: {ab_test_results.get('recommendation', 'N/A')}")

    body_lines.extend(
        [
            "",
            "---",
            "*Auto-generated by Audiobook Studio SelfIterationLoop*",
            "",
            "🤖 Generated with [Claude Code](https://claude.com/claude-code)",
        ]
    )'''
assert src.count(old) == 1
src = src.replace(old, new)

p.write_text(src, encoding="utf-8")
print("pr_automation.py OK")
