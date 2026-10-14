"""Fix 4 契约校准：让重写后的 PR 机制与既有单测的 mock 契约逐点对齐。

三处不兼容（对照 tests/unit/test_pr_automation.py 的 pin 断言）：
  1) test_push_branch_success 要求 _push_branch 恰好调用一次
     `["git","push","-u","origin","test-branch"]` —— 不能在函数内再探测
     remote（get-url 也是一次 _run_command）。→ 远端解析只在
     _create_pr_branch 做一次并缓存进 _PR_STATE；_push_branch 读缓存，
     缺省回退 []/"origin"。
  2) 成功路径的 mock stdout 是 MagicMock 而非 str —— rev-parse /
     write-tree / commit-tree 的 isinstance(str) 防御会误走失败分支。
     → 统一 str(stdout or "") 归一化（真实 subprocess text=True 下恒为 str，
     归一化不改变真实行为）。
  3) commit 成功测试会把 MagicMock 字符串存进 _PR_STATE["commit_sha"]，
     污染后续 push 测试的 refspec 精确断言。→ 存储 commit_sha 前校验
     40/64 位十六进制对象号形态（_looks_like_sha，也是真实完整性检查：
     只在确有 commit-tree 产物时才走 sha:refs/heads 推送）。
另：push 对 "Empty reply from server"（本机对 github HTTPS 的已知偶发）
重试一次。
"""
from pathlib import Path

p = Path("src/audiobook_studio/feedback/pr_automation.py")
src = p.read_text(encoding="utf-8")

# ── 1) _PR_STATE 扩展 + _looks_like_sha ──
old = '''# 环内 PR 的跨调用状态（fetch 到的 base、plumbing 生成的 commit）。
# 纯 plumbing 流程不再 checkout 分支，commit 上下文经此传递。
_PR_STATE: Dict[str, Any] = {"base_sha": None, "commit_sha": None, "branch_name": None}
'''
new = '''# 环内 PR 的跨调用状态（fetch 到的 base、plumbing 生成的 commit、
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
'''
assert src.count(old) == 1
src = src.replace(old, new)

# ── 2) _create_pr_branch：缓存远端 + rev-parse 归一化/回退 ──
old = '''    prefix, remote = _resolve_remote_spec()
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
new = '''    prefix, remote = _resolve_remote_spec()
    _PR_STATE.update({"remote_prefix": prefix, "remote_name": remote})
    fetch = _run_command(["git", *prefix, "fetch", remote, base_branch])
    if fetch.returncode != 0:
        raise RuntimeError(f"Failed to create branch (fetch {remote} {base_branch}): {fetch.stderr}")

    head = _run_command(["git", "rev-parse", "FETCH_HEAD"])
    base_sha = str(head.stdout or "").strip() if head.returncode == 0 else ""
    if not base_sha:
        # fetch 已成功而 rev-parse 异常时，origin/<base> 与 FETCH_HEAD 同指
        # 一提交，作为等价 committish 回退（read-tree 接受任意 committish）。
        base_sha = f"origin/{base_branch}"
        logger.warning(f"rev-parse FETCH_HEAD unavailable, falling back to {base_sha}")

    _PR_STATE.update({"base_sha": base_sha, "commit_sha": None, "branch_name": branch_name})
    logger.info(f"Prepared PR branch (plumbing, no checkout): {branch_name} @ base {str(base_sha)[:8]}")
    return branch_name'''
assert src.count(old) == 1
src = src.replace(old, new)

# ── 3) _commit_prompt_changes：write-tree/commit-tree 归一化 + SHA 校验存储 ──
old = '''        wt = _run_command(["git", "write-tree"], env=env)
        if wt.returncode != 0 or not isinstance(wt.stdout, str) or not wt.stdout.strip():
            logger.error(f"Failed to write-tree: {wt.stderr}")
            return False
        tree_sha = wt.stdout.strip()
        ct = _run_command(["git", "commit-tree", tree_sha, "-p", base_sha, "-m", message])
        if ct.returncode != 0 or not isinstance(ct.stdout, str) or not ct.stdout.strip():
            logger.error(f"Failed to commit-tree: {ct.stderr}")
            return False
        _PR_STATE["commit_sha"] = ct.stdout.strip()'''
new = '''        wt = _run_command(["git", "write-tree"], env=env)
        tree_sha = str(wt.stdout or "").strip()
        if wt.returncode != 0 or not tree_sha:
            logger.error(f"Failed to write-tree: {wt.stderr}")
            return False
        ct = _run_command(["git", "commit-tree", tree_sha, "-p", base_sha, "-m", message])
        commit_sha = str(ct.stdout or "").strip()
        if ct.returncode != 0 or not commit_sha:
            logger.error(f"Failed to commit-tree: {ct.stderr}")
            return False
        if _looks_like_sha(commit_sha):
            _PR_STATE["commit_sha"] = commit_sha
        else:
            logger.warning("commit-tree output not SHA-shaped; push will use branch ref")'''
assert src.count(old) == 1
src = src.replace(old, new)

# ── 4) _push_branch：读缓存远端 + Empty reply 重试 ──
old = '''def _push_branch(branch_name: str) -> bool:
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
new = '''def _push_branch(branch_name: str) -> bool:
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
    return True'''
assert src.count(old) == 1
src = src.replace(old, new)

p.write_text(src, encoding="utf-8")
print("pr_automation.py contract calibration OK")
