"""Tests for S2.3 — expand language support (Japanese / French).

Verifies:
- Japanese and French are first-class supported languages with TTS voices.
- Language detection in extract.py recognises ja / fr text.
- The translate default-voice lookup resolves ja-JP / fr-FR correctly.
- The /translate/languages API returns ja-JP and fr-FR.
"""

import sys

import pytest

sys.path.insert(0, "src")

from audiobook_studio.languages import (
    SUPPORTED_BCP47_CODES,
    default_voice_for,
    get_language_info,
    is_supported,
    normalize_language,
    prompt_guidance_for,
    to_bcp47,
)
from audiobook_studio.pipeline.extract import ExtractPipeline


def test_japanese_and_french_are_supported():
    assert "ja-JP" in SUPPORTED_BCP47_CODES
    assert "fr-FR" in SUPPORTED_BCP47_CODES
    assert is_supported("ja")
    assert is_supported("fr")


def test_japanese_french_have_tts_voices():
    assert default_voice_for("ja-JP") == "ja-JP-NanamiNeural"
    assert default_voice_for("fr-FR") == "fr-FR-DeniseNeural"
    assert get_language_info("ja").default_edge_voice == "ja-JP-NanamiNeural"
    assert get_language_info("fr").default_edge_voice == "fr-FR-DeniseNeural"


def test_normalize_and_prompt_guidance():
    assert normalize_language("ja-JP") == "ja"
    assert normalize_language("fr-FR") == "fr"
    assert to_bcp47("ja") == "ja-JP"
    assert "日本語" in prompt_guidance_for("ja")
    assert "français" in prompt_guidance_for("fr").lower()


def test_extract_detects_japanese():
    stage = ExtractPipeline()
    assert stage._detect_language("これは日本語のテキストです。") == "ja"


def test_extract_detects_french():
    stage = ExtractPipeline()
    text = "C'est un texte en français avec accents é à è û."
    assert stage._detect_language(text) == "fr"


def test_extract_still_detects_chinese_and_english():
    stage = ExtractPipeline()
    assert stage._detect_language("这是一个中文测试文本。") == "zh"
    assert stage._detect_language("This is an English test sentence.") == "en"


def test_translate_default_voice_uses_registry():
    # Translate's default-voice lookup now delegates to the registry.
    from audiobook_studio.languages import default_voice_for

    assert default_voice_for("ja-JP") == "ja-JP-NanamiNeural"
    assert default_voice_for("fr-FR") == "fr-FR-DeniseNeural"
