"""Tests for analyzer module."""

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from src.audiobook_studio.analyzer import (
    LLM_ANALYSIS_PROMPT,
    SCENE_TAG_TO_FILENAME,
    SceneTagAnalysisResult,
    SceneTagInfo,
    SceneTagMapper,
    analyze_scene_tags,
    create_scene_tag_mapper,
    ensure_scene_tags_in_output,
    normalize_scene_tag,
    resolve_scene_tags_to_files,
    validate_scene_tags,
)


class TestNormalizeSceneTag:
    """Tests for normalize_scene_tag function."""

    def test_basic_tag(self):
        assert normalize_scene_tag("雷雨夜") == "雷雨夜"

    def test_tag_with_brackets(self):
        assert normalize_scene_tag("[雷雨夜]") == "雷雨夜"
        assert normalize_scene_tag("【雷雨夜】") == "雷雨夜"

    def test_tag_with_whitespace(self):
        assert normalize_scene_tag("  雷雨夜  ") == "雷雨夜"
        assert normalize_scene_tag("\t\n雷雨夜\r") == "雷雨夜"

    def test_complex_tag(self):
        assert normalize_scene_tag("  [繁华街道]  ") == "繁华街道"


class TestValidateSceneTags:
    """Tests for validate_scene_tags function."""

    def test_none_input_returns_defaults(self):
        result = validate_scene_tags(None)
        assert len(result) == 5
        assert "雷雨夜" in result

    def test_empty_list_returns_defaults(self):
        result = validate_scene_tags([])
        assert len(result) == 5

    def test_valid_tags_pass_through(self):
        tags = ["雷雨夜", "繁华街道", "酒馆喧闹", "静谧书房", "森林鸟鸣"]
        result = validate_scene_tags(tags)
        assert result == tags

    def test_duplicate_tags_removed(self):
        tags = ["雷雨夜", "雷雨夜", "繁华街道"]
        result = validate_scene_tags(tags, min_tags=2, max_tags=10)
        assert result.count("雷雨夜") == 1

    def test_non_string_tags_ignored(self):
        tags = ["雷雨夜", 123, "繁华街道", None]
        result = validate_scene_tags(tags, min_tags=2, max_tags=10)
        assert "雷雨夜" in result
        assert "繁华街道" in result
        assert len(result) == 2

    def test_empty_string_tags_ignored(self):
        tags = ["雷雨夜", "", "  ", "繁华街道"]
        result = validate_scene_tags(tags, min_tags=2, max_tags=10)
        assert result == ["雷雨夜", "繁华街道"]

    def test_truncation_when_over_max(self):
        tags = ["雷雨夜", "繁华街道", "酒馆喧闹", "静谧书房", "森林鸟鸣", "海浪拍岸", "马车颠簸"]
        result = validate_scene_tags(tags, min_tags=3, max_tags=5)
        assert len(result) == 5

    def test_padding_when_under_min(self):
        tags = ["雷雨夜", "繁华街道"]
        result = validate_scene_tags(tags, min_tags=5, max_tags=10, default_tags=["A", "B", "C", "D", "E"])
        assert len(result) == 5
        assert "雷雨夜" in result
        assert "繁华街道" in result

    def test_custom_defaults_used(self):
        tags = []
        custom = ["自定义1", "自定义2", "自定义3"]
        result = validate_scene_tags(tags, min_tags=3, max_tags=10, default_tags=custom)
        assert result == custom


class TestEnsureSceneTagsInOutput:
    """Tests for ensure_scene_tags_in_output function."""

    def test_missing_scene_tags_field(self):
        output = {"book_meta": {}, "character_voice_map": []}
        result = ensure_scene_tags_in_output(output)
        assert "scene_tags" in result
        assert len(result["scene_tags"]) == 5

    def test_existing_scene_tags_validated(self):
        output = {"scene_tags": ["雷雨夜", "繁华街道"]}
        result = ensure_scene_tags_in_output(output, min_tags=3, max_tags=10)
        assert len(result["scene_tags"]) == 3
        assert "雷雨夜" in result["scene_tags"]

    def test_modifies_in_place(self):
        output = {"scene_tags": ["雷雨夜"]}
        result = ensure_scene_tags_in_output(output)
        assert result is output


class TestSceneTagMapper:
    """Tests for SceneTagMapper class."""

    def test_init_default_path(self):
        mapper = SceneTagMapper()
        assert mapper.effects_library_path == Path("assets/effects")

    def test_init_custom_path(self):
        mapper = SceneTagMapper(effects_library_path=Path("/custom/path"))
        assert mapper.effects_library_path == Path("/custom/path")

    def test_init_custom_mapping(self):
        custom = {"测试": "test.mp3"}
        mapper = SceneTagMapper(custom_mapping=custom)
        assert "测试" in mapper.mapping
        assert mapper.mapping["测试"] == "test.mp3"

    def test_resolve_known_tags(self):
        mapper = SceneTagMapper()
        with patch.object(Path, "exists", return_value=True):
            result = mapper.resolve(["雷雨夜", "繁华街道"])
            assert len(result) == 2
            assert result[0].name == "thunder_rain.mp3"
            assert result[1].name == "busy_street.mp3"

    def test_resolve_unknown_tag_fallback(self):
        mapper = SceneTagMapper()
        with patch.object(Path, "exists", return_value=True):
            result = mapper.resolve(["未知标签"])
            assert len(result) == 1
            assert result[0].name == "未知标签.mp3"

    def test_resolve_strips_brackets(self):
        mapper = SceneTagMapper()
        with patch.object(Path, "exists", return_value=True):
            result = mapper.resolve(["[雷雨夜]", "【繁华街道】"])
            assert result[0].name == "thunder_rain.mp3"
            assert result[1].name == "busy_street.mp3"

    def test_resolve_logs_warning_for_missing(self, caplog):
        caplog.set_level(logging.WARNING)
        mapper = SceneTagMapper()
        with patch.object(Path, "exists", return_value=False):
            mapper.resolve(["雷雨夜"])
            assert "音效文件不存在" in caplog.text

    def test_resolve_with_validation_require_exists(self):
        mapper = SceneTagMapper()
        with patch.object(Path, "exists", return_value=False):
            with pytest.raises(FileNotFoundError):
                mapper.resolve_with_validation(["雷雨夜"], require_exists=True)

    def test_resolve_with_validation_false_returns_empty(self):
        mapper = SceneTagMapper()
        with patch.object(Path, "exists", return_value=False):
            result = mapper.resolve_with_validation(["雷雨夜"], require_exists=False)
            assert result == []

    def test_get_available_tags(self):
        mapper = SceneTagMapper()
        tags = mapper.get_available_tags()
        assert "雷雨夜" in tags
        assert len(tags) == len(SCENE_TAG_TO_FILENAME)

    def test_add_mapping(self):
        mapper = SceneTagMapper()
        mapper.add_mapping("新标签", "new.mp3")
        assert mapper.mapping["新标签"] == "new.mp3"


class TestSceneTagInfo:
    """Tests for SceneTagInfo model."""

    def test_create_basic(self):
        info = SceneTagInfo(tag="雷雨夜", normalized_tag="雷雨夜")
        assert info.tag == "雷雨夜"
        assert info.normalized_tag == "雷雨夜"
        assert info.file_path is None
        assert info.file_exists is False
        assert info.mapped_filename is None


class TestSceneTagAnalysisResult:
    """Tests for SceneTagAnalysisResult model."""

    def test_from_tags_basic(self):
        mapper = SceneTagMapper()
        with patch.object(Path, "exists", return_value=True):
            result = SceneTagAnalysisResult.from_tags(["雷雨夜", "繁华街道"], mapper)
            assert result.total_tags == 2
            assert result.available_count == 2
            assert result.missing_count == 0
            assert len(result.scene_tags) == 2

    def test_from_tags_mixed_exists(self):
        mapper = SceneTagMapper()
        with patch.object(Path, "exists", side_effect=[True, False]):
            result = SceneTagAnalysisResult.from_tags(["雷雨夜", "不存在"], mapper)
            assert result.total_tags == 2
            assert result.available_count == 1
            assert result.missing_count == 1
            assert "不存在" in result.missing_tags


class TestConvenienceFunctions:
    """Tests for convenience functions."""

    def test_create_scene_tag_mapper(self):
        mapper = create_scene_tag_mapper(Path("/custom"))
        assert isinstance(mapper, SceneTagMapper)
        assert mapper.effects_library_path == Path("/custom")

    def test_analyze_scene_tags(self):
        with patch.object(Path, "exists", return_value=True):
            result = analyze_scene_tags(["雷雨夜"])
            assert isinstance(result, SceneTagAnalysisResult)
            assert result.total_tags == 1

    def test_resolve_scene_tags_to_files(self):
        with patch.object(Path, "exists", return_value=True):
            result = resolve_scene_tags_to_files(["雷雨夜"])
            assert len(result) == 1
            assert isinstance(result[0], Path)


class TestLLMAnalysisPrompt:
    """Tests for LLM_ANALYSIS_PROMPT schema."""

    def test_schema_structure(self):
        assert LLM_ANALYSIS_PROMPT["type"] == "object"
        assert "book_meta" in LLM_ANALYSIS_PROMPT["properties"]
        assert "scene_tags" in LLM_ANALYSIS_PROMPT["properties"]

    def test_scene_tags_constraints(self):
        scene_tags = LLM_ANALYSIS_PROMPT["properties"]["scene_tags"]
        assert scene_tags["minItems"] == 5
        assert scene_tags["maxItems"] == 15
        assert scene_tags["type"] == "array"

    def test_required_fields(self):
        required = LLM_ANALYSIS_PROMPT["required"]
        assert "book_meta" in required
        assert "character_voice_map" in required
        assert "emotion_snapshots" in required
        assert "scene_tags" in required


class TestSceneTagToFilenameMapping:
    """Tests for SCENE_TAG_TO_FILENAME mapping."""

    def test_all_mappings_are_strings(self):
        for tag, filename in SCENE_TAG_TO_FILENAME.items():
            assert isinstance(tag, str)
            assert isinstance(filename, str)
            assert filename.endswith(".mp3")

    def test_key_tags_present(self):
        expected = [
            "雷雨夜",
            "繁华街道",
            "酒馆喧闹",
            "静谧书房",
            "战场硝烟",
            "森林鸟鸣",
            "海浪拍岸",
        ]
        for tag in expected:
            assert tag in SCENE_TAG_TO_FILENAME
