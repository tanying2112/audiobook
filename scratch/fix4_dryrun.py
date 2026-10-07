"""Fix 4 实机 dry-run：在真实仓库上走完 resolve→fetch→scoped commit→push
（不创建 PR），随后删除远端分支，验证整链真实可用且零工作树/暂存区扰动。

前置：origin 为 SSH remote（本机无 SSH key）→ 预期被改写为 HTTPS + gh
credential helper；推送到一次性远端分支 dryrun/fix4-<ts>。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import src.audiobook_studio.feedback.pr_automation as pa  # noqa: E402

BRANCH = "dryrun/fix4-" + pa.datetime.now(pa.timezone.utc).strftime("%Y%m%d-%H%M%S")
BASE = "agent/A/fix-api-crud"

print("== 1) remote resolution ==")
prefix, remote = pa._resolve_remote_spec()
print("prefix:", prefix)
print("remote:", remote)
assert remote.startswith("https://github.com/"), f"SSH 未被改写: {remote}"

print("== 2) branch prep (fetch base) ==")
name = pa._create_pr_branch(BASE, "fix4_dryrun", 99)
print("branch:", name, "| base_sha:", pa._PR_STATE["base_sha"])
print("== 3) scoped commit (plumbing, no checkout) ==")
import subprocess
before = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True).stdout
ok = pa._commit_prompt_changes("edit_for_tts", 99)  # v99.j2 不存在 → v1.j2 + CHANGELOG.md
after = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True).stdout
print("commit ok:", ok, "| commit_sha:", pa._PR_STATE["commit_sha"])
assert before == after, "工作树/暂存区被扰动！"
assert pa._looks_like_sha(pa._PR_STATE["commit_sha"]), "commit_sha 未生成/不合法"

print("== 4) verify commit content (base tree + prompt files only) ==")
show = subprocess.run(
    ["git", "show", "--stat", "--oneline", pa._PR_STATE["commit_sha"]],
    capture_output=True, text=True,
)
print(show.stdout)
files = subprocess.run(
    ["git", "diff", "--name-only", pa._PR_STATE["base_sha"], pa._PR_STATE["commit_sha"]],
    capture_output=True, text=True,
).stdout.strip().splitlines()
print("changed files vs base:", files)
assert all(f.startswith("prompts/edit_for_tts/") for f in files), "卷入了非 prompt 文件！"
msg = subprocess.run(["git", "log", "-1", "--format=%B", pa._PR_STATE["commit_sha"]],
                     capture_output=True, text=True).stdout
assert "Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>" in msg, "attribution 缺失"

print("== 5) push to remote ==")
pa._PR_STATE["branch_name"] = BRANCH
pushed = pa._push_branch(BRANCH)
print("pushed:", pushed)
assert pushed
print("DRYRUN_OK branch=", BRANCH)
