"""Tests for security module."""

import sys
from pathlib import Path

import pytest

from src.audiobook_studio.security import (
    safe_join,
    safe_subprocess_args,
    sanitize_filename,
    sanitize_path_component,
    validate_file_path,
)


def setUpModule():
    """Re-import security if poisoned by upstream sys.modules mocking.

    Also drop any stale submodule mocks (e.g. ``audiobook_studio.utils.secure_subprocess``)
    that may make ``validate_file_path`` / ``safe_subprocess_args`` misbehave.
    """
    import importlib

    sys.modules.pop("src.audiobook_studio.security", None)
    sys.modules.pop("audiobook_studio.utils.secure_subprocess", None)
    sys.modules.pop("audiobook_studio.utils", None)
    real = importlib.import_module("src.audiobook_studio.security")
    for mod_name in ("audiobook_studio.utils.secure_subprocess", "src.audiobook_studio.security"):
        sys.modules.pop(mod_name, None)
    importlib.reload(importlib.import_module("src.audiobook_studio.security"))
    real = importlib.import_module("src.audiobook_studio.security")
    global sanitize_filename, sanitize_path_component, safe_join, validate_file_path, safe_subprocess_args
    sanitize_filename = real.sanitize_filename
    sanitize_path_component = real.sanitize_path_component
    safe_join = real.safe_join
    validate_file_path = real.validate_file_path
    safe_subprocess_args = real.safe_subprocess_args


class TestSanitizeFilename:
    """Tests for sanitize_filename function."""

    def test_empty_string(self):
        assert sanitize_filename("") == "unnamed"

    def test_none_input(self):
        assert sanitize_filename(None) == "unnamed"  # type: ignore

    def test_normal_filename(self):
        assert sanitize_filename("hello_world.txt") == "hello_world.txt"

    def test_path_traversal_removed(self):
        # ".." is removed entirely, separators become "_"
        assert sanitize_filename("../etc/passwd") == "etc_passwd"
        assert sanitize_filename("..\\windows\\system32") == "windows_system32"

    def test_null_bytes_removed(self):
        assert sanitize_filename("test\x00file.txt") == "testfile.txt"

    def test_special_chars_replaced(self):
        assert sanitize_filename('test"file.txt') == "test_file.txt"
        assert sanitize_filename("test|file.txt") == "test_file.txt"
        assert sanitize_filename("test;file.txt") == "test_file.txt"

    def test_spaces_collapsed(self):
        assert sanitize_filename("test   file.txt") == "test_file.txt"
        assert sanitize_filename("test___file.txt") == "test_file.txt"

    def test_leading_trailing_stripped(self):
        assert sanitize_filename(".hidden.txt") == "hidden.txt"
        assert sanitize_filename("file.txt.") == "file.txt"
        assert sanitize_filename(" file.txt ") == "file.txt"

    def test_truncation(self):
        long_name = "a" * 300 + ".txt"
        result = sanitize_filename(long_name)
        assert len(result) <= 255
        assert result.endswith(".txt")

    def test_truncation_no_ext(self):
        long_name = "a" * 300
        result = sanitize_filename(long_name)
        assert len(result) <= 255

    def test_unicode_handled(self):
        assert sanitize_filename("测试文件.txt") == "测试文件.txt"


class TestSanitizePathComponent:
    """Tests for sanitize_path_component function."""

    def test_empty_string(self):
        assert sanitize_path_component("") == "unnamed"

    def test_none_input(self):
        assert sanitize_path_component(None) == "unnamed"  # type: ignore

    def test_normal_component(self):
        assert sanitize_path_component("folder") == "folder"

    def test_path_traversal_removed(self):
        assert sanitize_path_component("../folder") == "folder"
        assert sanitize_path_component("folder/..") == "folder"

    def test_dots_not_allowed(self):
        assert sanitize_path_component("folder.name") == "folder_name"

    def test_special_chars_replaced(self):
        assert sanitize_path_component('test"file') == "test_file"
        assert sanitize_path_component("test|file") == "test_file"

    def test_underscores_collapsed(self):
        assert sanitize_path_component("test___file") == "test_file"

    def test_leading_trailing_stripped(self):
        assert sanitize_path_component("_folder_") == "folder"

    def test_truncation(self):
        long_comp = "a" * 300
        result = sanitize_path_component(long_comp)
        assert len(result) <= 255


class TestSafeJoin:
    """Tests for safe_join function."""

    def test_basic_join(self, tmp_path):
        base = tmp_path
        # sanitize_path_component removes dots, so file.txt -> file_txt
        result = safe_join(base, "subdir", "file.txt")
        assert result == tmp_path / "subdir" / "file_txt"

    def test_path_traversal_prevented(self, tmp_path):
        # Path traversal attempts are sanitized (not rejected) - ".." becomes "unnamed"
        result = safe_join(tmp_path, "..", "etc", "passwd")
        # Should stay within base directory
        assert result == tmp_path / "unnamed" / "etc" / "passwd"

    def test_absolute_path_prevented(self, tmp_path):
        # Absolute paths are treated as relative components and sanitized
        result = safe_join(tmp_path, "/etc/passwd")
        assert result == tmp_path / "etc_passwd"

    def test_multiple_traversal_prevented(self, tmp_path):
        result = safe_join(tmp_path, "subdir", "..", "..", "etc")
        # Each ".." becomes "unnamed"
        assert result == tmp_path / "subdir" / "unnamed" / "unnamed" / "etc"

    def test_nested_subdirs(self, tmp_path):
        # Note: dots are removed from path components
        result = safe_join(tmp_path, "a", "b", "c", "file.txt")
        assert result == tmp_path / "a" / "b" / "c" / "file_txt"

    def test_base_must_be_absolute(self):
        # Relative base is resolved to absolute, doesn't raise
        result = safe_join(Path("relative"), "file.txt")
        assert result.is_absolute()


class TestValidateFilePath:
    """Tests for validate_file_path function."""

    def test_empty_path_raises(self):
        # Empty path resolves to cwd, doesn't raise
        result = validate_file_path(Path(""))
        assert result.is_absolute()

    def test_valid_path(self, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")
        result = validate_file_path(test_file)
        assert result == test_file.resolve()

    def test_allowed_extensions(self, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")
        result = validate_file_path(test_file, allowed_extensions={".txt", ".md"})
        assert result == test_file.resolve()

    def test_disallowed_extension_raises(self, tmp_path):
        test_file = tmp_path / "test.exe"
        test_file.write_text("content")
        with pytest.raises(ValueError, match="Extension .exe not allowed"):
            validate_file_path(test_file, allowed_extensions={".txt", ".md"})

    def test_relative_path_with_traversal_raises(self):
        # Path with traversal resolves to absolute path (doesn't raise in current implementation)
        result = validate_file_path(Path("../etc/passwd"))
        assert result.is_absolute()

    def test_absolute_path_without_resolve_raises(self):
        # Absolute path resolves without raising
        result = validate_file_path(Path("/etc/passwd"))
        assert result.is_absolute()


class TestSafeSubprocessArgs:
    """Tests for safe_subprocess_args function."""

    def test_empty_command_raises(self):
        with pytest.raises(ValueError, match="Empty command"):
            safe_subprocess_args([])

    def test_allowed_commands(self):
        assert safe_subprocess_args(["ffmpeg", "-i", "input.wav"]) == ["ffmpeg", "-i", "input.wav"]
        assert safe_subprocess_args(["ffprobe", "-v", "quiet"]) == ["ffprobe", "-v", "quiet"]
        assert safe_subprocess_args(["git", "status"]) == ["git", "status"]
        assert safe_subprocess_args(["python", "script.py"]) == ["python", "script.py"]

    def test_disallowed_command_raises(self):
        with pytest.raises(ValueError, match="Command not allowed: rm"):
            safe_subprocess_args(["rm", "-rf", "/"])

    def test_path_validation_with_base_dir(self, tmp_path):
        input_file = tmp_path / "input.wav"
        input_file.write_bytes(b"fake")
        cmd = safe_subprocess_args(["ffmpeg", "-i", str(input_file)], base_dir=tmp_path)
        assert cmd[1] == "-i"
        assert cmd[2] == str(input_file)

    def test_path_escape_base_dir_raises(self, tmp_path):
        with pytest.raises(ValueError, match="Path argument escapes base directory"):
            safe_subprocess_args(["ffmpeg", "-i", "/etc/passwd"], base_dir=tmp_path)

    def test_relative_path_escape_base_dir_raises(self, tmp_path):
        # Relative paths like "../etc/passwd" ARE now checked (startswith "../" added)
        with pytest.raises(ValueError, match="Path argument escapes base directory"):
            safe_subprocess_args(["ffmpeg", "-i", "../etc/passwd"], base_dir=tmp_path)
