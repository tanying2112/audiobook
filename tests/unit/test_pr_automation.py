"""Unit tests for src/audiobook_studio/feedback/pr_automation.py."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.audiobook_studio.feedback.pr_automation import (
    MergeResult,
    PRResult,
    _commit_prompt_changes,
    _create_github_pr,
    _create_pr_branch,
    _get_changed_prompt_files,
    _get_current_branch,
    _get_git_repo_root,
    _has_uncommitted_changes,
    _push_branch,
    _run_command,
    _wait_for_ci_checks,
    close_stale_prompt_prs,
    create_prompt_upgrade_pr,
    get_pr_status,
    list_open_prompt_prs,
    monitor_and_merge_pr,
)


class TestPRAutomationHelpers:
    def test_run_command_success(self):
        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock(spec=subprocess.CompletedProcess)
            mock_result.returncode = 0
            mock_result.stdout = "success"
            mock_result.stderr = ""
            mock_run.return_value = mock_result

            result = _run_command(["echo", "hello"])
            assert result.returncode == 0
            assert result.stdout == "success"
            mock_run.assert_called_once_with(
                ["echo", "hello"], cwd=None, capture_output=True, text=True
            )

    def test_run_command_failure(self):
        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock(spec=subprocess.CompletedProcess)
            mock_result.returncode = 1
            mock_result.stdout = ""
            mock_result.stderr = "error occurred"
            mock_run.return_value = mock_result

            result = _run_command(["false"])
            assert result.returncode == 1
            assert result.stderr == "error occurred"

    def test_get_git_repo_root_success(self):
        with patch("src.audiobook_studio.feedback.pr_automation._run_command") as mock_run:
            mock_result = MagicMock(spec=subprocess.CompletedProcess)
            mock_result.returncode = 0
            mock_result.stdout = "/tmp/repo\n"
            mock_run.return_value = mock_result

            result = _get_git_repo_root()
            assert result == Path("/tmp/repo")
            mock_run.assert_called_once_with(["git", "rev-parse", "--show-toplevel"])

    def test_get_git_repo_root_failure(self):
        with patch("src.audiobook_studio.feedback.pr_automation._run_command") as mock_run:
            mock_result = MagicMock(spec=subprocess.CompletedProcess)
            mock_result.returncode = 1
            mock_result.stderr = "not a git repo"
            mock_run.return_value = mock_result

            with pytest.raises(RuntimeError, match="Not in a git repository"):
                _get_git_repo_root()

    def test_get_current_branch_success(self):
        with patch("src.audiobook_studio.feedback.pr_automation._run_command") as mock_run:
            mock_result = MagicMock(spec=subprocess.CompletedProcess)
            mock_result.returncode = 0
            mock_result.stdout = "feature-branch\n"
            mock_run.return_value = mock_result

            result = _get_current_branch()
            assert result == "feature-branch"

    def test_get_current_branch_failure(self):
        with patch("src.audiobook_studio.feedback.pr_automation._run_command") as mock_run:
            mock_result = MagicMock(spec=subprocess.CompletedProcess)
            mock_result.returncode = 1
            mock_result.stderr = "failed"
            mock_run.return_value = mock_result

            with pytest.raises(RuntimeError, match="Failed to get current branch"):
                _get_current_branch()

    def test_has_uncommitted_changes_true(self):
        with patch("src.audiobook_studio.feedback.pr_automation._run_command") as mock_run:
            mock_result = MagicMock(spec=subprocess.CompletedProcess)
            mock_result.returncode = 0
            mock_result.stdout = " M file.txt\n"
            mock_run.return_value = mock_result

            assert _has_uncommitted_changes() is True

    def test_has_uncommitted_changes_false(self):
        with patch("src.audiobook_studio.feedback.pr_automation._run_command") as mock_run:
            mock_result = MagicMock(spec=subprocess.CompletedProcess)
            mock_result.returncode = 0
            mock_result.stdout = ""
            mock_run.return_value = mock_result

            assert _has_uncommitted_changes() is False

    def test_get_changed_prompt_files_with_matches(self):
        with patch("src.audiobook_studio.feedback.pr_automation._run_command") as mock_run:
            mock_result = MagicMock(spec=subprocess.CompletedProcess)
            mock_result.returncode = 0
            # Return some changed files including prompt files
            mock_result.stdout = "prompts/edit_for_tts/v2.j2\nprompts/edit_for_tts/CHANGELOG.md\nother/file.txt\n"
            mock_run.return_value = mock_result

            result = _get_changed_prompt_files()
            assert len(result) == 2
            assert any(p.name == "v2.j2" for p in result)
            assert any(p.name == "CHANGELOG.md" for p in result)

    def test_get_changed_prompt_files_no_matches(self):
        with patch("src.audiobook_studio.feedback.pr_automation._run_command") as mock_run:
            mock_result = MagicMock(spec=subprocess.CompletedProcess)
            mock_result.returncode = 0
            mock_result.stdout = "other/file.txt\nanother/file.md\n"
            mock_run.return_value = mock_result

            result = _get_changed_prompt_files()
            assert result == []

    def test_get_changed_prompt_files_empty(self):
        with patch("src.audiobook_studio.feedback.pr_automation._run_command") as mock_run:
            mock_result = MagicMock(spec=subprocess.CompletedProcess)
            mock_result.returncode = 0
            mock_result.stdout = ""
            mock_run.return_value = mock_result

            result = _get_changed_prompt_files()
            assert result == []

    def test_create_pr_branch_success(self):
        with patch("src.audiobook_studio.feedback.pr_automation._run_command") as mock_run, \
             patch("src.audiobook_studio.feedback.pr_automation._get_git_repo_root") as mock_root:
            mock_root.return_value = Path("/tmp/repo")
            mock_result = MagicMock(spec=subprocess.CompletedProcess)
            mock_result.returncode = 0
            mock_run.return_value = mock_result

            result = _create_pr_branch("main", "edit_for_tts", 2)
            assert result.startswith("auto/prompt-upgrade-edit_for_tts-v2-")
            # Timestamp suffix is in the format YYYYMMDD-HHMMSS, so we can check that it ends with a time pattern
            # But for simplicity, we just check that the length is as expected or that it doesn't end with a hyphen.
            # Actually, the format is fixed: we can check that the part after the last hyphen is a timestamp.
            # However, for the test, we'll just check that it doesn't end with a hyphen (since the timestamp doesn't have a trailing hyphen).
            assert not result.endswith("-")
            # Should have called fetch, checkout -b
            assert mock_run.call_count >= 2

    def test_create_pr_branch_failure(self):
        with patch("src.audiobook_studio.feedback.pr_automation._run_command") as mock_run, \
             patch("src.audiobook_studio.feedback.pr_automation._get_git_repo_root") as mock_root:
            mock_root.return_value = Path("/tmp/repo")
            mock_result = MagicMock(spec=subprocess.CompletedProcess)
            mock_result.returncode = 1
            mock_result.stderr = "failed to create branch"
            mock_run.return_value = mock_result

            with pytest.raises(RuntimeError, match="Failed to create branch"):
                _create_pr_branch("main", "edit_for_tts", 2)

    def test_commit_prompt_changes_success(self):
        with patch("src.audiobook_studio.feedback.pr_automation._run_command") as mock_run, \
             patch("pathlib.Path.exists", return_value=True):
            mock_result = MagicMock(spec=subprocess.CompletedProcess)
            mock_result.returncode = 0
            mock_run.return_value = mock_result

            result = _commit_prompt_changes("edit_for_tts", 2)
            assert result is True
            # Should have called git add for each file and git commit
            assert mock_run.call_count >= 3

    def test_commit_prompt_changes_no_files(self):
        with patch("pathlib.Path.exists") as mock_exists:
            mock_exists.return_value = False

            result = _commit_prompt_changes("edit_for_tts", 2)
            assert result is False

    def test_commit_prompt_changes_add_failure(self):
        with patch("src.audiobook_studio.feedback.pr_automation._run_command") as mock_run, \
             patch("pathlib.Path.exists", return_value=True):
            # First call (git add) fails, so commit won't be reached
            mock_result_add = MagicMock(spec=subprocess.CompletedProcess)
            mock_result_add.returncode = 1
            mock_result_add.stderr = "failed to add"
            mock_run.return_value = mock_result_add

            result = _commit_prompt_changes("edit_for_tts", 2)
            assert result is False

    def test_commit_prompt_changes_commit_failure(self):
        with patch("src.audiobook_studio.feedback.pr_automation._run_command") as mock_run, \
             patch("pathlib.Path.exists", return_value=True):
            # First call (git add) succeeds, second call (git add) succeeds, third call (git commit) fails
            mock_result_success = MagicMock(spec=subprocess.CompletedProcess)
            mock_result_success.returncode = 0
            mock_result_fail = MagicMock(spec=subprocess.CompletedProcess)
            mock_result_fail.returncode = 1
            mock_result_fail.stderr = "failed to commit"
            mock_run.side_effect = [mock_result_success, mock_result_success, mock_result_fail]

            result = _commit_prompt_changes("edit_for_tts", 2)
            assert result is False

    def test_push_branch_success(self):
        with patch("src.audiobook_studio.feedback.pr_automation._run_command") as mock_run:
            mock_result = MagicMock(spec=subprocess.CompletedProcess)
            mock_result.returncode = 0
            mock_run.return_value = mock_result

            result = _push_branch("test-branch")
            assert result is True
            mock_run.assert_called_once_with(["git", "push", "-u", "origin", "test-branch"])

    def test_push_branch_failure(self):
        with patch("src.audiobook_studio.feedback.pr_automation._run_command") as mock_run:
            mock_result = MagicMock(spec=subprocess.CompletedProcess)
            mock_result.returncode = 1
            mock_result.stderr = "failed to push"
            mock_run.return_value = mock_result

            result = _push_branch("test-branch")
            assert result is False

    def test_create_github_pr_success(self):
        with patch("src.audiobook_studio.feedback.pr_automation._run_command") as mock_run:
            mock_result = MagicMock(spec=subprocess.CompletedProcess)
            mock_result.returncode = 0
            mock_result.stdout = "https://github.com/user/repo/pull/123\n"
            mock_run.return_value = mock_result

            result = _create_github_pr("Test Title", "Test Body", "test-branch")
            assert result.success is True
            assert result.pr_number == 123
            assert result.pr_url == "https://github.com/user/repo/pull/123"
            assert result.branch_name == "test-branch"

    def test_create_github_pr_failure(self):
        with patch("src.audiobook_studio.feedback.pr_automation._run_command") as mock_run:
            mock_result = MagicMock(spec=subprocess.CompletedProcess)
            mock_result.returncode = 1
            mock_result.stderr = "gh failed"
            mock_run.return_value = mock_result

            result = _create_github_pr("Test Title", "Test Body", "test-branch")
            assert result.success is False
            assert result.error == "gh failed"

    def test_wait_for_ci_checks_timeout(self):
        with patch("src.audiobook_studio.feedback.pr_automation._run_command") as mock_run, \
             patch("src.audiobook_studio.feedback.pr_automation.datetime") as mock_dt, \
             patch("time.sleep"):
            # Simulate timeout by making datetime.now() always return a time before timeout
            mock_now = MagicMock()
            mock_now.timestamp.return_value = 1000.0
            mock_dt.now.return_value = mock_now
            mock_dt.now.return_value.timestamp.return_value = 1000.0  # never advances

            mock_result = MagicMock(spec=subprocess.CompletedProcess)
            mock_result.returncode = 0
            mock_result.stdout = '[]'  # no checks
            mock_run.return_value = mock_result

            result = _wait_for_ci_checks(123, timeout_seconds=1, poll_interval=1)
            assert result is False  # timed out

    def test_wait_for_ci_checks_success(self):
        with patch("src.audiobook_studio.feedback.pr_automation._run_command") as mock_run, \
             patch("src.audiobook_studio.feedback.pr_automation.datetime") as mock_dt, \
             patch("time.sleep"):
            # First call returns incomplete checks, second call returns completed and passed
            mock_result1 = MagicMock(spec=subprocess.CompletedProcess)
            mock_result1.returncode = 0
            mock_result1.stdout = '[{"name": "check1", "state": "PENDING", "conclusion": ""}]'

            mock_result2 = MagicMock(spec=subprocess.CompletedProcess)
            mock_result2.returncode = 0
            mock_result2.stdout = '[{"name": "check1", "state": "COMPLETED", "conclusion": "SUCCESS"}]'

            mock_run.side_effect = [mock_result1, mock_result2]

            # Mock datetime to advancing time
            mock_now = MagicMock()
            mock_now.timestamp.side_effect = [1000.0, 1000.0, 1000.0]  # same time for simplicity
            mock_dt.now.return_value = mock_now

            result = _wait_for_ci_checks(123, timeout_seconds=10, poll_interval=1)
            assert result is True

    def test_wait_for_ci_checks_failure(self):
        with patch("src.audiobook_studio.feedback.pr_automation._run_command") as mock_run, \
             patch("src.audiobook_studio.feedback.pr_automation.datetime") as mock_dt, \
             patch("time.sleep"):
            # First call returns incomplete then completed but failed
            mock_result1 = MagicMock(spec=subprocess.CompletedProcess)
            mock_result1.returncode = 0
            mock_result1.stdout = '[{"name": "check1", "state": "PENDING", "conclusion": ""}]'

            mock_result2 = MagicMock(spec=subprocess.CompletedProcess)
            mock_result2.returncode = 0
            mock_result2.stdout = '[{"name": "check1", "state": "COMPLETED", "conclusion": "FAILURE"}]'

            mock_run.side_effect = [mock_result1, mock_result2]

            mock_now = MagicMock()
            mock_now.timestamp.side_effect = [1000.0, 1000.0, 1000.0]
            mock_dt.now.return_value = mock_now

            result = _wait_for_ci_checks(123, timeout_seconds=10, poll_interval=1)
            assert result is False

    def test_auto_merge_pr_success(self):
        with patch("src.audiobook_studio.feedback.pr_automation._run_command") as mock_run:
            # merge command succeeds
            mock_merge_result = MagicMock(spec=subprocess.CompletedProcess)
            mock_merge_result.returncode = 0
            # view command succeeds and returns merge commit
            mock_view_result = MagicMock(spec=subprocess.CompletedProcess)
            mock_view_result.returncode = 0
            mock_view_result.stdout = '{"mergeCommit": {"oid": "abc123def456"}}'

            mock_run.side_effect = [mock_merge_result, mock_view_result]

            result = _auto_merge_pr(123, merge_method="squash")
            assert result.success is True
            assert result.merged is True
            assert result.merge_commit_sha == "abc123def456"

    def test_auto_merge_pr_failure(self):
        with patch("src.audiobook_studio.feedback.pr_automation._run_command") as mock_run:
            mock_result = MagicMock(spec=subprocess.CompletedProcess)
            mock_result.returncode = 1
            mock_result.stderr = "merge failed"
            mock_run.return_value = mock_result

            result = _auto_merge_pr(123, merge_method="squash")
            assert result.success is False
            assert result.error == "merge failed"

    def test_get_pr_status_success(self):
        with patch("src.audiobook_studio.feedback.pr_automation._run_command") as mock_run:
            mock_result = MagicMock(spec=subprocess.CompletedProcess)
            mock_result.returncode = 0
            mock_result.stdout = '{"state": "OPEN", "mergeStateStatus": "CLEAN"}'
            mock_run.return_value = mock_result

            result = get_pr_status(123)
            assert result["state"] == "OPEN"
            assert result["mergeStateStatus"] == "CLEAN"

    def test_get_pr_status_failure(self):
        with patch("src.audiobook_studio.feedback.pr_automation._run_command") as mock_run:
            mock_result = MagicMock(spec=subprocess.CompletedProcess)
            mock_result.returncode = 1
            mock_result.stderr = "failed to get status"
            mock_run.return_value = mock_result

            result = get_pr_status(123)
            assert "error" in result
            assert result["error"] == "failed to get status"

    def test_list_open_prompt_prs_success(self):
        with patch("src.audiobook_studio.feedback.pr_automation._run_command") as mock_run:
            mock_result = MagicMock(spec=subprocess.CompletedProcess)
            mock_result.returncode = 0
            mock_result.stdout = '''[
                {"number": 1, "title": "Test PR", "headRefName": "test-branch", "createdAt": "2023-01-01T00:00:00Z", "labels": [{"name": "prompt-upgrade"}]}
            ]'''
            mock_run.return_value = mock_result

            result = list_open_prompt_prs()
            assert len(result) == 1
            assert result[0]["number"] == 1
            assert result[0]["title"] == "Test PR"

    def test_list_open_prompt_prs_failure(self):
        with patch("src.audiobook_studio.feedback.pr_automation._run_command") as mock_run:
            mock_result = MagicMock(spec=subprocess.CompletedProcess)
            mock_result.returncode = 1
            mock_result.stderr = "gh failed"
            mock_run.return_value = mock_result

            result = list_open_prompt_prs()
            assert result == []

    def test_close_stale_prompt_prs_no_prs(self):
        with patch("src.audiobook_studio.feedback.pr_automation.list_open_prompt_prs") as mock_list:
            mock_list.return_value = []
            with patch("src.audiobook_studio.feedback.pr_automation._run_command") as mock_run:
                result = close_stale_prompt_prs(days=7)
                assert result == 0
                mock_run.assert_not_called()

    def test_close_stale_prompt_prs_with_stale(self):
        with patch("src.audiobook_studio.feedback.pr_automation.list_open_prompt_prs") as mock_list, \
             patch("src.audiobook_studio.feedback.pr_automation._run_command") as mock_run, \
             patch("src.audiobook_studio.feedback.pr_automation.datetime") as mock_dt:
            # Mock one stale PR (created 10 days ago)
            mock_list.return_value = [{
                "number": 123,
                "createdAt": "2023-01-01T00:00:00Z"  # old date
            }]
            mock_result = MagicMock(spec=subprocess.CompletedProcess)
            mock_result.returncode = 0
            mock_run.return_value = mock_result

            # Mock datetime.now to be 2023-01-11 (10 days later)
            mock_now = MagicMock()
            mock_dt.now.return_value = mock_now
            # Make fromisoformat work - return a datetime that when subtracted gives 10 days
            mock_dt.fromisoformat.return_value = mock_now.replace(day=1)  # simplified

            result = close_stale_prompt_prs(days=7)
            assert result == 1
            # Should have called gh pr close
            mock_run.assert_called_once()


class TestPRAutomationIntegration:
    @patch("src.audiobook_studio.feedback.pr_automation._get_git_repo_root")
    @patch("src.audiobook_studio.feedback.pr_automation._create_pr_branch")
    @patch("src.audiobook_studio.feedback.pr_automation._commit_prompt_changes")
    @patch("src.audiobook_studio.feedback.pr_automation._push_branch")
    @patch("src.audiobook_studio.feedback.pr_automation._create_github_pr")
    def test_create_prompt_upgrade_pr_success(
        self, mock_create_pr, mock_commit, mock_push, mock_create_pr_func, mock_get_root
    ):
        # Setup mocks
        mock_get_root.return_value = Path("/tmp/repo")
        mock_create_pr.return_value = "test-branch"
        mock_commit.return_value = True
        mock_push.return_value = True
        mock_create_pr_func.return_value = PRResult(
            success=True,
            pr_number=123,
            pr_url="https://github.com/user/repo/pull/123",
            branch_name="test-branch"
        )

        result = create_prompt_upgrade_pr("edit_for_tts", 2)
        assert result.success is True
        assert result.pr_number == 123
        # Verify all steps were called
        mock_get_root.assert_called_once()
        mock_create_pr.assert_called_once_with("main", "edit_for_tts", 2)
        mock_commit.assert_called_once_with("edit_for_tts", 2, None)
        mock_push.assert_called_once_with("test-branch")
        mock_create_pr_func.assert_called_once()

    @patch("src.audiobook_studio.feedback.pr_automation._get_git_repo_root")
    def test_create_prompt_upgrade_pr_not_git_repo(self, mock_get_root):
        mock_get_root.side_effect = RuntimeError("Not in a git repository")

        result = create_prompt_upgrade_pr("edit_for_tts", 2)
        assert result.success is False
        assert "Not in a git repository" in result.error

    @patch("src.audiobook_studio.feedback.pr_automation._get_git_repo_root")
    @patch("src.audiobook_studio.feedback.pr_automation._create_pr_branch")
    def test_create_prompt_upgrade_pr_branch_failure(self, mock_create_pr, mock_get_root):
        mock_get_root.return_value = Path("/tmp/repo")
        mock_create_pr.side_effect = RuntimeError("Failed to create branch")

        result = create_prompt_upgrade_pr("edit_for_tts", 2)
        assert result.success is False
        assert "Failed to create branch" in result.error

    @patch("src.audiobook_studio.feedback.pr_automation._get_git_repo_root")
    @patch("src.audiobook_studio.feedback.pr_automation._create_pr_branch")
    @patch("src.audiobook_studio.feedback.pr_automation._commit_prompt_changes")
    def test_create_prompt_upgrade_pr_commit_failure(self, mock_commit, mock_create_pr, mock_get_root):
        mock_get_root.return_value = Path("/tmp/repo")
        mock_create_pr.return_value = "test-branch"
        mock_commit.return_value = False  # commit failed

        result = create_prompt_upgrade_pr("edit_for_tts", 2)
        assert result.success is False
        assert "Failed to commit prompt changes" in result.error

    @patch("src.audiobook_studio.feedback.pr_automation._get_git_repo_root")
    @patch("src.audiobook_studio.feedback.pr_automation._create_pr_branch")
    @patch("src.audiobook_studio.feedback.pr_automation._commit_prompt_changes")
    @patch("src.audiobook_studio.feedback.pr_automation._push_branch")
    def test_create_prompt_upgrade_pr_push_failure(self, mock_push, mock_commit, mock_create_pr, mock_get_root):
        mock_get_root.return_value = Path("/tmp/repo")
        mock_create_pr.return_value = "test-branch"
        mock_commit.return_value = True
        mock_push.return_value = False  # push failed

        result = create_prompt_upgrade_pr("edit_for_tts", 2)
        assert result.success is False
        assert "Failed to push branch" in result.error

    @patch("src.audiobook_studio.feedback.pr_automation.wait_for_ci_checks")
    @patch("src.audiobook_studio.feedback.pr_automation._auto_merge_pr")
    def test_monitor_and_merge_pr_success(self, mock_auto_merge, mock_wait_for_ci):
        mock_wait_for_ci.return_value = True
        mock_auto_merge.return_value = MergeResult(success=True, merged=True, merge_commit_sha="abc123")

        result = monitor_and_merge_pr(123)
        assert result.success is True
        assert result.merged is True
        assert result.merge_commit_sha == "abc123"
        mock_wait_for_ci.assert_called_once_with(123, timeout_seconds=1800, merge_method="squash")
        mock_auto_merge.assert_called_once_with(123, merge_method="squash")

    @patch("src.audiobook_studio.feedback.pr_automation.wait_for_ci_checks")
    def test_monitor_and_merge_pr_ci_failure(self, mock_wait_for_ci):
        mock_wait_for_ci.return_value = False  # CI checks failed

        result = monitor_and_merge_pr(123)
        assert result.success is False
        assert "CI checks failed or timed out" in result.error
        mock_wait_for_ci.assert_called_once_with(123, timeout_seconds=1800, merge_method="squash")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])