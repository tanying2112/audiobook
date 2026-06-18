"""Tests for feedback/prompt_upgrader module."""

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from src.audiobook_studio.feedback.prompt_upgrader import (
    PATTERN_PROMPT_FIXES,
    _load_current_prompt,
    _apply_pattern_fixes,
    _write_new_version,
    upgrade_prompt,
    batch_upgrade,
    _map_pattern_to_stage,
)


class TestPatternPromptFixes:
    """Tests for PATTERN_PROMPT_FIXES mapping."""

    def test_all_patterns_have_fixes(self):
        # Actual patterns defined in the source
        expected_patterns = [
            "dialogue_attribution", "emotion_too_mild", "emotion_too_strong",
            "emotion_wrong", "speaker_wrong", "pause_missing", "pause_too_long",
            "sfx_missing", "text_colloquial", "text_formal",
            "prosody_robotic", "prosody_flat",
        ]
        for pattern in expected_patterns:
            assert pattern in PATTERN_PROMPT_FIXES
            assert len(PATTERN_PROMPT_FIXES[pattern]) > 10

        # Verify total count
        assert len(PATTERN_PROMPT_FIXES) == 12


class TestLoadCurrentPrompt:
    """Tests for _load_current_prompt function."""

    @patch("pathlib.Path.exists")
    def test_no_prompt_dir(self, mock_exists):
        mock_exists.return_value = False

        content, version = _load_current_prompt("nonexistent_stage")
        assert content is None
        assert version == 0

    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.glob")
    def test_no_version_files(self, mock_glob, mock_exists):
        mock_exists.return_value = True
        mock_glob.return_value = []

        content, version = _load_current_prompt("empty_stage")
        assert content is None
        assert version == 0

    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.glob")
    def test_load_highest_version(self, mock_glob, mock_exists):
        mock_exists.return_value = True
        mock_v1 = MagicMock()
        mock_v1.stem = "v1"
        mock_v1.read_text.return_value = "v1 content"
        mock_v2 = MagicMock()
        mock_v2.stem = "v2"
        mock_v2.read_text.return_value = "v2 content"
        mock_v3 = MagicMock()
        mock_v3.stem = "v3"
        mock_v3.read_text.return_value = "v3 content"
        mock_glob.return_value = [mock_v1, mock_v2, mock_v3]

        content, version = _load_current_prompt("test_stage")
        assert content == "v3 content"
        assert version == 3


class TestApplyPatternFixes:
    """Tests for _apply_pattern_fixes function."""

    def test_apply_new_fixes(self):
        content = "Original prompt content"
        patterns = ["dialogue_attribution", "emotion_too_mild"]
        updated, applied = _apply_pattern_fixes(content, patterns, "edit_for_tts")

        assert "dialogue_attribution" in applied
        assert "emotion_too_mild" in applied
        assert len(applied) == 2

    def test_skip_existing_fixes(self):
        # Content already contains the fix text
        fix_text = PATTERN_PROMPT_FIXES["dialogue_attribution"][:50]
        content = f"Prompt with {fix_text} already present"
        patterns = ["dialogue_attribution"]
        updated, applied = _apply_pattern_fixes(content, patterns, "edit_for_tts")

        assert "dialogue_attribution" not in applied
        assert len(applied) == 0

    def test_unknown_pattern(self):
        content = "Original prompt"
        patterns = ["unknown_pattern"]
        updated, applied = _apply_pattern_fixes(content, patterns, "edit_for_tts")

        assert len(applied) == 0

    def test_multiple_patterns_some_existing(self):
        fix1 = PATTERN_PROMPT_FIXES["dialogue_attribution"][:50]
        content = f"Prompt with {fix1}"
        patterns = ["dialogue_attribution", "emotion_too_mild"]
        updated, applied = _apply_pattern_fixes(content, patterns, "edit_for_tts")

        assert "dialogue_attribution" not in applied
        assert "emotion_too_mild" in applied
        assert len(applied) == 1


class TestWriteNewVersion:
    """Tests for _write_new_version function."""

    @patch("pathlib.Path.mkdir")
    @patch("pathlib.Path.write_text")
    @patch("builtins.open", new_callable=MagicMock)
    def test_write_new_version(self, mock_open, mock_write_text, mock_mkdir):
        mock_file = MagicMock()
        mock_open.return_value.__enter__.return_value = mock_file

        content = "New prompt content"
        version = 1
        changes = ["Fix 1", "Fix 2"]

        result = _write_new_version("edit_for_tts", content, version, changes)

        assert result.name == "v2.j2"
        mock_write_text.assert_called_once_with(content, encoding="utf-8")
        mock_file.write.assert_called()


class TestUpgradePrompt:
    """Tests for upgrade_prompt function."""

    @patch("src.audiobook_studio.feedback.prompt_upgrader._load_current_prompt")
    def test_no_current_prompt(self, mock_load):
        mock_load.return_value = (None, 0)

        result = upgrade_prompt("edit_for_tts", ["dialogue_attribution"])
        assert result is None

    @patch("src.audiobook_studio.feedback.prompt_upgrader._write_new_version")
    @patch("src.audiobook_studio.feedback.prompt_upgrader._load_current_prompt")
    @patch("src.audiobook_studio.feedback.prompt_upgrader._apply_pattern_fixes")
    def test_upgrade_with_patterns(self, mock_apply, mock_load, mock_write):
        mock_load.return_value = ("Original prompt", 1)
        mock_apply.return_value = ("Updated prompt", ["dialogue_attribution"])
        mock_write.return_value = Path("prompts/edit_for_tts/v2.j2")

        result = upgrade_prompt("edit_for_tts", ["dialogue_attribution"])

        assert result == Path("prompts/edit_for_tts/v2.j2")
        mock_write.assert_called_once()

    @patch("src.audiobook_studio.feedback.prompt_upgrader._load_current_prompt")
    @patch("src.audiobook_studio.feedback.prompt_upgrader._apply_pattern_fixes")
    def test_no_upgrade_needed(self, mock_apply, mock_load):
        mock_load.return_value = ("Original prompt", 1)
        mock_apply.return_value = ("Original prompt", [])

        result = upgrade_prompt("edit_for_tts", ["unknown_pattern"])

        assert result is None

    @patch("src.audiobook_studio.feedback.prompt_upgrader._write_new_version")
    @patch("src.audiobook_studio.feedback.prompt_upgrader._load_current_prompt")
    @patch("src.audiobook_studio.feedback.prompt_upgrader._apply_pattern_fixes")
    def test_upgrade_with_additional_fixes(self, mock_apply, mock_load, mock_write):
        mock_load.return_value = ("Original prompt", 1)
        mock_apply.return_value = ("Original prompt", [])
        mock_write.return_value = Path("prompts/edit_for_tts/v2.j2")

        result = upgrade_prompt("edit_for_tts", [], additional_fixes=["Custom fix instruction"])

        assert result == Path("prompts/edit_for_tts/v2.j2")


class TestBatchUpgrade:
    """Tests for batch_upgrade function."""

    @patch("src.audiobook_studio.feedback.prompt_upgrader.upgrade_prompt")
    def test_batch_upgrade(self, mock_upgrade):
        mock_upgrade.side_effect = [
            Path("prompts/edit_for_tts/v2.j2"),
            Path("prompts/quality_judge/v2.j2"),
            None,  # No upgrade for annotate
        ]

        # Create mock analysis result
        mock_analysis = MagicMock()
        mock_analysis.top_patterns = [
            ("dialogue_attribution", 5),
            ("emotion_too_mild", 4),
            ("clipping", 3),
            ("rare_pattern", 1),  # Below threshold
        ]

        results = batch_upgrade(mock_analysis, min_pattern_threshold=2)

        assert "edit_for_tts" in results
        assert "quality_judge" in results
        assert mock_upgrade.call_count == 2  # Only 2 stages had patterns above threshold


class TestMapPatternToStage:
    """Tests for _map_pattern_to_stage function."""

    def test_edit_patterns(self):
        edit_patterns = [
            "dialogue_attribution", "emotion_too_mild", "emotion_too_strong",
            "emotion_wrong", "speaker_wrong", "pause_missing", "pause_too_long",
            "sfx_missing", "sfx_wrong", "text_colloquial", "text_formal",
        ]
        for pattern in edit_patterns:
            assert _map_pattern_to_stage(pattern) == "edit_for_tts"

    def test_quality_patterns(self):
        quality_patterns = [
            "clipping", "silence", "low_volume", "duration_mismatch",
            "prosody_robotic", "prosody_flat",
        ]
        for pattern in quality_patterns:
            assert _map_pattern_to_stage(pattern) == "quality_judge"

    def test_structure_patterns(self):
        structure_patterns = [
            "chapter_split_wrong", "character_missing", "summary_incomplete",
        ]
        for pattern in structure_patterns:
            assert _map_pattern_to_stage(pattern) == "analyze_structure"

    def test_annotation_patterns(self):
        annotation_patterns = [
            "emotion_too_mild", "emotion_too_strong", "emotion_wrong",
        ]
        for pattern in annotation_patterns:
            # These map to both edit_for_tts and annotate_paragraph
            # The function returns the first match which is edit_for_tts
            assert _map_pattern_to_stage(pattern) == "edit_for_tts"

    def test_unknown_pattern(self):
        assert _map_pattern_to_stage("unknown_pattern") is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])