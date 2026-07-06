"""Tests for the multilingual_dubbing module.

Covers:
- ``EmotionType`` enum coverage
- ``CharacterVoice`` / ``EmotionMapping`` / ``Segment`` dataclasses
- ``MultilingualDubbingManager`` initialization & default config
- Character voice registry (add/get)
- Emotion mapping registry (add/get, fallback to NEUTRAL)
- Translation quality matrix (set, symmetric)
- ``translate_text_preserving_markup`` placeholder round-trip (with mocked LLM)
- ``_translate_with_llm``: success path, mock-mode path, fallback path
- ``check_emotional_continuity``: count mismatch, char mismatch, emotion
  mismatch, length ratio out-of-bounds, perfect match
- ``process_multilingual_dubbing``: full flow, fallback voice warning,
  per-segment failure resilience, continuity report toggling
- ``main()`` demo end-to-end (mocked LLM)
"""

import os
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _mock_llm_env(monkeypatch):
    monkeypatch.setenv("MOCK_LLM", "true")
    yield


# Direct imports — module doesn't depend on database at module import time.
from src.audiobook_studio.translation.multilingual_dubbing import (
    CharacterVoice,
    EmotionMapping,
    EmotionType,
    MultilingualDubbingManager,
    Segment,
    main,
)


# ── Enum & dataclass basic coverage ──────────────────────────────────────────


class TestEmotionType:
    def test_all_values(self):
        values = {e.value for e in EmotionType}
        assert values == {
            "neutral",
            "happy",
            "sad",
            "angry",
            "fearful",
            "surprised",
            "disgusted",
            "other",
        }

    def test_lookup_by_value(self):
        assert EmotionType("happy") is EmotionType.HAPPY
        assert EmotionType("neutral") is EmotionType.NEUTRAL


class TestDataclasses:
    def test_character_voice_defaults(self):
        cv = CharacterVoice("贾宝玉", "zh-CN", "voice_1")
        assert cv.style == "neutral"
        assert cv.pitch_shift == 0.0
        assert cv.speed_rate == 1.0
        assert cv.volume == 1.0

    def test_emotion_mapping_fields(self):
        em = EmotionMapping(EmotionType.HAPPY, 2.0, 1.1, 1.05, 0.8)
        assert em.emotion is EmotionType.HAPPY
        assert em.pitch_shift == 2.0
        assert em.energy == 0.8

    def test_segment_defaults(self):
        s = Segment("s1", "hello", "旁白", EmotionType.NEUTRAL, "zh-CN", 0.0, 1.0)
        assert s.voice_id is None
        assert s.pitch_shift == 0.0
        assert s.speed_rate == 1.0
        assert s.volume == 1.0

    def test_segment_str_repr_works(self):
        s = Segment("s1", "hello", "旁白", EmotionType.NEUTRAL, "zh-CN", 0.0, 1.0)
        # Field access (not direct __repr__) - sanity
        assert s.id == "s1"


# ── Manager initialization ────────────────────────────────────────────────────


class TestManagerInit:
    def test_default_emotion_mappings_all_keys(self):
        m = MultilingualDubbingManager()
        assert len(m.emotion_mappings) == 8
        for em in EmotionType:
            assert em in m.emotion_mappings
            assert isinstance(m.emotion_mappings[em], EmotionMapping)

    def test_default_emotion_values(self):
        m = MultilingualDubbingManager()
        happy = m.emotion_mappings[EmotionType.HAPPY]
        assert happy.pitch_shift == 2.0
        assert happy.speed_rate == 1.1
        assert happy.energy == 0.8

    def test_sample_character_voices(self):
        m = MultilingualDubbingManager()
        assert "旁白" in m.character_voices
        assert "主角" in m.character_voices
        assert "反派" in m.character_voices
        for char_name in ("旁白", "主角", "反派"):
            assert "zh-CN" in m.character_voices[char_name]
            assert "en-US" in m.character_voices[char_name]

    def test_translation_quality_empty_initially(self):
        m = MultilingualDubbingManager()
        assert m.translation_quality == {}


# ── Character voice registry ─────────────────────────────────────────────────


class TestCharacterVoiceRegistry:
    def test_add_new_character(self):
        m = MultilingualDubbingManager()
        cv = CharacterVoice("新角色", "fr-FR", "voice_x", "neutral")
        m.add_character_voice("新角色", "fr-FR", cv)
        assert "新角色" in m.character_voices
        assert m.character_voices["新角色"]["fr-FR"] is cv

    def test_add_existing_character_new_language(self):
        m = MultilingualDubbingManager()
        cv = CharacterVoice("旁白", "fr-FR", "voice_x", "neutral")
        m.add_character_voice("旁白", "fr-FR", cv)
        assert m.character_voices["旁白"]["fr-FR"] is cv
        # existing zh-CN unaffected
        assert "zh-CN" in m.character_voices["旁白"]

    def test_add_existing_character_existing_language_overwrites(self):
        m = MultilingualDubbingManager()
        new_cv = CharacterVoice("旁白", "zh-CN", "NEW_VOICE_ID", "friendly")
        m.add_character_voice("旁白", "zh-CN", new_cv)
        assert m.character_voices["旁白"]["zh-CN"].voice_id == "NEW_VOICE_ID"

    def test_get_character_voice_existing(self):
        m = MultilingualDubbingManager()
        v = m.get_character_voice("旁白", "zh-CN")
        assert v is not None
        assert v.name == "旁白"

    def test_get_character_voice_unknown_character(self):
        m = MultilingualDubbingManager()
        assert m.get_character_voice("路人甲", "zh-CN") is None

    def test_get_character_voice_known_char_unknown_lang(self):
        m = MultilingualDubbingManager()
        v = m.get_character_voice("旁白", "ru-RU")
        assert v is None


# ── Emotion mapping registry ──────────────────────────────────────────────────


class TestEmotionMappingRegistry:
    def test_add_new_emotion(self):
        m = MultilingualDubbingManager()
        custom = EmotionMapping(EmotionType.OTHER, 5.0, 1.5, 1.0, 0.9)
        m.add_emotion_mapping(EmotionType.OTHER, custom)
        assert m.emotion_mappings[EmotionType.OTHER] is custom

    def test_override_existing_emotion(self):
        m = MultilingualDubbingManager()
        em = m.get_emotion_mapping(EmotionType.HAPPY)
        assert em.pitch_shift == 2.0
        new_em = EmotionMapping(EmotionType.HAPPY, 10.0, 1.0, 1.0, 0.5)
        m.add_emotion_mapping(EmotionType.HAPPY, new_em)
        again = m.get_emotion_mapping(EmotionType.HAPPY)
        assert again.pitch_shift == 10.0

    def test_get_emotion_mapping_known(self):
        m = MultilingualDubbingManager()
        em = m.get_emotion_mapping(EmotionType.ANGRY)
        assert em.speed_rate == 1.2
        assert em.volume == 1.3

    def test_get_emotion_mapping_falls_back_to_neutral(self):
        """If the emotion key is unknown (via pop), lookup returns NEUTRAL."""
        m = MultilingualDubbingManager()
        m.emotion_mappings.pop(EmotionType.SAD)
        em = m.get_emotion_mapping(EmotionType.SAD)
        assert em.emotion is EmotionType.NEUTRAL
        assert em.pitch_shift == 0.0


# ── Translation quality matrix ────────────────────────────────────────────────


class TestTranslationQuality:
    def test_set_quality_symmetric(self):
        m = MultilingualDubbingManager()
        m.set_translation_quality("zh-CN", "en-US", 0.92)
        assert m.translation_quality[("zh-CN", "en-US")] == 0.92
        assert m.translation_quality[("en-US", "zh-CN")] == 0.92

    def test_set_quality_multiple_pairs(self):
        m = MultilingualDubbingManager()
        m.set_translation_quality("zh-CN", "en-US", 0.9)
        m.set_translation_quality("zh-CN", "es-ES", 0.85)
        m.set_translation_quality("en-US", "ja-JP", 0.7)
        # 双向存储: 3 unique pairs → 6 keys (symmetric reflection)
        # The last pair (en-US, ja-JP) generates both (en-US, ja-JP) and
        # (ja-JP, en-US). The earlier pairs add 2 each.
        assert m.translation_quality[("zh-CN", "en-US")] == 0.9
        assert m.translation_quality[("en-US", "zh-CN")] == 0.9
        assert m.translation_quality[("en-US", "ja-JP")] == 0.7
        assert m.translation_quality[("ja-JP", "en-US")] == 0.7
        assert len(m.translation_quality) == 6


# ── translate_text_preserving_markup ─────────────────────────────────────────


class TestTranslateTextPreservingMarkup:
    def test_character_markup_round_trip(self):
        m = MultilingualDubbingManager()
        with patch.object(m, "_translate_with_llm", side_effect=lambda t, src, tgt: t):
            out = m.translate_text_preserving_markup("[character:贾宝玉]宝玉笑道。[/character]", "zh-CN", "en-US")
        assert out == "[character:贾宝玉]宝玉笑道。[/character]"

    def test_emotion_markup_round_trip(self):
        m = MultilingualDubbingManager()
        with patch.object(m, "_translate_with_llm", side_effect=lambda t, src, tgt: t):
            out = m.translate_text_preserving_markup("(emotion:happy)今天我非常高兴。(/emotion)", "zh-CN", "en-US")
        assert out == "(emotion:happy)今天我非常高兴。(/emotion)"

    def test_mixed_markup_round_trip(self):
        m = MultilingualDubbingManager()
        text = (
            "[character:旁白](emotion:neutral)开场白。(/emotion)[/character]"
            "[character:主角](emotion:happy)我来了！(/emotion)[/character]"
        )
        with patch.object(m, "_translate_with_llm", side_effect=lambda t, src, tgt: t):
            out = m.translate_text_preserving_markup(text, "zh-CN", "en-US")
        assert out == text

    def test_no_markup_passes_text_through(self):
        m = MultilingualDubbingManager()
        with patch.object(m, "_translate_with_llm", side_effect=lambda t, src, tgt: "TRANSLATED") as mocked:
            out = m.translate_text_preserving_markup("无标记文本", "zh-CN", "en-US")
        assert out == "TRANSLATED"
        mocked.assert_called_once()


# ── _translate_with_llm ────────────────────────────────────────────────────────


class TestTranslateWithLLM:
    def test_success_path(self, monkeypatch):
        monkeypatch.setenv("MOCK_LLM", "false")

        m = MultilingualDubbingManager()
        mock_router = MagicMock()
        mock_result = MagicMock()
        mock_result.output.raw_text = "Translated text"
        mock_router.call.return_value = mock_result

        with patch("src.audiobook_studio.llm.create_router", return_value=mock_router):
            out = m._translate_with_llm("原文", "zh-CN", "en-US")
        assert out == "Translated text"

    def test_success_unknown_lang_uses_lang_code(self, monkeypatch):
        """Target language not in lang_names dict → fallback naming uses raw code."""
        monkeypatch.setenv("MOCK_LLM", "false")
        m = MultilingualDubbingManager()
        mock_router = MagicMock()
        mock_result = MagicMock()
        mock_result.output.raw_text = " "
        mock_router.call.return_value = mock_result
        with patch("src.audiobook_studio.llm.create_router", return_value=mock_router):
            out = m._translate_with_llm("x", "zh-CN", "klingon")
        # Empty translation after strip → goes to fallback prefix
        assert "klingon translation of:" in out

    def test_fallback_on_exception(self, monkeypatch):
        monkeypatch.setenv("MOCK_LLM", "false")
        m = MultilingualDubbingManager()
        with patch(
            "src.audiobook_studio.llm.create_router",
            side_effect=RuntimeError("no llm"),
        ):
            out = m._translate_with_llm("原文", "zh-CN", "en-US")
        assert "English translation of:" in out
        assert "原文" in out

    def test_fallback_unknown_target_language(self, monkeypatch):
        monkeypatch.setenv("MOCK_LLM", "false")
        m = MultilingualDubbingManager()
        with patch(
            "src.audiobook_studio.llm.create_router",
            side_effect=RuntimeError("boom"),
        ):
            out = m._translate_with_llm("test", "zh-CN", "xh-ZA")
        assert "xh-ZA translation of:" in out

    def test_empty_raw_text_triggers_fallback(self, monkeypatch):
        """If LLM returns empty raw_text, function falls back to placeholder."""
        monkeypatch.setenv("MOCK_LLM", "false")
        m = MultilingualDubbingManager()
        mock_router = MagicMock()
        mock_result = MagicMock()
        mock_result.output.raw_text = ""
        mock_router.call.return_value = mock_result
        with patch("src.audiobook_studio.llm.create_router", return_value=mock_router):
            out = m._translate_with_llm("hello", "zh-CN", "en-US")
        # Empty .strip() returns "" → falsy condition triggers fallback branch
        assert "English translation of:" in out
        assert "hello" in out


# ── check_emotional_continuity ────────────────────────────────────────────────


class TestCheckEmotionalContinuity:
    @staticmethod
    def _seg(idx, char, emotion, text, lang="zh-CN"):
        return Segment(
            id=f"seg_{idx}", text=text, character=char, emotion=emotion, language=lang, start_time=0.0, end_time=1.0
        )

    def test_count_mismatch_returns_false(self):
        m = MultilingualDubbingManager()
        ok, issues = m.check_emotional_continuity([self._seg(1, "x", EmotionType.NEUTRAL, "a")], [])
        assert ok is False
        assert "片段数量不匹配" in issues[0]

    def test_character_mismatch(self):
        m = MultilingualDubbingManager()
        orig = [self._seg(1, "甲", EmotionType.NEUTRAL, "abc")]
        trans = [self._seg(1, "乙", EmotionType.NEUTRAL, "abc")]
        ok, issues = m.check_emotional_continuity(orig, trans)
        assert ok is False
        assert any("角色不匹配" in i for i in issues)

    def test_emotion_mismatch(self):
        m = MultilingualDubbingManager()
        orig = [self._seg(1, "甲", EmotionType.HAPPY, "abc")]
        trans = [self._seg(1, "甲", EmotionType.SAD, "xyz")]
        ok, issues = m.check_emotional_continuity(orig, trans)
        assert ok is False
        assert any("情感不匹配" in i for i in issues)

    def test_text_length_too_short(self):
        m = MultilingualDubbingManager()
        orig = [self._seg(1, "甲", EmotionType.NEUTRAL, "一二三四五六七八九十一二三四五")]
        trans = [self._seg(1, "甲", EmotionType.NEUTRAL, "短")]
        ok, issues = m.check_emotional_continuity(orig, trans)
        assert ok is False
        assert any("文本长度异常变化" in i for i in issues)

    def test_text_length_too_long(self):
        m = MultilingualDubbingManager()
        long_text = "字" * 100
        orig = [self._seg(1, "甲", EmotionType.NEUTRAL, "短")]
        trans = [self._seg(1, "甲", EmotionType.NEUTRAL, long_text)]
        ok, issues = m.check_emotional_continuity(orig, trans)
        assert ok is False
        assert any("文本长度异常变化" in i for i in issues)

    def test_perfect_match_returns_true(self):
        m = MultilingualDubbingManager()
        orig = [self._seg(1, "甲", EmotionType.HAPPY, "这是一段话")]
        trans = [self._seg(1, "甲", EmotionType.HAPPY, "This is text")]
        ok, issues = m.check_emotional_continuity(orig, trans)
        assert ok is True
        assert issues == []

    def test_empty_text_skips_length_check(self):
        m = MultilingualDubbingManager()
        orig = [self._seg(1, "甲", EmotionType.NEUTRAL, "")]
        trans = [self._seg(1, "甲", EmotionType.NEUTRAL, "")]
        ok, _ = m.check_emotional_continuity(orig, trans)
        assert ok is True

    def test_multiple_segments_mixed_issues(self):
        m = MultilingualDubbingManager()
        orig = [
            self._seg(1, "甲", EmotionType.HAPPY, "good text"),
            self._seg(2, "乙", EmotionType.SAD, "second text"),
        ]
        trans = [
            self._seg(1, "甲", EmotionType.HAPPY, "good text translated"),
            self._seg(2, "X", EmotionType.ANGRY, "second text translated"),
        ]
        ok, issues = m.check_emotional_continuity(orig, trans)
        assert ok is False
        assert any("片段 2" in i and "角色不匹配" in i for i in issues)
        assert any("片段 2" in i and "情感不匹配" in i for i in issues)


# ── process_multilingual_dubbing ──────────────────────────────────────────────


class TestProcessMultilingualDubbing:
    @staticmethod
    def _seg(idx, char, emotion, text, lang="zh-CN"):
        return Segment(
            id=f"seg_{idx}", text=text, character=char, emotion=emotion, language=lang, start_time=0.0, end_time=1.0
        )

    def test_all_existing_voices_success(self):
        m = MultilingualDubbingManager()
        # Use a source text whose length is in ratio range (0.3, 3.0) to the
        # translation we inject; otherwise continuity check flags length anomaly.
        segs = [self._seg(1, "旁白", EmotionType.NEUTRAL, "中文测试文本一二三")]
        with patch.object(m, "_translate_with_llm", side_effect=lambda t, src, tgt: "Translated English text"):
            out_segs, report = m.process_multilingual_dubbing(segs, "en-US")
        assert len(out_segs) == 1
        assert report["successful_translations"] == 1
        assert report["failed_translations"] == 0
        # Continuity requires len ratio between 0.3 and 3.0
        assert report["emotional_continuity_passed"] is True, f"issues={report['continuity_issues']}"
        assert out_segs[0].voice_id == "en-US-JennyNeural"
        assert out_segs[0].id == "seg_1_en-US"

    def test_unknown_character_uses_default_voice_and_warns(self):
        m = MultilingualDubbingManager()
        segs = [self._seg(1, "路人", EmotionType.HAPPY, "[character]")]
        with patch.object(m, "_translate_with_llm", side_effect=lambda t, src, tgt: "翻译"):
            out_segs, report = m.process_multilingual_dubbing(segs, "ja-JP")
        assert len(out_segs) == 1
        assert out_segs[0].voice_id == "ja-JP-default"
        assert any("未找到角色 '路人'" in w for w in report["warnings"])
        # Emotion parameters should be applied to defaults
        assert out_segs[0].pitch_shift > 0  # happy emotion pitch up

    def test_segment_translation_failure_resilient(self):
        m = MultilingualDubbingManager()
        segs = [self._seg(1, "旁白", EmotionType.NEUTRAL, "hello")]

        call_count = [0]

        def fake_translate(text, src, tgt):
            call_count[0] += 1
            raise RuntimeError("translate boom")

        with patch.object(m, "_translate_with_llm", side_effect=fake_translate):
            out_segs, report = m.process_multilingual_dubbing(segs, "en-US")
        assert len(out_segs) == 1
        assert "_FAILED" in out_segs[0].id
        assert report["failed_translations"] == 1
        assert report["successful_translations"] == 0
        assert any("翻译失败" in w for w in report["warnings"])

    def test_voice_params_apply_emotion_mapping(self):
        m = MultilingualDubbingManager()
        segs = [self._seg(1, "主角", EmotionType.ANGRY, "content")]
        with patch.object(m, "_translate_with_llm", side_effect=lambda t, src, tgt: "T"):
            out_segs, _ = m.process_multilingual_dubbing(segs, "en-US")
        # ANGRY emotion: pitch_shift=1.0, speed_rate=1.2, volume=1.3
        cv = m.get_character_voice("主角", "en-US")
        em = m.get_emotion_mapping(EmotionType.ANGRY)
        # The segments carry the combined voice params.
        assert out_segs[0].pitch_shift == cv.pitch_shift + em.pitch_shift == 1.0
        assert out_segs[0].speed_rate == cv.speed_rate * em.speed_rate == 1.2

    def test_empty_segment_lists(self):
        m = MultilingualDubbingManager()
        out_segs, report = m.process_multilingual_dubbing([], "en-US")
        assert out_segs == []
        assert report["successful_translations"] == 0
        assert report["emotional_continuity_passed"] is True  # 0 == 0

    def test_continuity_check_failed_propagated_in_report(self):
        """When translation length differs massively, continuity fails and
        report contains the issue list."""
        m = MultilingualDubbingManager()
        long_text = "字" * 100
        segs = [self._seg(1, "旁白", EmotionType.NEUTRAL, long_text)]
        with patch.object(m, "_translate_with_llm", side_effect=lambda t, src, tgt: "短"):
            out_segs, report = m.process_multilingual_dubbing(segs, "en-US")
        # Successful translation, but continuity check sees length mismatch
        assert report["successful_translations"] == 1
        # The translated segment keeps character, but text is "短" while orig is 100 chars
        # ratio = 1/100 = 0.01 < 0.3 → length issue
        assert report["emotional_continuity_passed"] is False
        assert len(report["continuity_issues"]) > 0


# ── main() ────────────────────────────────────────────────────────────────────


class TestMain:
    def test_main_runs_end_to_end(self):
        """main() builds four segments and processes them via en-US then es-ES."""
        with patch(
            "src.audiobook_studio.translation.multilingual_dubbing.MultilingualDubbingManager._translate_with_llm",
            side_effect=lambda t, src, tgt: f"[{tgt}]{t}",
        ):
            # Should not raise
            main()

    def test_main_handles_translation_exception(self):
        # The LLM fallback returns placeholder text — main() should complete.
        with patch(
            "src.audiobook_studio.translation.multilingual_dubbing.MultilingualDubbingManager._translate_with_llm",
            side_effect=RuntimeError("boom"),
        ):
            main()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--cov=src/audiobook_studio/translation/multilingual_dubbing.py"])
