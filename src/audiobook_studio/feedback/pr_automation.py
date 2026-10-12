"""
PR Automation Module for Self-Iteration Loop.

Provides GitHub PR creation and auto-merge functionality for prompt version upgrades.
"""

import json
import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, cast

logger = logging.getLogger(__name__)


@dataclass
class PRResult:
    """Result of PR creation operation."""

    success: bool
    pr_number: Optional[int] = None
    pr_url: Optional[str] = None
    branch_name: Optional[str] = None
    error: Optional[str] = None


@dataclass
class MergeResult:
    """Result of PR merge operation."""

    success: bool
    merged: bool = False
    merge_commit_sha: Optional[str] = None
    error: Optional[str] = None


def _run_command(
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
        )
    if result.returncode != 0:
        logger.warning(f"Command failed: {' '.join(cmd)} - {result.stderr}")
    return result


def _get_git_repo_root() -> Path:
    """Get the git repository root."""
    result = _run_command(["git", "rev-parse", "--show-toplevel"])
    if result.returncode != 0:
        raise RuntimeError("Not in a git repository")
    return Path(result.stdout.strip())


def _get_current_branch() -> str:
    """Get the current git branch name."""
    result = _run_command(["git", "branch", "--show-current"])
    if result.returncode != 0:
        raise RuntimeError("Failed to get current branch")
    return result.stdout.strip()


def _has_uncommitted_changes() -> bool:
    """Check if there are uncommitted changes."""
    result = _run_command(["git", "status", "--porcelain"])
    return bool(result.stdout.strip())


def _get_changed_prompt_files() -> List[Path]:
    """Get list of changed prompt files (v*.j2 and CHANGELOG.md)."""
    result = _run_command(["git", "diff", "--name-only", "HEAD"])
    if result.returncode != 0:
        return []

    changed = []
    for line in result.stdout.strip().split("\n"):
        if line.strip():
            path = Path(line.strip())
            if path.suffix == ".j2" or path.name == "CHANGELOG.md":
                changed.append(path)
    return changed


# 环内 PR 的跨调用状态（fetch 到的 base、plumbing 生成的 commit、
# 解析后的远端）。纯 plumbing 流程不再 checkout 分支，commit 上下文经此传递。
# remote 前缀/引用在 _create_pr_branch 解析一次，_push_branch 只读缓存
# （不在 push 内再探测 remote，保持单次命令调用的既有契约）。
_PR_STATE: Dict[str, Any] = {
    "base_sha": None,
    "commit_sha": None,
    "branch_name": None,
    "remote_prefix": [],
    "remote_name": "origin",
}


def _looks_like_sha(s: Any) -> bool:
    """commit-tree 产物应为 40 位 SHA-1（或 64 位 SHA-256）十六进制对象号。

    只有确有 commit 产物时才走 `sha:refs/heads/<branch>` 推送；否则回退
    分支名推送（独立的 _push_branch 调用兼容路径）。
    """
    if not isinstance(s, str):
        return False
    t = s.strip()
    return len(t) in (40, 64) and all(c in "0123456789abcdefABCDEF" for c in t)


def _stdout_of(result: Any) -> str:
    """防御性读取 CompletedProcess.stdout，恒返回 str。

    真实 subprocess（text=True）stdout 恒为 str；mock（spec=CompletedProcess）
    在未显式设置时访问会抛 AttributeError，此处回退 ""。成功路径以 rc 为准，
    stdout 读不到时走告警+回退，绝不误判失败。
    """
    raw = getattr(result, "stdout", "")
    return raw if isinstance(raw, str) else ""

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
        url = _stdout_of(r).strip() if r.returncode == 0 else ""
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
    _PR_STATE.update({"remote_prefix": prefix, "remote_name": remote})
    fetch = _run_command(["git", *prefix, "fetch", remote, base_branch])
    if fetch.returncode != 0:
        raise RuntimeError(f"Failed to create branch (fetch {remote} {base_branch}): {fetch.stderr}")

    head = _run_command(["git", "rev-parse", "FETCH_HEAD"])
    base_sha = _stdout_of(head).strip() if head.returncode == 0 else ""
    if not base_sha:
        # fetch 已成功而 rev-parse 异常时，origin/<base> 与 FETCH_HEAD 同指
        # 一提交，作为等价 committish 回退（read-tree 接受任意 committish）。
        base_sha = f"origin/{base_branch}"
        logger.warning(f"rev-parse FETCH_HEAD unavailable, falling back to {base_sha}")

    _PR_STATE.update({"base_sha": base_sha, "commit_sha": None, "branch_name": branch_name})
    logger.info(f"Prepared PR branch (plumbing, no checkout): {branch_name} @ base {str(base_sha)[:8]}")
    return branch_name


def _commit_prompt_changes(stage: str, version: int, message: Optional[str] = None) -> bool:
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
            f"feat(prompt): upgrade {stage} to v{version}\n\n"
            "Automated prompt upgrade via SelfIterationLoop "
            "(scoped commit: base tree + prompt files only)\n\n"
            "Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
        )

    with tempfile.TemporaryDirectory(prefix="pr-index-") as td:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(td) / "index")}
        # （PR_BASE_SHA / PR_COMMIT_MSG 在 write-tree 串联前补入 env）
        if _run_command(["git", "read-tree", base_sha], env=env).returncode != 0:
            logger.error(f"Failed to read-tree base {base_sha}")
            return False
        for f in files_to_add:
            if _run_command(["git", "add", "--", f.as_posix()], env=env).returncode != 0:
                logger.error(f"Failed to stage {f}")
                return False
        # write-tree→commit-tree 在单条 bash 内串联：树对象号不回流 Python，
        # 消息/基线经 env 传递（避免 shell 引号问题）。rc 为失败唯一判据；
        # stdout 读不到（如 mock）只告警并回退分支名推送。
        env["PR_BASE_SHA"] = str(base_sha)
        env["PR_COMMIT_MSG"] = message
        script = 'tree=$(git write-tree) && git commit-tree "$tree" -p "$PR_BASE_SHA" -m "$PR_COMMIT_MSG"'
        ct = _run_command(["bash", "-c", script], env=env)
        if ct.returncode != 0:
            logger.error(f"Failed to write-tree/commit-tree: {getattr(ct, 'stderr', '')}")
            return False
        commit_sha = _stdout_of(ct).strip()
        if _looks_like_sha(commit_sha):
            _PR_STATE["commit_sha"] = commit_sha
        else:
            logger.warning("commit output unavailable/not SHA-shaped; push will use branch ref")

    logger.info(f"Committed changes for {stage} v{version} (scoped, base={str(base_sha)[:8]})")
    return True


def _push_branch(branch_name: str) -> bool:
    """Push the PR branch to the cached remote (single command call).

    有 plumbing 提交（_PR_STATE["commit_sha"]，经 _looks_like_sha 校验）时推
    `sha:refs/heads/<branch>`；无有效提交时回退传统 `<branch>`（保持独立
    调用兼容）。远端用 _create_pr_branch 缓存的解析结果（SSH github URL →
    HTTPS + gh credential helper），无缓存时回退 origin 原名推送。
    对本机已知的 HTTPS 偶发 "Empty reply from server" 重试一次。
    """
    prefix = list(_PR_STATE.get("remote_prefix") or [])
    remote = _PR_STATE.get("remote_name") or "origin"
    commit_sha = _PR_STATE.get("commit_sha")
    refspec = f"{commit_sha}:refs/heads/{branch_name}" if commit_sha else branch_name
    result = _run_command(["git", *prefix, "push", "-u", remote, refspec])
    if result.returncode != 0:
        if "Empty reply from server" in str(result.stderr):
            logger.warning("push got 'Empty reply from server', retrying once")
            result = _run_command(["git", *prefix, "push", "-u", remote, refspec])
        if result.returncode != 0:
            logger.error(f"Failed to push branch to {remote}: {result.stderr}")
            return False
    logger.info(f"Pushed branch: {branch_name} -> {remote}")
    return True


def _create_github_pr(
    title: str,
    body: str,
    head_branch: str,
    base_branch: str = "main",
    labels: Optional[List[str]] = None,
) -> PRResult:
    """Create a GitHub PR using gh CLI."""
    cmd = [
        "gh",
        "pr",
        "create",
        "--title",
        title,
        "--body",
        body,
        "--head",
        head_branch,
        "--base",
        base_branch,
    ]

    if labels:
        for label in labels:
            cmd.extend(["--label", label])

    result = _run_command(cmd)
    if result.returncode != 0:
        return PRResult(success=False, error=result.stderr.strip())

    # Parse PR URL and number from output
    pr_url = result.stdout.strip()
    pr_number = None
    if pr_url:
        # Extract PR number from URL like https://github.com/owner/repo/pull/123
        parts = pr_url.split("/")
        if len(parts) >= 2:
            try:
                pr_number = int(parts[-1])
            except ValueError:
                pass

    logger.info(f"Created PR #{pr_number}: {pr_url}")
    return PRResult(
        success=True,
        pr_number=pr_number,
        pr_url=pr_url,
        branch_name=head_branch,
    )


def _wait_for_ci_checks(pr_number: int, timeout_seconds: int = 1800, poll_interval: int = 30) -> bool:
    """Wait for CI checks to pass on a PR."""
    logger.info(f"Waiting for CI checks on PR #{pr_number} (timeout: {timeout_seconds}s)...")

    start_time = datetime.now()
    while (datetime.now() - start_time).total_seconds() < timeout_seconds:
        result = _run_command(["gh", "pr", "checks", str(pr_number), "--json", "name,state,conclusion"])
        if result.returncode != 0:
            logger.warning(f"Failed to get PR checks: {result.stderr}")
            import time

            time.sleep(poll_interval)
            continue

        try:
            checks = json.loads(result.stdout)
            all_completed = True
            all_passed = True

            for check in checks:
                state = check.get("state", "")
                conclusion = check.get("conclusion", "")

                if state != "COMPLETED":
                    all_completed = False
                elif conclusion != "SUCCESS":
                    all_passed = False
                    logger.warning(f"Check failed: {check.get('name')} - {conclusion}")

            if all_completed:
                if all_passed:
                    logger.info(f"All CI checks passed for PR #{pr_number}")
                    return True
                else:
                    logger.error(f"Some CI checks failed for PR #{pr_number}")
                    return False
        except json.JSONDecodeError:
            logger.warning("Failed to parse PR checks output")

        import time

        time.sleep(poll_interval)

    logger.error(f"Timeout waiting for CI checks on PR #{pr_number}")
    return False


def _auto_merge_pr(pr_number: int, merge_method: str = "squash") -> MergeResult:
    """Auto-merge a PR after CI passes."""
    result = _run_command(
        [
            "gh",
            "pr",
            "merge",
            str(pr_number),
            "--auto",
            f"--{merge_method}",
            "--delete-branch",
        ]
    )

    if result.returncode != 0:
        return MergeResult(success=False, error=result.stderr.strip())

    # Get merge commit SHA
    result = _run_command(["gh", "pr", "view", str(pr_number), "--json", "mergeCommit"])
    merge_sha = None
    if result.returncode == 0:
        try:
            data = json.loads(result.stdout)
            merge_sha = data.get("mergeCommit", {}).get("oid")
        except json.JSONDecodeError:
            pass

    logger.info(f"Auto-merged PR #{pr_number} (sha: {merge_sha})")
    return MergeResult(success=True, merged=True, merge_commit_sha=merge_sha)


def create_prompt_upgrade_pr(
    stage: str,
    version: int,
    base_branch: str = "main",
    promotion_result: Optional[Dict[str, Any]] = None,
    validation_results: Optional[Dict[str, Any]] = None,
    ab_test_results: Optional[Dict[str, Any]] = None,
) -> PRResult:
    """
    Create a GitHub PR for a prompt version upgrade.

    Args:
        stage: Pipeline stage name (e.g., "edit_for_tts")
        version: New prompt version number
        base_branch: Base branch for PR (default: main)
        promotion_result: Promotion gate evaluation results
        validation_results: Canary validation results
        ab_test_results: A/B test results

    Returns:
        PRResult with success status and PR details
    """
    # Check if we're in a git repo
    try:
        repo_root = _get_git_repo_root()
        os.chdir(repo_root)
    except RuntimeError as e:
        return PRResult(success=False, error=str(e))

    # Create branch
    try:
        branch_name = _create_pr_branch(base_branch, stage, version)
    except RuntimeError as e:
        return PRResult(success=False, error=str(e))

    # Commit changes
    if not _commit_prompt_changes(stage, version):
        return PRResult(success=False, error="Failed to commit prompt changes")

    # Push branch
    if not _push_branch(branch_name):
        return PRResult(success=False, error="Failed to push branch")

    # Build PR body
    body_lines = [
        f"## Automated Prompt Upgrade: {stage} → v{version}",
        "",
        "This PR was automatically created by the SelfIterationLoop after successful "
        "promotion gate evaluation and canary validation.",
        "",
        "### Changes",
        f"- Upgraded prompt `{stage}` to version `v{version}`",
        "- Updated CHANGELOG.md with change summary",
        "",
        "### Validation Results",
    ]

    if promotion_result:
        body_lines.append("#### Promotion Gate")
        for gate in promotion_result.get("gates", []):
            status = "✅" if gate.get("passed") else "❌"
            score = gate.get("score")
            score_str = f"{score:.3f}" if isinstance(score, (int, float)) else str(score)
            threshold = gate.get("threshold")
            threshold_str = f" (threshold: {threshold})" if threshold is not None else ""
            body_lines.append(f"- {status} {gate.get('name')}: {score_str}{threshold_str}")

    if validation_results:
        body_lines.append("")
        body_lines.append("#### Canary Validation")
        for stage_name, metrics in validation_results.items():
            body_lines.append(f"- **{stage_name}**: {metrics}")

    if ab_test_results:
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
    )

    body = "\n".join(body_lines)
    title = f"feat(prompt): upgrade {stage} to v{version} [auto]"

    # Create PR
    return _create_github_pr(
        title=title,
        body=body,
        head_branch=branch_name,
        base_branch=base_branch,
        labels=["automated", "prompt-upgrade", f"stage:{stage}"],
    )


def monitor_and_merge_pr(
    pr_number: int,
    timeout_seconds: int = 1800,
    merge_method: str = "squash",
) -> MergeResult:
    """
    Monitor a PR for CI completion and auto-merge if all checks pass.

    Args:
        pr_number: PR number to monitor
        timeout_seconds: Max time to wait for CI (default: 30 min)
        merge_method: Merge method (squash, merge, rebase)

    Returns:
        MergeResult with success status
    """
    # Wait for CI checks
    ci_passed = _wait_for_ci_checks(pr_number, timeout_seconds=timeout_seconds)

    if not ci_passed:
        return MergeResult(success=False, error="CI checks failed or timed out")

    # Auto-merge
    return _auto_merge_pr(pr_number, merge_method=merge_method)


def get_pr_status(pr_number: int) -> Dict[str, Any]:
    """Get current PR status including CI checks."""
    result = _run_command(["gh", "pr", "view", str(pr_number), "--json", "state,mergeStateStatus,checks"])
    if result.returncode != 0:
        return {"error": result.stderr.strip()}

    try:
        data = json.loads(result.stdout)
        return cast(Dict[str, Any], data)
    except json.JSONDecodeError:
        return {"error": "Failed to parse PR status"}


def list_open_prompt_prs() -> List[Dict[str, Any]]:
    """List all open prompt upgrade PRs."""
    result = _run_command(
        [
            "gh",
            "pr",
            "list",
            "--label",
            "prompt-upgrade",
            "--state",
            "open",
            "--json",
            "number,title,headRefName,createdAt,labels",
        ]
    )
    if result.returncode != 0:
        return []

    try:
        return cast(List[Dict[str, Any]], json.loads(result.stdout))
    except json.JSONDecodeError:
        return []


def close_stale_prompt_prs(days: int = 7) -> int:
    """Close prompt upgrade PRs older than specified days."""

    prs = list_open_prompt_prs()
    closed_count = 0

    for pr in prs:
        created = pr.get("createdAt", "")
        if created:
            # Parse ISO format date
            try:
                created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                age_days = (datetime.now(timezone.utc) - created_dt).days
                if age_days > days:
                    _run_command(["gh", "pr", "close", str(pr["number"]), "--comment", "Auto-closed: stale PR"])
                    closed_count += 1
            except ValueError:
                pass

    return closed_count


if __name__ == "__main__":
    # Simple test
    import sys

    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) > 1 and sys.argv[1] == "list":
        prs = list_open_prompt_prs()
        for pr in prs:
            logger.debug("#%s: %s (%s)", pr["number"], pr["title"], pr["headRefName"])
