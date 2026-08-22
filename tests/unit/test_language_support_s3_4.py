"""Tests for S3.4 — cross-language (zh/en/ja/ko) end-to-end support.

验收(免费资源可达成部分):
- 中文/英文/日文/韩文 均为一等公民,且各有 TTS 音色 + 免费 API 推荐
- 自动翻译:requires_translation 在同源时跳过、异源时触发
- 跨语言 SOP 规则迁移:结构保留,language/prompt_guidance 适配目标语言
- GET /api/v1/languages 暴露每语言 TTS/free-API 配置
"""

import sys

import pytest

sys.path.insert(0, "src")

from audiobook_studio.api import languages as languages_api
from audiobook_studio.languages import (
    SUPPORTED_ISO_CODES,
    free_api_for,
    is_supported,
    migrate_sop_rules,
    normalize_language,
    requires_translation,
    tts_engine_for,
)


@pytest.mark.parametrize("lang", ["zh", "en", "ja", "ko"])
def test_core_four_languages_are_first_class(lang):
    assert lang in SUPPORTED_ISO_CODES
    assert is_supported(lang)


def test_core_four_have_tts_voice_and_free_api():
    for lang in ["zh", "en", "ja", "ko"]:
        # TTS engine family is configured per language
        assert tts_engine_for(lang) in {"edge", "kokoro"}
        # A free-resource LLM family is recommended
        assert free_api_for(lang) in {"qwen", "llama", "ollama"}


def test_ko_uses_qwen_free_api():
    # Qwen has strong Korean/CJK coverage
    assert free_api_for("ko") == "qwen"
    assert free_api_for("ja") == "qwen"
    assert free_api_for("zh") == "qwen"
    assert free_api_for("en") == "llama"


def test_requires_translation_skips_same_language():
    assert requires_translation("zh", "zh-CN") is False
    assert requires_translation("ja-JP", "ja") is False
    assert requires_translation("zh", "en") is True
    assert requires_translation("ko", "ja") is True


def test_migrate_sop_rules_adapts_language_and_guidance():
    rules = [
        {
            "name": "emotion-rich",
            "language": "zh",
            "prompt_guidance": "请使用简体中文输出。",
            "weight": 1.0,
        }
    ]
    migrated = migrate_sop_rules("zh", "ja", rules)
    assert len(migrated) == 1
    m = migrated[0]
    # structure preserved
    assert m["name"] == "emotion-rich"
    assert m["weight"] == 1.0
    # language metadata adapted
    assert m["language"] == "ja"
    assert m["source_language"] == "zh"
    assert m["target_language"] == "ja"
    # guidance swapped to target language
    assert "日本語" in m["prompt_guidance"]


def test_migrate_sop_rules_empty_is_safe():
    assert migrate_sop_rules("en", "ko", []) == []


def test_languages_endpoint_exposes_core_four():
    resp = languages_api.list_languages()
    langs = {l["iso639_1"]: l for l in resp["languages"]}
    for code in ["zh", "en", "ja", "ko"]:
        assert code in langs
        assert langs[code]["default_edge_voice"]
        assert langs[code]["tts_engine"]
        assert langs[code]["free_api"]


def test_language_endpoint_falls_back_to_en_for_unknown():
    # Unknown codes normalise to "en" (the registry's safe fallback).
    resp = languages_api.get_language("xx")
    assert resp["iso639_1"] == "en"


def test_translate_required_endpoint():
    resp = languages_api.translate_required(source="zh", target="en")
    assert resp["requires_translation"] is True
    resp2 = languages_api.translate_required(source="ja-JP", target="ja")
    assert resp2["requires_translation"] is False


def test_sop_migrate_endpoint():
    resp = languages_api.migrate_sop(
        source_lang="en",
        target_lang="ko",
        rules=[{"name": "tone", "prompt_guidance": "Please respond in English."}],
    )
    assert resp["target_language"] == "ko"
    assert resp["migrated_count"] == 1
    assert "한국어" in resp["rules"][0]["prompt_guidance"]
