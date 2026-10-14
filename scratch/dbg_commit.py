import subprocess, sys
from pathlib import Path
from unittest.mock import MagicMock, patch
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import src.audiobook_studio.feedback.pr_automation as pa

def _proc(rc=0, stdout="", stderr=""):
    m = MagicMock(spec=subprocess.CompletedProcess)
    m.returncode = rc; m.stdout = stdout; m.stderr = stderr
    return m

pa._PR_STATE.update({"base_sha": None, "commit_sha": None, "remote_prefix": [], "remote_name": "origin"})
calls = []
def fake_run(cmd, **kw):
    calls.append((cmd, kw.get("env")))
    return _proc(0)

with patch("pathlib.Path.exists", return_value=True), patch.object(pa, "_run_command", side_effect=fake_run):
    ok = pa._commit_prompt_changes("edit_for_tts", 2)
    print("result:", ok)
    for c, e in calls:
        print("CALL:", c, "| env-GIT_INDEX_FILE:", (e or {}).get("GIT_INDEX_FILE"))
    print("commit_sha state:", pa._PR_STATE["commit_sha"])
    print("base_sha state:", pa._PR_STATE["base_sha"])
