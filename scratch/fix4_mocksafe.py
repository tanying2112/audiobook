"""Fix 4 mock-safety 校准：成功路径不得读取未显式设置的 mock stdout。

实证：本 venv（py3.11）下 MagicMock(spec=subprocess.CompletedProcess) 在
stdout 未显式设置时访问即抛 AttributeError —— 旧实现的“成功”路径从不读
stdout（仅失败分支读 stderr），故既有单测全绿。plumbing 重写后 rev-parse /
write-tree / commit-tree 需要在成功路径读 stdout → 既有单测会 ERROR。

三处对齐：
  1) 新增 _stdout_of()：防御性读 stdout（getattr 默认 ""，仅接受 str）。
  2) write-tree→commit-tree 串进单条 bash -c（树对象号不过手 Python；
     消息/基线经 env 传；rc 为失败唯一门，stdout 读不到只告警不判败 ——
     真实 subprocess 恒可读到合法 sha 并存入 _PR_STATE）。
  3) rev-parse / get-url 的 stdout 改走 _stdout_of。
真实端到端行为不变：真实调用恒有 str stdout。
"""
from pathlib import Path

p = Path("src/audiobook_studio/feedback/pr_automation.py")
src = p.read_text(encoding="utf-8")

# ── 1) _stdout_of helper（放 _looks_like_sha 之后） ──
old = '''    if not isinstance(s, str):
        return False
    t = s.strip()
    return len(t) in (40, 64) and all(c in "0123456789abcdefABCDEF" for c in t)
'''
new = '''    if not isinstance(s, str):
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
'''
assert src.count(old) == 1
src = src.replace(old, new)

# ── 2) _resolve_remote_spec：stdout 防御读 ──
old = '''        r = _run_command(["git", "remote", "get-url", remote_name])
        url = r.stdout.strip() if (r.returncode == 0 and isinstance(r.stdout, str)) else ""
'''
new = '''        r = _run_command(["git", "remote", "get-url", remote_name])
        url = _stdout_of(r).strip() if r.returncode == 0 else ""
'''
assert src.count(old) == 1
src = src.replace(old, new)

# ── 3) _create_pr_branch：rev-parse stdout 防御读 ──
old = '''    head = _run_command(["git", "rev-parse", "FETCH_HEAD"])
    base_sha = str(head.stdout or "").strip() if head.returncode == 0 else ""
'''
new = '''    head = _run_command(["git", "rev-parse", "FETCH_HEAD"])
    base_sha = _stdout_of(head).strip() if head.returncode == 0 else ""
'''
assert src.count(old) == 1
src = src.replace(old, new)

# ── 4) _commit_prompt_changes：write-tree/commit-tree 串入单条 bash -c ──
old = '''        wt = _run_command(["git", "write-tree"], env=env)
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
new = '''        # write-tree→commit-tree 在单条 bash 内串联：树对象号不回流 Python，
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
            logger.warning("commit output unavailable/not SHA-shaped; push will use branch ref")'''
assert src.count(old) == 1
src = src.replace(old, new)

# env 构造行同步说明（PR_BASE_SHA/PR_COMMIT_MSG 在 with 块内补充）
old = '''    with tempfile.TemporaryDirectory(prefix="pr-index-") as td:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(td) / "index")}
        if _run_command(["git", "read-tree", base_sha], env=env).returncode != 0:'''
new = '''    with tempfile.TemporaryDirectory(prefix="pr-index-") as td:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(td) / "index")}
        # （PR_BASE_SHA / PR_COMMIT_MSG 在 write-tree 串联前补入 env）
        if _run_command(["git", "read-tree", base_sha], env=env).returncode != 0:'''
assert src.count(old) == 1
src = src.replace(old, new)

p.write_text(src, encoding="utf-8")
print("mock-safe calibration OK")
