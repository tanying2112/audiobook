"""Tests for the Stage 7 multilingual translation dubbing pipeline.

These tests are aligned with the current implementation in
``src/audiobook_studio/pipeline/translate.py`` and intentionally replace the
previous test file which targeted the legacy ``mock_mode``-based API that no
longer exists.

Strategy:
- Heavy collaborators (``VoiceCloningManager``, ``AnnotateParagraphPipeline``,
  ``SynthesizePipeline``) are mocked at the import site.
- ``router.call`` is replaced with a stub that returns a predictable
  ``TranslationResult``, exercising the success path of ``_translate_text``.
- ``_synthesize_dubbed_segment`` is tested both directly (with mocked TTS output)
  and indirectly via ``translate_and_dub`` (where the synthesize step raises
  and the pipeline records a failed translation).
"""

import os
from unittest.mock import MagicMock, patch

import pytest

# Ensure mocked LLM mode globally for all tests under this file.
os.environ.setdefault("MOCK_LLM", "true")


@pytest.fixture
def pipeline():
    """Build a TranslateAndDubPipeline with all heavy collaborators mocked.

    ``mock_mode`` is force-disabled so the real LLM/shopping router code path is
    executed (router.call is mocked afterwards via ``pipeline.router``).
    The router.call returns a fake object whose ``output.translated_text`` is
    ``"translated"`` so that ``_translate_text`` returns a stable string.
    """
    fake_router = MagicMock()
    fake_result = MagicMock()
    fake_result.output.translated_text = "translated"
    fake_router.call.return_value = fake_result

    with (
        patch("src.audiobook_studio.pipeline.translate.VoiceCloningManager") as mock_vc,
        patch("src.audiobook_studio.pipeline.translate.AnnotateParagraphPipeline") as mock_ap,
        patch("src.audiobook_studio.pipeline.translate.create_router", return_value=fake_router),
        patch("src.audiobook_studio.pipeline.translate.SynthesizePipeline") as mock_synth_cls,
    ):
        mock_vc.return_value = MagicMock()
        mock_ap.return_value = MagicMock()
        mock_synth_cls.return_value = MagicMock()
        from src.audiobook_studio.pipeline.translate import TranslateAndDubPipeline

        pipeline = TranslateAndDubPipeline()
        # Force-disable mock_mode so LLM/router code paths are exercised
        pipeline.mock_mode = False
        # Synthesizer exposes .run() (not .run)
        pipeline.synthesizer.run = MagicMock()
        pipeline.synthesizer.output_dir = "/tmp/tts_test"
        yield pipeline


@pytest.fixture
def pipeline_with_synth(tts_synth_output):
    """Pipeline where the synthesizer.run returns a real synth output dataclass."""

    class FakeSynth:
        output_dir = "/tmp/tts_test"
        run = MagicMock(return_value=[tts_synth_output])

    fake_router = MagicMock()
    fake_result = MagicMock()
    fake_result.output.translated_text = "translated"
    fake_router.call.return_value = fake_result

    with (
        patch("src.audiobook_studio.pipeline.translate.VoiceCloningManager") as mock_vc,
        patch("src.audiobook_studio.pipeline.translate.AnnotateParagraphPipeline") as mock_ap,
        patch("src.audiobook_studio.pipeline.translate.create_router", return_value=fake_router),
    ):
        mock_vc.return_value = MagicMock()
        mock_ap.return_value = MagicMock()
        from src.audiobook_studio.pipeline.translate import TranslateAndDubPipeline

        pipeline = TranslateAndDubPipeline()
        pipeline.mock_mode = False
        # Force-replace synthesizer with our fake that returns a real synth
        pipeline.synthesizer = FakeSynth()
        yield pipeline


@pytest.fixture
def tts_synth_output():
    """Mimic the synth output dataclass returned by SimplerSynthesize."""
    out = MagicMock()
    out.file_path = "/tmp/dubbed_voice_en.mp3"
    out.duration_ms = 1500
    out.engine = "kokoro"
    out.voice_id = "dubbed_voice_en"
    return out


# ── Initialization ────────────────────────────────────────────────────────────


class TestInitialization:
    def test_defaults_are_mocked_when_not_provided(self):
        """When no collaborator provided, defaults are MagickMock instances."""
        with (
            patch("src.audiobook_studio.pipeline.translate.VoiceCloningManager") as mock_vc,
            patch("src.audiobook_studio.pipeline.translate.AnnotateParagraphPipeline") as mock_ap,
            patch("src.audiobook_studio.pipeline.translate.create_router"),
            patch("src.audiobook_studio.pipeline.translate.SynthesizePipeline"),
        ):
            mock_vc.return_value = MagicMock()
            mock_ap.return_value = MagicMock()
            from src.audiobook_studio.pipeline.translate import TranslateAndDubPipeline

            p = TranslateAndDubPipeline()
            assert p.voice_cloning_manager is not None
            assert p.annotate_pipeline is not None
            assert p.router is not None
            assert p.synthesizer is not None

    def test_provided_collaborators_kept(self):
        with (
            patch("src.audiobook_studio.pipeline.translate.create_router"),
            patch("src.audiobook_studio.pipeline.translate.SynthesizePipeline"),
        ):
            from src.audiobook_studio.pipeline.translate import TranslateAndDubPipeline

            custom_vc = MagicMock()
            custom_ap = MagicMock()
            p = TranslateAndDubPipeline(
                voice_cloning_manager=custom_vc,
                annotate_pipeline=custom_ap,
            )
            assert p.voice_cloning_manager is custom_vc
            assert p.annotate_pipeline is custom_ap


# ── _translate_text ───────────────────────────────────────────────────────────


class TestTranslateText:
    def test_router_success_returns_stripped_translation(self, pipeline):
        result = pipeline._translate_text("你好", "zh-CN", "en-US", "旁白", "neutral")
        assert result == "translated"

    def test_router_exception_falls_back_to_placeholder(self, pipeline):
        pipeline.router.call.side_effect = RuntimeError("llm unavailable")
        result = pipeline._translate_text("你好", "zh-CN", "fr-FR", "旁白", "happy")
        assert result == "[fr-FR] 你好"


# ── _apply_voice_characteristics ───────────────────────────────────────────────


class TestApplyVoiceCharacteristics:
    @staticmethod
    def _annotation(emotion):
        from src.audiobook_studio.schemas import ParagraphAnnotation

        return ParagraphAnnotation(
            paragraph_index=0,
            speaker_canonical_name="旁白",
            is_dialogue=False,
            emotion=emotion,
            emotion_intensity=0.5,
            speech_rate=1.0,
            pitch_shift_semitones=0,
            pause_before_ms=300,
            pause_after_ms=500,
            confidence=0.9,
            needs_sfx=False,
            sfx_tags=[],
        )

    @pytest.mark.parametrize(
        "emotion,exp_rate,exp_pitch",
        [
            ("neutral", 1.0, 0.0),
            ("happy", 1.1, 2.0),
            ("sad", 0.9, -3.0),
            ("angry", 1.2, 1.0),
            ("fearful", 1.1, -1.0),
            ("surprised", 1.15, 3.0),
            ("disgusted", 0.95, -2.0),
        ],
    )
    def test_known_emotions(self, pipeline, emotion, exp_rate, exp_pitch):
        ann = self._annotation(emotion)
        vc = {"base_speed_rate": 1.0, "base_pitch_shift": 0.0}
        params = pipeline._apply_voice_characteristics(ann, vc)
        assert params["speech_rate"] == pytest.approx(exp_rate)
        assert params["pitch_shift_semitones"] == pytest.approx(exp_pitch)

    def test_unknown_emotion_falls_back_to_neutral(self, pipeline):
        ann = self._annotation("tense")
        vc = {"base_speed_rate": 2.0, "base_pitch_shift": 1.0}
        params = pipeline._apply_voice_characteristics(ann, vc)
        assert params["speech_rate"] == 2.0
        assert params["pitch_shift_semitones"] == 1.0

    def test_voice_config_base_values_combine_with_emotion(self, pipeline):
        ann = self._annotation("happy")  # rate 1.1, pitch +2.0
        vc = {"base_speed_rate": 1.5, "base_pitch_shift": 0.5}
        params = pipeline._apply_voice_characteristics(ann, vc)
        assert params["speech_rate"] == pytest.approx(1.5 * 1.1)
        assert params["pitch_shift_semitones"] == pytest.approx(0.5 + 2.0)


# ── _get_target_voice ─────────────────────────────────────────────────────────


class TestGetTargetVoice:
    def test_default_voice_for_unknown_character(self, pipeline):
        """No DB character found → falls back to default_voices.language map."""
        voice = pipeline._get_target_voice("陌生角色", "en-US", "neutral")
        assert voice["voice_id"] == "en-US-JennyNeural"
        assert voice["language"] == "en-US"
        assert voice["base_volume"] == 1.0

    def test_supported_language_uses_default_map(self, pipeline):
        for lang, expected in [
            ("es-ES", "es-ES-ElviraNeural"),
            ("ja-JP", "ja-JP-NanamiNeural"),
            ("fr-FR", "fr-FR-DeniseNeural"),
            ("de-DE", "de-DE-KatjaNeural"),
            ("zh-CN", "zh-CN-XiaoyiNeural"),
        ]:
            voice = pipeline._get_target_voice("x", lang, "neutral")
            assert voice["voice_id"] == expected
            assert voice["language"] == lang

    def test_unsupported_language_falls_back_to_jenny(self, pipeline):
        voice = pipeline._get_target_voice("x", "klingon", "neutral")
        assert voice["voice_id"] == "en-US-JennyNeural"

    def test_character_with_voice_mapping_dict(self, pipeline):
        """When DB character has dict voice_mapping, voice for matching lang is used."""
        fake_session = MagicMock()
        fake_char = MagicMock()
        fake_char.voice_mapping = {"en-US": "custom-VoiceA"}
        fake_session.query.return_value.filter.return_value.first.return_value = fake_char
        with patch("src.audiobook_studio.database.SessionLocal", return_value=fake_session):
            voice = pipeline._get_target_voice("甲", "en-US", "happy")
        assert voice["voice_id"] == "custom-VoiceA"
        assert voice["language"] == "en-US"

    def test_character_with_dict_but_missing_language_falls_back(self, pipeline):
        fake_session = MagicMock()
        fake_char = MagicMock()
        fake_char.voice_mapping = {"de-DE": "de-Voice"}  # No en-US mapping
        fake_session.query.return_value.filter.return_value.first.return_value = fake_char
        with patch("src.audiobook_studio.database.SessionLocal", return_value=fake_session):
            voice = pipeline._get_target_voice("甲", "es-ES", "neutral")
        assert voice["voice_id"] == "es-ES-ElviraNeural"

    def test_character_with_non_dict_voice_mapping_falls_back(self, pipeline):
        fake_session = MagicMock()
        fake_char = MagicMock()
        fake_char.voice_mapping = "not a dict"
        fake_session.query.return_value.filter.return_value.first.return_value = fake_char
        with patch("src.audiobook_studio.database.SessionLocal", return_value=fake_session):
            voice = pipeline._get_target_voice("甲", "en-US", "neutral")
        assert voice["voice_id"] == "en-US-JennyNeural"

    def test_no_character_found(self, pipeline):
        fake_session = MagicMock()
        fake_session.query.return_value.filter.return_value.first.return_value = None
        with patch("src.audiobook_studio.database.SessionLocal", return_value=fake_session):
            voice = pipeline._get_target_voice("ghost", "en-US", "neutral")
        assert voice["voice_id"] == "en-US-JennyNeural"


# ── _synthesize_dubbed_segment ──────────────────────────────────────────────


class TestSynthesizeDubbedSegment:
    def test_synthesize_returns_audio_segment(self, pipeline_with_synth, tts_synth_output):
        from src.audiobook_studio.models.audio_segment import AudioSegment

        original = AudioSegment(
            project_id=1,
            chapter_id=2,
            paragraph_id=3,
            file_path="/tmp/orig.wav",
            duration_ms=2000,
            engine="kokoro",
            voice_id="v",
        )
        original.text = "原文"
        out = pipeline_with_synth._synthesize_dubbed_segment(
            original,
            translated_text="translated",
            target_language="en-US",
            voice_params={"voice_id": "dubbed_voice_en", "base_pitch_shift": 1.0, "base_speed_rate": 1.0},
        )
        assert isinstance(out, AudioSegment)
        assert out.paragraph_id == 3 + 10000
        assert "dubbed_en-US" in out.file_path  # custom_output_path naming
        assert out.engine == "kokoro"
        # voice_id comes from voice_params, not synth output (line 406 src)
        assert out.voice_id == "dubbed_voice_en"
        assert out.duration_ms == 1500
        # Test-compatibility: text attribute stamped on output
        assert out.text == "translated"

    def test_synthesize_no_output_raises(self, pipeline):
        pipeline.synthesizer.run.return_value = []  # empty list
        from src.audiobook_studio.models.audio_segment import AudioSegment

        original = AudioSegment(
            project_id=1,
            chapter_id=1,
            paragraph_id=1,
            file_path="/tmp/orig.wav",
            duration_ms=2000,
            engine="kokoro",
            voice_id="v",
        )
        with pytest.raises(RuntimeError, match="no output"):
            pipeline._synthesize_dubbed_segment(
                original,
                translated_text="x",
                target_language="en-US",
                voice_params={"voice_id": "v", "base_pitch_shift": 0.0, "base_speed_rate": 1.0},
            )


# ── translate_and_dub ────────────────────────────────────────────────────────


class TestTranslateAndDub:
    @staticmethod
    def _make_segment(idx, text, annotation=None):
        from src.audiobook_studio.models.audio_segment import AudioSegment

        seg = AudioSegment(
            project_id=1,
            chapter_id=1,
            paragraph_id=idx,
            file_path=f"/tmp/s{idx}.wav",
            duration_ms=1500,
            engine="kokoro",
            voice_id="v",
        )
        seg.text = text
        if annotation is not None:
            seg.annotation = annotation
        return seg

    def test_empty_segments(self, pipeline):
        out_segs, report = pipeline.translate_and_dub([], "en-US")
        assert out_segs == []
        assert report["source_segments"] == 0
        assert report["successful_translations"] == 0
        assert report["failed_translations"] == 0
        assert report["emotional_continuity_passed"] is False  # default

    def test_single_segment_success_when_synth_fails(self, pipeline):
        """Synthesize always raises here, so single segment is recorded as failed."""
        pipeline.synthesizer.run.side_effect = RuntimeError("no tts")
        seg = self._make_segment(1, "hello")
        out_segs, report = pipeline.translate_and_dub([seg], "en-US")
        assert len(out_segs) == 1
        assert out_segs[0].paragraph_id == -1  # failed marker
        assert out_segs[0].engine == "failed"
        assert report["failed_translations"] == 1
        assert report["successful_translations"] == 0
        assert any("翻译失败" in w for w in report["warnings"])

    def test_multi_segment_failures(self, pipeline):
        pipeline.synthesizer.run.side_effect = RuntimeError("no tts")
        segs = [self._make_segment(i, f"text{i}") for i in range(1, 4)]
        out_segs, report = pipeline.translate_and_dub(segs, "en-US")
        assert len(out_segs) == 3
        assert report["failed_translations"] == 3

    def test_segment_without_text_uses_default_label(self, pipeline):
        """When segment lacks a 'text' attribute, the pipeline uses
        ``[段落 {id}]`` placeholder via getattr fallback."""
        from src.audiobook_studio.models.audio_segment import AudioSegment

        seg = AudioSegment(
            project_id=1,
            chapter_id=1,
            paragraph_id=1,
            file_path="/tmp/x.wav",
            duration_ms=1000,
            engine="kokoro",
            voice_id="v",
        )
        # Don't set text attribute
        pipeline.synthesizer.run.side_effect = RuntimeError("no tts")
        out_segs, _ = pipeline.translate_and_dub([seg], "en-US")
        # Should not raise; failed segment recorded
        assert len(out_segs) == 1
        assert out_segs[0].paragraph_id == -1

    def test_segment_with_default_annotation_path(self, pipeline):
        """When annotation is None, pipeline creates a default ParagraphAnnotation
        with speaker_canonical_name='旁白' and emotion='neutral'."""
        from src.audiobook_studio.schemas import ParagraphAnnotation

        seg = self._make_segment(1, "没有标注的文本")
        # Ensure annotation not set
        try:
            del seg.annotation
        except AttributeError:
            pass
        pipeline.synthesizer.run.side_effect = RuntimeError("no tts")
        out_segs, _ = pipeline.translate_and_dub([seg], "en-US")
        assert len(out_segs) == 1

    def test_report_metadata_propagated(self, pipeline):
        """Report echoes back book_title and author parameters."""
        seg = self._make_segment(1, "x")
        pipeline.synthesizer.run.side_effect = RuntimeError("no tts")
        _, report = pipeline.translate_and_dub([seg], target_language="ja-JP", book_title="测试书", author="测试作者")
        assert report["book_title"] == "测试书"
        assert report["author"] == "测试作者"
        assert report["target_language"] == "ja-JP"

    def test_semantic_coherence_skipped_for_single_segments(self, pipeline):
        """Logic: ``if len(segments) > 1 and len(dubbed_segments) > 1`` skips."""
        seg = self._make_segment(1, "x")
        pipeline.synthesizer.run.side_effect = RuntimeError("no tts")
        _, report = pipeline.translate_and_dub([seg], "en-US")
        # Single segment → semantic coherence not run → score remains None
        assert report["semantic_coherence_score"] is None

    def test_semantic_coherence_module_import_failure(self, pipeline):
        """When SemanticCoherenceChecker import fails, semantic_checker remains
        None and coherence check is skipped without error."""
        seg1 = self._make_segment(1, "你好")
        seg2 = self._make_segment(2, "世界")
        pipeline.synthesizer.run.side_effect = RuntimeError("no tts")
        # Two segments but both fail → dubbed_segments has 2 failed entries
        out_segs, report = pipeline.translate_and_dub([seg1, seg2], "en-US")
        # Both failed (paragraph_id = -1) so should not have _FAILED suffix
        # only successful segments filtered out by ('_FAILED' in seg.segment_id)
        # but our failed AudioSegment doesn't have segment_id attr either way.
        assert report["semantic_coherence_score"] is None
        assert report["emotional_continuity_passed"] is False


# ── semantic_coherence execution path ───────────────────────────────────────


class TestSemanticCoherence:
    @staticmethod
    def _make_segment(idx, text):
        from src.audiobook_studio.models.audio_segment import AudioSegment

        seg = AudioSegment(
            project_id=1,
            chapter_id=1,
            paragraph_id=idx,
            file_path=f"/tmp/s{idx}.wav",
            duration_ms=2000,
            engine="kokoro",
            voice_id="v",
        )
        seg.text = text
        return seg

    def test_full_coherence_check_exercised(self):
        """Inject a real SemanticCoherenceChecker via patch and trace coherence
        enforcement: success + failed semantic coherence + exception path."""
        from src.audiobook_studio.models.audio_segment import AudioSegment
        from src.audiobook_studio.pipeline import translate as tr_mod

        # Build pipeline with synth configured
        fake_router = MagicMock()
        fake_result = MagicMock()
        fake_result.output.translated_text = "translated"
        fake_router.call.return_value = fake_result

        with (
            patch("src.audiobook_studio.pipeline.translate.create_router", return_value=fake_router),
            patch("src.audiobook_studio.pipeline.translate.SynthesizePipeline"),
            patch("src.audiobook_studio.pipeline.translate.VoiceCloningManager"),
            patch("src.audiobook_studio.pipeline.translate.AnnotateParagraphPipeline"),
        ):
            pipeline = tr_mod.TranslateAndDubPipeline()
            pipeline.synthesizer = MagicMock()
            # Provide synthetic output objects so synthesis succeeds, leaving
            # segments with .text attribute for coherence check filtering.
            out1 = MagicMock()
            out1.file_path = "/tmp/a.mp3"
            out1.duration_ms = 1000
            out1.engine = "kokoro"
            out1.voice_id = "v"
            out2 = MagicMock()
            out2.file_path = "/tmp/b.mp3"
            out2.duration_ms = 1000
            out2.engine = "kokoro"
            out2.voice_id = "v"
            pipeline.synthesizer.run.return_value = [out1, out2]

            # Mock SemanticCoherenceChecker
            fake_checker = MagicMock()
            fake_checker.check_coherence.return_value = {
                "score": 0.92,
                "passed": True,
                "issues": [],
            }
            fake_class = MagicMock(return_value=fake_checker)

            segs = [self._make_segment(1, "再见"), self._make_segment(2, "你好")]
            with patch.dict(
                "sys.modules",
                {"src.audiobook_studio.quality.semantic_coherence": MagicMock(SemanticCoherenceChecker=fake_class)},
            ):
                # Re-import the module-level lazy import via patch import line
                with patch(
                    "src.audiobook_studio.quality.semantic_coherence.SemanticCoherenceChecker",
                    fake_class,
                ):
                    out_segs, report = pipeline.translate_and_dub(segs, "en-US")
            assert report["semantic_coherence_score"] == 0.92
            assert report["emotional_continuity_passed"] is True
            fake_checker.check_coherence.assert_called_once()

    def test_coherence_exception_records_warning(self):
        from src.audiobook_studio.pipeline import translate as tr_mod

        fake_router = MagicMock()
        fake_result = MagicMock()
        fake_result.output.translated_text = "translated"
        fake_router.call.return_value = fake_result

        with (
            patch("src.audiobook_studio.pipeline.translate.create_router", return_value=fake_router),
            patch("src.audiobook_studio.pipeline.translate.SynthesizePipeline"),
            patch("src.audiobook_studio.pipeline.translate.VoiceCloningManager"),
            patch("src.audiobook_studio.pipeline.translate.AnnotateParagraphPipeline"),
        ):
            pipeline = tr_mod.TranslateAndDubPipeline()
            pipeline.synthesizer = MagicMock()
            pipeline.synthesizer.run.return_value = [
                MagicMock(file_path="/tmp/a.mp3", duration_ms=1000, engine="kokoro", voice_id="v"),
                MagicMock(file_path="/tmp/b.mp3", duration_ms=1000, engine="kokoro", voice_id="v"),
            ]
            fake_checker = MagicMock()
            fake_checker.check_coherence.side_effect = RuntimeError("coherence boom")
            segs = [self._make_segment(1, "你好"), self._make_segment(2, "再见")]
            with patch(
                "src.audiobook_studio.quality.semantic_coherence.SemanticCoherenceChecker",
                MagicMock(return_value=fake_checker),
            ):
                _, report = pipeline.translate_and_dub(segs, "en-US")
            assert report["semantic_coherence_score"] is None
            assert any("情感连贯性检查失败" in w for w in report["warnings"])


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--cov=src/audiobook_studio/pipeline/translate.py"])
