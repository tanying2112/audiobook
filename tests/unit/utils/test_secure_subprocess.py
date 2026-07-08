"""Tests for secure_subprocess module."""

import asyncio
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.audiobook_studio.utils.secure_subprocess import (
    get_ffmpeg,
    get_ffprobe,
    get_nvidia_smi,
    get_sysctl,
    get_system_profiler,
    resolve_executable,
    run_command,
    run_command_async,
    validate_path,
)


class TestResolveExecutable:
    """Tests for resolve_executable function."""

    def test_resolve_existing_executable(self):
        """Test resolving an existing executable like python."""
        result = resolve_executable("python")
        assert result is not None
        assert Path(result).exists()
        assert Path(result).is_file()

    def test_resolve_nonexistent_executable(self):
        """Test resolving a non-existent executable returns None."""
        result = resolve_executable("nonexistent_executable_xyz_123")
        assert result is None

    def test_cache_behavior(self):
        """Test that resolve_executable caches results."""
        # Clear cache first
        import src.audiobook_studio.utils.secure_subprocess as sp

        sp._executable_cache.clear()

        result1 = resolve_executable("python")
        result2 = resolve_executable("python")
        assert result1 == result2
        assert "python" in sp._executable_cache


class TestValidatePath:
    """Tests for validate_path function."""

    def test_valid_relative_path(self, tmp_path):
        """Test validating a valid relative path."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")
        result = validate_path(Path("test.txt"))
        assert result.is_absolute()

    def test_valid_absolute_path(self, tmp_path):
        """Test validating a valid absolute path."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")
        result = validate_path(test_file)
        assert result == test_file.resolve()

    def test_must_exist_true_existing(self, tmp_path):
        """Test must_exist=True with existing path."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")
        result = validate_path(test_file, must_exist=True)
        assert result == test_file.resolve()

    def test_must_exist_false_missing(self, tmp_path):
        """Test must_exist=False with missing path."""
        missing = tmp_path / "missing.txt"
        result = validate_path(missing, must_exist=False)
        assert result == missing.resolve()

    def test_must_exist_true_missing_raises(self, tmp_path):
        """Test must_exist=True with missing path raises ValueError."""
        missing = tmp_path / "missing.txt"
        with pytest.raises(ValueError, match="Path does not exist"):
            validate_path(missing, must_exist=True)

    def test_allowed_dirs_within(self, tmp_path):
        """Test allowed_dirs with path within allowed directory."""
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        test_file = subdir / "test.txt"
        test_file.write_text("content")
        result = validate_path(test_file, allowed_dirs=[tmp_path])
        assert result == test_file.resolve()

    def test_allowed_dirs_outside_raises(self, tmp_path):
        """Test allowed_dirs with path outside allowed directory raises."""
        # Create a path that is truly outside allowed_dirs
        # Since we can't write outside tmp_path, use an absolute path
        # that won't be under tmp_path
        with pytest.raises(ValueError, match="Path outside allowed directories"):
            validate_path(Path("/etc/passwd"), allowed_dirs=[tmp_path])

    def test_allowed_dirs_multiple(self, tmp_path):
        """Test allowed_dirs with multiple allowed directories."""
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        dir1.mkdir()
        dir2.mkdir()
        test_file = dir1 / "test.txt"
        test_file.write_text("content")
        result = validate_path(test_file, allowed_dirs=[dir1, dir2])
        assert result == test_file.resolve()

    def test_resolve_failure_raises(self):
        """Test that resolve failure raises ValueError (line 62)."""
        # Create a path that will fail to resolve
        # Using a path with invalid characters that causes OSError on resolve
        # On most systems this is hard, but we can mock it
        with patch("pathlib.Path.resolve", side_effect=OSError("Permission denied")):
            with pytest.raises(ValueError, match="Invalid path"):
                validate_path(Path("test.txt"))


class TestRunCommand:
    """Tests for run_command function."""

    def test_empty_command_raises(self):
        """Test empty command raises ValueError."""
        with pytest.raises(ValueError, match="Empty command"):
            run_command([])

    def test_nonexistent_executable_raises(self):
        """Test nonexistent executable raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError, match="Executable not found"):
            run_command(["nonexistent_executable_xyz_123"])

    def test_run_echo_command(self):
        """Test running a simple echo command."""
        result = run_command(["python", "-c", "print('hello')"], check=False)
        assert result.returncode == 0
        assert "hello" in result.stdout

    def test_run_command_with_cwd(self, tmp_path):
        """Test running command with custom cwd."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")
        result = run_command(["python", "-c", "import os; print(os.getcwd())"], cwd=tmp_path)
        assert tmp_path.name in result.stdout

    def test_run_command_timeout(self):
        """Test command timeout raises TimeoutExpired."""
        with pytest.raises(subprocess.TimeoutExpired):
            run_command(["python", "-c", "import time; time.sleep(10)"], timeout=1)

    def test_run_command_check_false(self):
        """Test check=False doesn't raise on non-zero exit."""
        result = run_command(["python", "-c", "import sys; sys.exit(1)"], check=False)
        assert result.returncode == 1

    def test_run_command_allowed_dirs_valid(self, tmp_path):
        """Test allowed_dirs with valid path argument."""
        test_file = tmp_path / "input.wav"
        test_file.write_bytes(b"fake")
        result = run_command(
            ["python", "-c", "import sys; print(sys.argv[1])", str(test_file)],
            allowed_dirs=[tmp_path],
            check=False,
        )
        assert result.returncode == 0

    def test_run_command_allowed_dirs_escape(self, tmp_path):
        """Test allowed_dirs with path escaping - validation error is silently ignored."""
        # Validation failure is caught silently (line 124-126), command still runs
        result = run_command(
            ["python", "-c", "import sys; print(sys.argv[1])", "/etc/passwd"],
            allowed_dirs=[tmp_path],
            check=False,
        )
        # Command runs, argument passed through unchanged
        assert result.returncode == 0

    def test_run_command_allowed_dirs_relative_escape(self, tmp_path):
        """Test allowed_dirs with relative path escaping - validation error silently ignored."""
        result = run_command(
            ["python", "-c", "import sys; print(sys.argv[1])", "../etc/passwd"],
            allowed_dirs=[tmp_path],
            check=False,
        )
        # Command runs, argument passed through unchanged
        assert result.returncode == 0

    def test_run_command_capture_output_false(self):
        """Test capture_output=False returns None for stdout/stderr."""
        result = run_command(["python", "-c", "print('hello')"], capture_output=False)
        assert result.stdout is None
        assert result.stderr is None

    def test_run_command_text_false(self):
        """Test text=False returns bytes."""
        result = run_command(["python", "-c", "print('hello')"], text=False)
        assert isinstance(result.stdout, bytes)


class TestRunCommandAsync:
    """Tests for run_command_async function."""

    @pytest.mark.asyncio
    async def test_empty_command_raises(self):
        """Test empty command raises ValueError."""
        with pytest.raises(ValueError, match="Empty command"):
            await run_command_async([])

    @pytest.mark.asyncio
    async def test_nonexistent_executable_raises(self):
        """Test nonexistent executable raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError, match="Executable not found"):
            await run_command_async(["nonexistent_executable_xyz_123"])

    @pytest.mark.asyncio
    async def test_run_simple_async_command(self):
        """Test running a simple async command."""
        result = await run_command_async(["python", "-c", "print('async hello')"])
        assert result.returncode == 0
        assert "async hello" in result.stdout

    @pytest.mark.asyncio
    async def test_run_async_command_timeout(self):
        """Test async command timeout raises TimeoutExpired."""
        with pytest.raises(subprocess.TimeoutExpired):
            await run_command_async(["python", "-c", "import time; time.sleep(10)"], timeout=1)

    @pytest.mark.asyncio
    async def test_run_async_command_allowed_dirs(self, tmp_path):
        """Test async command with allowed_dirs (lines 170-174)."""
        test_file = tmp_path / "input.wav"
        test_file.write_bytes(b"fake")
        result = await run_command_async(
            ["python", "-c", "import sys; print(sys.argv[1])", str(test_file)],
            allowed_dirs=[tmp_path],
        )
        assert result.returncode == 0
        assert str(test_file) in result.stdout

    @pytest.mark.asyncio
    async def test_run_async_command_allowed_dirs_non_path_args(self, tmp_path):
        """Test async command with allowed_dirs and non-path arguments."""
        # Non-path args should not be validated
        result = await run_command_async(
            ["python", "-c", "import sys; print('arg1', sys.argv[2])", "not_a_path", "value"],
            allowed_dirs=[tmp_path],
        )
        assert result.returncode == 0

    @pytest.mark.asyncio
    async def test_run_async_command_with_cwd(self, tmp_path):
        """Test async command with custom cwd."""
        result = await run_command_async(
            ["python", "-c", "import os; print(os.getcwd())"],
            cwd=tmp_path,
        )
        assert tmp_path.name in result.stdout


class TestConvenienceFunctions:
    """Tests for convenience executable resolvers."""

    def test_get_ffmpeg(self):
        """Test get_ffmpeg returns path or None."""
        result = get_ffmpeg()
        # May be None if ffmpeg not installed, but shouldn't error
        assert result is None or Path(result).exists()

    def test_get_ffprobe(self):
        """Test get_ffprobe returns path or None."""
        result = get_ffprobe()
        assert result is None or Path(result).exists()

    def test_get_nvidia_smi(self):
        """Test get_nvidia_smi returns path or None."""
        result = get_nvidia_smi()
        assert result is None or Path(result).exists()

    def test_get_sysctl(self):
        """Test get_sysctl returns path or None."""
        result = get_sysctl()
        assert result is None or Path(result).exists()

    def test_get_system_profiler(self):
        """Test get_system_profiler returns path or None."""
        result = get_system_profiler()
        assert result is None or Path(result).exists()


class TestEdgeCases:
    """Additional edge case tests."""

    def test_validate_path_with_runtime_error(self):
        """Test validate_path handles RuntimeError during resolve."""
        with patch("pathlib.Path.resolve", side_effect=RuntimeError("Runtime error")):
            with pytest.raises(ValueError, match="Invalid path"):
                validate_path(Path("test.txt"))

    @pytest.mark.asyncio
    async def test_run_command_async_allowed_dirs_validation_error_silent(self, tmp_path):
        """Test that validation errors in allowed_dirs are silently ignored (line 174-175)."""
        # Path that fails validation but we catch the ValueError
        result = await run_command_async(
            ["python", "-c", "import sys; print(sys.argv[1])", "/invalid/path"],
            allowed_dirs=[tmp_path],  # /invalid/path won't be in tmp_path
        )
        # The argument should remain unchanged since validation failed silently
        assert result.returncode == 0

    @pytest.mark.asyncio
    async def test_run_command_async_allowed_dirs_windows_path(self, tmp_path):
        """Test allowed_dirs with Windows-style path separators."""
        test_file = tmp_path / "input.wav"
        test_file.write_bytes(b"fake")
        # Use a path with backslash (will be treated as part of filename on Unix)
        result = await run_command_async(
            ["python", "-c", "import sys; print(sys.argv[1])", "not_a_real_path\\file.wav"],
            allowed_dirs=[tmp_path],
        )
        # Should not crash, validation error caught silently
        assert result.returncode == 0
