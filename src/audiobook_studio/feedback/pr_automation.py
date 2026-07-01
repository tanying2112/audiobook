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
from typing import Any, Dict, List, Optional

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


def _run_command(cmd: List[str], cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
    """Run a shell command and return result."""
    logger.debug(f"Running command: {' '.join(cmd)}")
    result = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
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


def _create_pr_branch(base_branch: str, stage: str, version: int) -> str:
    """Create and checkout a new branch for the PR."""
    branch_name = f"auto/prompt-upgrade-{stage}-v{version}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"

    # Fetch latest
    _run_command(["git", "fetch", "origin", base_branch])

    # Create new branch from base
    result = _run_command(["git", "checkout", "-b", branch_name, f"origin/{base_branch}"])
    if result.returncode != 0:
        raise RuntimeError(f"Failed to create branch: {result.stderr}")

    logger.info(f"Created branch: {branch_name}")
    return branch_name


def _commit_prompt_changes(stage: str, version: int, message: Optional[str] = None) -> bool:
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
        message = f"feat(prompt): upgrade {stage} to v{version}\n\nAutomated prompt upgrade via SelfIterationLoop"

    result = _run_command(["git", "commit", "-m", message])
    if result.returncode != 0:
        logger.error(f"Failed to commit: {result.stderr}")
        return False

    logger.info(f"Committed changes for {stage} v{version}")
    return True


def _push_branch(branch_name: str) -> bool:
    """Push the branch to origin."""
    result = _run_command(["git", "push", "-u", "origin", branch_name])
    if result.returncode != 0:
        logger.error(f"Failed to push branch: {result.stderr}")
        return False
    logger.info(f"Pushed branch: {branch_name}")
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
        "gh", "pr", "create",
        "--title", title,
        "--body", body,
        "--head", head_branch,
        "--base", base_branch,
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
    result = _run_command([
        "gh", "pr", "merge", str(pr_number),
        "--auto",
        f"--{merge_method}",
        "--delete-branch",
    ])

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
    branch_name = _create_pr_branch(base_branch, stage, version)

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
        f"- Updated CHANGELOG.md with change summary",
        "",
        "### Validation Results",
    ]

    if promotion_result:
        body_lines.append("#### Promotion Gate")
        for gate in promotion_result.get("gates", []):
            status = "✅" if gate.get("passed") else "❌"
            body_lines.append(f"- {status} {gate.get('name')}: {gate.get('score'):.3f} (threshold: {gate.get('threshold')})")

    if validation_results:
        body_lines.append("")
        body_lines.append("#### Canary Validation")
        for stage_name, metrics in validation_results.items():
            body_lines.append(f"- **{stage_name}**: {metrics}")

    if ab_test_results:
        body_lines.append("")
        body_lines.append("#### A/B Test Results")
        body_lines.append(f"- Samples: {ab_test_results.get('num_samples', 'N/A')}")
        body_lines.append(f"- Improvement: {ab_test_results.get('improvement_pct', 'N/A'):.1f}%")
        body_lines.append(f"- Significant: {ab_test_results.get('is_significant', 'N/A')}")
        body_lines.append(f"- Recommendation: {ab_test_results.get('recommendation', 'N/A')}")

    body_lines.extend([
        "",
        "---",
        "*Auto-generated by Audiobook Studio SelfIterationLoop*",
    ])

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
        return data
    except json.JSONDecodeError:
        return {"error": "Failed to parse PR status"}


def list_open_prompt_prs() -> List[Dict[str, Any]]:
    """List all open prompt upgrade PRs."""
    result = _run_command([
        "gh", "pr", "list",
        "--label", "prompt-upgrade",
        "--state", "open",
        "--json", "number,title,headRefName,createdAt,labels",
    ])
    if result.returncode != 0:
        return []

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return []


def close_stale_prompt_prs(days: int = 7) -> int:
    """Close prompt upgrade PRs older than specified days."""
    import time

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
            except Exception:
                pass

    return closed_count


if __name__ == "__main__":
    # Simple test
    import sys
    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) > 1 and sys.argv[1] == "list":
        prs = list_open_prompt_prs()
        for pr in prs:
            logger.debug("#%s: %s (%s)", pr['number'], pr['title'], pr['headRefName'])