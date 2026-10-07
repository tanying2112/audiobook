"""PR 机制契约验证：脱离 pytest/conftest，用 unittest 复刻
tests/unit/test_pr_automation.py 中 pin 内部实现的 7 个 helper 断言
（其余 integration 测试全量 mock 三个函数，不受实现影响）。

跑法：.venv/bin/python scratch/verify_pr_contract.py -v
"""
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src.audiobook_studio.feedback.pr_automation import (  # noqa: E402
    _commit_prompt_changes,
    _create_pr_branch,
    _push_branch,
    _run_command,
)


def _proc(rc=0, stdout=None, stderr=None):
    """rc 恒设；stdout/stderr 不传则保持 auto-MagicMock（复刻原测试：成功路径
    的 stdout 是 MagicMock 而非 str，正是实现必须归一化处理的对象）。"""
    m = MagicMock(spec=subprocess.CompletedProcess)
    m.returncode = rc
    if stdout is not None:
        m.stdout = stdout
    if stderr is not None:
        m.stderr = stderr
    return m


class PRContractTest(unittest.TestCase):
    def setUp(self):
        import src.audiobook_studio.feedback.pr_automation as pa
        pa._PR_STATE.update({"base_sha": None, "commit_sha": None, "branch_name": None,
                             "remote_prefix": [], "remote_name": "origin"})
        self.pa = pa

    def test_run_command_pinned_kwargs(self):
        with patch("subprocess.run") as mr:
            mr.return_value = _proc(0, "success", "")
            r = _run_command(["echo", "hello"])
            self.assertEqual(r.stdout, "success")
            mr.assert_called_once_with(["echo", "hello"], cwd=None, capture_output=True, text=True)

    def test_create_branch_success(self):
        with patch.object(self.pa, "_run_command") as mr:
            mr.return_value = _proc(0)  # stdout 为 MagicMock（与原测试一致）
            name = _create_pr_branch("main", "edit_for_tts", 2)
            self.assertTrue(name.startswith("auto/prompt-upgrade-edit_for_tts-v2-"))
            self.assertFalse(name.endswith("-"))
            self.assertGreaterEqual(mr.call_count, 2)
            # 无 checkout：全程不得出现 checkout 子命令
            for c in mr.call_args_list:
                self.assertNotIn("checkout", c.args[0])

    def test_create_branch_failure(self):
        with patch.object(self.pa, "_run_command") as mr:
            mr.return_value = _proc(1, "", "failed to create branch")
            with self.assertRaisesRegex(RuntimeError, "Failed to create branch"):
                _create_pr_branch("main", "edit_for_tts", 2)

    def test_commit_success(self):
        with patch("pathlib.Path.exists", return_value=True), patch.object(self.pa, "_run_command") as mr:
            mr.return_value = _proc(0)  # stdout MagicMock
            self.assertTrue(_commit_prompt_changes("edit_for_tts", 2))
            self.assertGreaterEqual(mr.call_count, 3)
            # 零 checkout / 零裸 commit：全部走 plumbing（read-tree/add/write-tree/commit-tree）
            for c in mr.call_args_list:
                cmd = c.args[0]
                self.assertNotIn("checkout", cmd)
                self.assertNotEqual(cmd[:2], ["git", "commit"])
            # MagicMock 输出不得被存成 commit_sha（污染后续 push refspec）
            self.assertIsNone(self.pa._PR_STATE["commit_sha"])

    def test_commit_no_files(self):
        with patch("pathlib.Path.exists", return_value=False):
            self.assertFalse(_commit_prompt_changes("edit_for_tts", 2))

    def test_commit_stage_failure(self):
        with patch("pathlib.Path.exists", return_value=True), patch.object(self.pa, "_run_command") as mr:
            mr.side_effect = [_proc(0), _proc(0), _proc(1, "", "failed to add")]
            self.assertFalse(_commit_prompt_changes("edit_for_tts", 2))

    def test_commit_commit_failure(self):
        with patch("pathlib.Path.exists", return_value=True), patch.object(self.pa, "_run_command") as mr:
            mr.side_effect = [_proc(0), _proc(0), _proc(1, "", "failed to commit")]
            self.assertFalse(_commit_prompt_changes("edit_for_tts", 2))

    def test_push_pinned_exact_call(self):
        with patch.object(self.pa, "_run_command") as mr:
            mr.return_value = _proc(0)
            self.assertTrue(_push_branch("test-branch"))
            mr.assert_called_once_with(["git", "push", "-u", "origin", "test-branch"])

    def test_push_failure_no_retry(self):
        with patch.object(self.pa, "_run_command") as mr:
            mr.return_value = _proc(1, "", "failed to push")
            self.assertFalse(_push_branch("test-branch"))
            mr.assert_called_once()

    def test_push_empty_reply_retries_once(self):
        with patch.object(self.pa, "_run_command") as mr:
            mr.side_effect = [_proc(1, "", "fatal: unable to access ...: Empty reply from server"), _proc(0)]
            self.assertTrue(_push_branch("test-branch"))
            self.assertEqual(mr.call_count, 2)

    def test_push_with_real_sha_refspec(self):
        sha = "a" * 40
        self.pa._PR_STATE.update({"commit_sha": sha, "remote_prefix": ["-c", "credential.helper=!gh auth git-credential"],
                                  "remote_name": "https://github.com/o/r.git"})
        with patch.object(self.pa, "_run_command") as mr:
            mr.return_value = _proc(0)
            self.assertTrue(_push_branch("auto/x"))
            mr.assert_called_once_with(
                ["git", "-c", "credential.helper=!gh auth git-credential", "push", "-u",
                 "https://github.com/o/r.git", f"{sha}:refs/heads/auto/x"]
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
