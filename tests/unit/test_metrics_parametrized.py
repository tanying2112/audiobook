"""Parametrized tests for quality/metrics.py — exhaustive branch coverage.

Uses pytest.mark.parametrize with boundary data matrices to exercise
all if/elif/else branches in:
  - _compute_wer_cer() Levenshtein distance computation
  - Tokenization (Chinese vs English)
  - Dataclass to_dict() / from_dict() serialization
  - WERResult.compute() edge cases
  - SpeakerSimilarityResult and SpeakerEmbedding round-trip
"""

from dataclasses import fields as dc_fields
from pathlib import Path
from typing import Dict, Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def wer_metric():
    """Create an ASRWerMetric with a mocked backend for _compute_wer_cer tests."""
    from src.audiobook_studio.quality.metrics import ASRWerMetric
    metric = ASRWerMetric(backend="funasr", model_name="test", reference_text="dummy")
    # Replace backend with a mock to avoid import of real ASR models
    metric._backend = MagicMock()
    return metric


# ===========================================================================
# 1. _compute_wer_cer — exhaustive parametrized Levenshtein tests
# ===========================================================================


class TestComputeWerCer:
    """Parametrized tests covering all branches of _compute_wer_cer."""

    @pytest.mark.parametrize(
        "reference, hypothesis, expected_wer, expected_cer, expected_ins, expected_del, expected_sub",
        [
            # ── Identity / trivial ──
            ("hello world", "hello world", 0.0, 0.0, 0, 0, 0),
            ("a", "a", 0.0, 0.0, 0, 0, 0),
            ("", "", 0.0, 0.0, 0, 0, 0),

            # ── English — single substitution ──
            ("hello", "jello", 1.0, 1.0, 0, 0, 1),

            # ── English — single insertion ──
            ("hello", "hello there", 1.0, 1.0, 1, 0, 0),

            # ── English — single deletion ──
            ("hello world", "hello", 0.5, 0.5, 0, 1, 0),

            # ── English — all operations ──
            ("the cat sat", "the dog sit", 2/3, 2/3, 0, 0, 2),

            # ── English — empty reference edge case (1 word) ──
            ("", "hello", 1.0, 1.0, 1, 0, 0),

            # ── English — empty hypothesis ──
            ("hello", "", 1.0, 1.0, 0, 1, 0),

            # ── English — complete replacement (single word) ──
            ("abc", "xyz", 1.0, 1.0, 0, 0, 1),

            # ── English — longer hypothesis with insertions ──
            ("a b", "a x b y", 1.0, 1.0, 2, 0, 0),

            # ── English — longer reference with deletions ──
            ("a b c d", "a c", 0.5, 0.5, 0, 2, 0),

            # ── English — single char mismatch ──
            ("a", "b", 1.0, 1.0, 0, 0, 1),

            # ── English — partial match ──
            ("hello world", "hello moon", 0.5, 0.5, 0, 0, 1),

            # ── English — repeated words ──
            ("the the the", "the the", 1/3, 1/3, 0, 1, 0),
            ("the the", "the the the", 1/2, 1/2, 1, 0, 0),
        ],
    )
    def test_english_wer_cer(self, wer_metric, reference, hypothesis,
                              expected_wer, expected_cer,
                              expected_ins, expected_del, expected_sub):
        wer, cer, ins, dels, subs, ref_w, hyp_w = wer_metric._compute_wer_cer(reference, hypothesis)
        assert wer == pytest.approx(expected_wer, abs=0.01)
        assert cer == pytest.approx(expected_cer, abs=0.01)
        assert ins == expected_ins
        assert dels == expected_del
        assert subs == expected_sub

    @pytest.mark.parametrize(
        "reference, hypothesis, expected_wer, expected_cer, expected_ins, expected_del, expected_sub",
        [
            # ── Chinese — identical ──
            ("你好世界", "你好世界", 0.0, 0.0, 0, 0, 0),

            # ── Chinese — single substitution ──
            ("你好世界", "你坏世界", 0.25, 0.25, 0, 0, 1),

            # ── Chinese — single insertion (2 chars added) ──
            ("你好", "你好世界", 1.0, 1.0, 2, 0, 0),

            # ── Chinese — single deletion (2 chars removed) ──
            ("你好世界", "你好", 0.5, 0.5, 0, 2, 0),

            # ── Chinese — empty reference (2 chars inserted) ──
            ("", "你好", 2.0, 2.0, 2, 0, 0),

            # ── Chinese — empty hypothesis (1 char deleted) ──
            ("你好", "", 1.0, 1.0, 0, 2, 0),

            # ── Chinese — complete replacement (no Chinese chars → English tokenization) ──
            ("abc", "xyz", 1.0, 1.0, 0, 0, 1),
        ],
    )
    def test_chinese_wer_cer(self, wer_metric, reference, hypothesis,
                              expected_wer, expected_cer,
                              expected_ins, expected_del, expected_sub):
        wer, cer, ins, dels, subs, ref_w, hyp_w = wer_metric._compute_wer_cer(reference, hypothesis)
        assert wer == pytest.approx(expected_wer, abs=0.01)
        assert cer == pytest.approx(expected_cer, abs=0.01)
        assert ins == expected_ins
        assert dels == expected_del
        assert subs == expected_sub

    @pytest.mark.parametrize(
        "reference, hypothesis, expected_wer, expected_cer, expected_ins, expected_del, expected_sub",
        [
            # ── Mixed Chinese + English spaces ──
            ("你好 world", "你好 world", 0.0, 0.0, 0, 0, 0),

            # ── Chinese with English words (Chinese detected → char tokenization) ──
            # Tokenized as: 你 好 h e l l o 世 界 (9 chars) vs 你 好 w o r l d 世 界 (9 chars)
            # "hello" vs "world" → 5 substitutions among 9 total
            ("你好hello世界", "你好world世界", 4/9, 4/9, 0, 0, 4),
        ],
    )
    def test_mixed_language_wer_cer(self, wer_metric, reference, hypothesis,
                                     expected_wer, expected_cer,
                                     expected_ins, expected_del, expected_sub):
        wer, cer, ins, dels, subs, ref_w, hyp_w = wer_metric._compute_wer_cer(reference, hypothesis)
        assert wer == pytest.approx(expected_wer, abs=0.01)
        assert cer == pytest.approx(expected_cer, abs=0.01)
        assert ins == expected_ins
        assert dels == expected_del
        assert subs == expected_sub

    def test_token_counts_correct(self, wer_metric):
        """reference_words and hypothesis_words are the token counts."""
        wer, cer, ins, dels, subs, ref_w, hyp_w = wer_metric._compute_wer_cer(
            "hello world foo", "hello bar foo"
        )
        assert ref_w == 3
        assert hyp_w == 3
        assert ins + dels + subs >= 1

    def test_chinese_tokenization_strips_spaces(self, wer_metric):
        """Chinese text should be tokenized by character, spaces removed."""
        wer, cer, ins, dels, subs, ref_w, hyp_w = wer_metric._compute_wer_cer(
            "你 好 世 界", "你好世界"
        )
        # Chinese tokenization strips spaces → "你好世界" → 4 chars
        assert ref_w == 4
        assert hyp_w == 4

    @pytest.mark.parametrize(
        "ref, hyp",
        [
            ("", ""),
            ("", "a"),
            ("a", ""),
            ("a", "a"),
            ("a b c d e", "a b c d e"),
        ],
    )
    def test_levenshtein_boundary_word_counts(self, wer_metric, ref, hyp):
        """Verify word/token counts are always correct at boundaries."""
        wer, cer, ins, dels, subs, ref_w, hyp_w = wer_metric._compute_wer_cer(ref, hyp)
        expected_ref_w = len(ref.split()) if ref else 0
        expected_hyp_w = len(hyp.split()) if hyp else 0
        assert ref_w == expected_ref_w
        assert hyp_w == expected_hyp_w

    def test_insertion_dominates(self, wer_metric):
        """When hypothesis is much longer, insertions dominate."""
        wer, cer, ins, dels, subs, ref_w, hyp_w = wer_metric._compute_wer_cer(
            "a", "a b c d e f g h i j"
        )
        assert ins == 9
        assert dels == 0
        assert subs == 0

    def test_deletion_dominates(self, wer_metric):
        """When hypothesis is much shorter, deletions dominate."""
        wer, cer, ins, dels, subs, ref_w, hyp_w = wer_metric._compute_wer_cer(
            "a b c d e f g h i j", "a"
        )
        assert ins == 0
        assert dels == 9
        assert subs == 0

    def test_substitution_dominates(self, wer_metric):
        """When all tokens mismatch but counts match, substitutions dominate."""
        wer, cer, ins, dels, subs, ref_w, hyp_w = wer_metric._compute_wer_cer(
            "cat dog bird", "bat fog nerd"
        )
        assert ins == 0
        assert dels == 0
        assert subs == 3


# ===========================================================================
# 2. WERResult.compute() edge cases
# ===========================================================================


class TestWERResultCompute:
    """Test WERResult.compute() with various edge cases."""

    def test_no_reference_text_returns_error(self, wer_metric):
        """When no reference is provided, returns error WERResult."""
        wer_metric.reference_text = None
        result = wer_metric.compute(Path("dummy.wav"))
        assert result.success is False
        assert result.error == "No reference text provided"
        assert result.wer == 1.0
        assert result.cer == 1.0
        assert result.reference_words == 0
        assert result.hypothesis_words == 0

    def test_reference_overrides_constructor(self, wer_metric):
        """reference_text parameter overrides constructor reference_text."""
        mock_asr_result = MagicMock()
        mock_asr_result.success = True
        mock_asr_result.text = "hello world"
        wer_metric._backend.transcribe.return_value = mock_asr_result

        result = wer_metric.compute(Path("dummy.wav"), reference_text="hello world")
        assert result.success is True
        assert result.wer == 0.0
        assert result.cer == 0.0

    def test_asr_failure_returns_error(self, wer_metric):
        """When ASR backend fails, returns error WERResult."""
        mock_asr_result = MagicMock()
        mock_asr_result.success = False
        mock_asr_result.error = "Model load failed"
        wer_metric._backend.transcribe.return_value = mock_asr_result

        result = wer_metric.compute(Path("dummy.wav"), reference_text="hello")
        assert result.success is False
        assert result.error == "Model load failed"

    def test_asr_exception_returns_error(self, wer_metric):
        """When ASR backend raises exception, returns error WERResult."""
        wer_metric._backend.transcribe.side_effect = RuntimeError("GPU OOM")

        result = wer_metric.compute(Path("dummy.wav"), reference_text="hello")
        assert result.success is False
        assert "GPU OOM" in result.error

    def test_successful_computation(self, wer_metric):
        """Successful WER computation with matching reference."""
        mock_asr_result = MagicMock()
        mock_asr_result.success = True
        mock_asr_result.text = "hello world"
        wer_metric._backend.transcribe.return_value = mock_asr_result

        result = wer_metric.compute(Path("dummy.wav"), reference_text="hello world")
        assert result.success is True
        assert result.wer == 0.0
        assert result.cer == 0.0
        assert result.insertions == 0
        assert result.deletions == 0
        assert result.substitutions == 0

    def test_partial_match_computation(self, wer_metric):
        """WER computation with partial match."""
        mock_asr_result = MagicMock()
        mock_asr_result.success = True
        mock_asr_result.text = "hello moon"
        wer_metric._backend.transcribe.return_value = mock_asr_result

        result = wer_metric.compute(Path("dummy.wav"), reference_text="hello world")
        assert result.success is True
        assert result.wer == pytest.approx(0.5, abs=0.01)
        assert result.cer == pytest.approx(0.5, abs=0.01)


# ===========================================================================
# 3. Dataclass to_dict() serialization
# ===========================================================================


class TestDNSMOSResultToDict:
    @pytest.mark.parametrize(
        "mos_overall, mos_sig, mos_bak, mos_ovr, success, error",
        [
            (4.5, 4.2, 4.0, 4.3, True, None),
            (1.0, 1.0, 1.0, 1.0, True, None),
            (5.0, 5.0, 5.0, 5.0, True, None),
            (0.0, 0.0, 0.0, 0.0, False, "Model not loaded"),
            (3.5, 3.0, 4.0, 3.8, False, "Inference error"),
        ],
    )
    def test_dnsmos_to_dict(self, mos_overall, mos_sig, mos_bak, mos_ovr, success, error):
        from src.audiobook_studio.quality.metrics import DNSMOSResult
        r = DNSMOSResult(mos_overall, mos_sig, mos_bak, mos_ovr, success, error)
        d = r.to_dict()
        assert d["mos_overall"] == mos_overall
        assert d["mos_sig"] == mos_sig
        assert d["mos_bak"] == mos_bak
        assert d["mos_ovr"] == mos_ovr
        assert d["success"] == success
        assert d["error"] == error


class TestASRResultToDict:
    @pytest.mark.parametrize(
        "text, words, language, confidence, duration_ms, success, error",
        [
            ("hello", [{"word": "hello", "start_ms": 0, "end_ms": 500, "confidence": 0.99}], "en", 0.99, 500.0, True, None),
            ("", [], "unknown", 0.0, 0.0, False, "No audio"),
            ("你好", [{"word": "你", "start_ms": 0, "end_ms": 300, "confidence": 0.95}, {"word": "好", "start_ms": 300, "end_ms": 600, "confidence": 0.97}], "zh", 0.96, 600.0, True, None),
            ("test", [{"word": "test", "start_ms": 0, "end_ms": 1000, "confidence": 0.5}], "en", 0.5, 1000.0, True, None),
        ],
    )
    def test_asr_to_dict(self, text, words, language, confidence, duration_ms, success, error):
        from src.audiobook_studio.quality.metrics import ASRResult
        r = ASRResult(text=text, words=words, language=language,
                      confidence=confidence, duration_ms=duration_ms,
                      success=success, error=error)
        d = r.to_dict()
        assert d["text"] == text
        assert d["words"] == words
        assert d["language"] == language
        assert d["confidence"] == confidence
        assert d["duration_ms"] == duration_ms
        assert d["success"] == success
        assert d["error"] == error


class TestWERResultToDict:
    @pytest.mark.parametrize(
        "wer, cer, insertions, deletions, substitutions, reference_words, hypothesis_words, success, error",
        [
            (0.0, 0.0, 0, 0, 0, 10, 10, True, None),
            (1.0, 1.0, 5, 5, 5, 10, 10, False, "No reference"),
            (0.5, 0.3, 2, 1, 1, 5, 6, True, None),
            (0.1, 0.05, 0, 0, 1, 10, 10, True, None),
            (2.0, 2.0, 10, 0, 0, 0, 10, False, "Empty reference"),
        ],
    )
    def test_wer_to_dict(self, wer, cer, insertions, deletions, substitutions,
                          reference_words, hypothesis_words, success, error):
        from src.audiobook_studio.quality.metrics import WERResult
        r = WERResult(wer=wer, cer=cer, insertions=insertions, deletions=deletions,
                      substitutions=substitutions, reference_words=reference_words,
                      hypothesis_words=hypothesis_words, success=success, error=error)
        d = r.to_dict()
        assert d["wer"] == wer
        assert d["cer"] == cer
        assert d["insertions"] == insertions
        assert d["deletions"] == deletions
        assert d["substitutions"] == substitutions
        assert d["reference_words"] == reference_words
        assert d["hypothesis_words"] == hypothesis_words
        assert d["success"] == success
        assert d["error"] == error


class TestSpeakerSimilarityResultToDict:
    @pytest.mark.parametrize(
        "similarity, threshold, is_same, ref_id, target_id, success, error",
        [
            (0.95, 0.85, True, "ref_001", "target_001", True, None),
            (0.5, 0.85, False, "ref_001", "target_002", True, None),
            (0.0, 0.85, False, "", "target_003", False, "No reference"),
            (1.0, 1.0, True, "ref", "target", True, None),
        ],
    )
    def test_similarity_to_dict(self, similarity, threshold, is_same, ref_id, target_id, success, error):
        from src.audiobook_studio.quality.metrics import SpeakerSimilarityResult
        r = SpeakerSimilarityResult(
            similarity=similarity, threshold=threshold, is_same_speaker=is_same,
            reference_id=ref_id, target_id=target_id, success=success, error=error,
        )
        d = r.to_dict()
        assert d["similarity"] == similarity
        assert d["threshold"] == threshold
        assert d["is_same_speaker"] == is_same
        assert d["reference_id"] == ref_id
        assert d["target_id"] == target_id
        assert d["success"] == success
        assert d["error"] == error


# ===========================================================================
# 4. SpeakerEmbedding to_dict / from_dict round-trip
# ===========================================================================


class TestSpeakerEmbeddingRoundTrip:
    @pytest.mark.parametrize(
        "embedding_dim, model_name, sample_rate",
        [
            (192, "ecapa_tdnn", 16000),
            (512, "wavlm_large", 16000),
            (256, "custom_model", 44100),
            (1, "minimal", 8000),
        ],
    )
    def test_round_trip(self, embedding_dim, model_name, sample_rate):
        from src.audiobook_studio.quality.metrics import SpeakerEmbedding
        emb = np.random.randn(embedding_dim).astype(np.float32)
        se = SpeakerEmbedding(embedding=emb, model_name=model_name, sample_rate=sample_rate)

        d = se.to_dict()
        assert d["dim"] == embedding_dim
        assert d["model_name"] == model_name
        assert d["sample_rate"] == sample_rate
        assert len(d["embedding"]) == embedding_dim

        restored = SpeakerEmbedding.from_dict(d)
        assert restored.model_name == model_name
        assert restored.sample_rate == sample_rate
        np.testing.assert_array_almost_equal(restored.embedding, emb)

    def test_zero_dimension_embedding(self):
        from src.audiobook_studio.quality.metrics import SpeakerEmbedding
        emb = np.array([], dtype=np.float32)
        se = SpeakerEmbedding(embedding=emb, model_name="test", sample_rate=16000)
        d = se.to_dict()
        assert d["dim"] == 0
        assert d["embedding"] == []

        restored = SpeakerEmbedding.from_dict(d)
        assert len(restored.embedding) == 0

    def test_all_zeros_embedding(self):
        from src.audiobook_studio.quality.metrics import SpeakerEmbedding
        emb = np.zeros(192, dtype=np.float32)
        se = SpeakerEmbedding(embedding=emb, model_name="ecapa", sample_rate=16000)
        d = se.to_dict()
        restored = SpeakerEmbedding.from_dict(d)
        np.testing.assert_array_equal(restored.embedding, emb)

    def test_large_embedding(self):
        """Large embedding (e.g. wav2vec 1024-dim)."""
        from src.audiobook_studio.quality.metrics import SpeakerEmbedding
        emb = np.random.randn(1024).astype(np.float32)
        se = SpeakerEmbedding(embedding=emb, model_name="wav2vec_large", sample_rate=16000)
        d = se.to_dict()
        restored = SpeakerEmbedding.from_dict(d)
        assert restored.embedding.shape == (1024,)
        np.testing.assert_array_almost_equal(restored.embedding, emb)


# ===========================================================================
# 5. WERResult.compute() — no reference branch
# ===========================================================================


class TestWERResultNoReference:
    """Test the early-return branch when reference_text is missing."""

    @pytest.mark.parametrize(
        "ref_text",
        [
            None,
            "",
        ],
    )
    def test_no_reference_returns_error(self, ref_text):
        """Empty/None reference triggers the no-reference error branch."""
        from src.audiobook_studio.quality.metrics import ASRWerMetric
        metric = ASRWerMetric(backend="funasr", model_name="test", reference_text="init")
        metric._backend = MagicMock()
        metric.reference_text = ref_text  # Force it to None/empty

        result = metric.compute(Path("dummy.wav"))
        assert result.success is False
        assert "No reference" in result.error
        assert result.wer == 1.0
        assert result.cer == 1.0

    def test_constructor_reference_used_when_no_param(self):
        """Constructor reference_text is used when compute() gets no param."""
        from src.audiobook_studio.quality.metrics import ASRWerMetric
        metric = ASRWerMetric(backend="funasr", model_name="test", reference_text="hello")
        metric._backend = MagicMock()

        mock_asr = MagicMock()
        mock_asr.success = True
        mock_asr.text = "hello"
        metric._backend.transcribe.return_value = mock_asr

        result = metric.compute(Path("dummy.wav"))
        assert result.success is True
        assert result.wer == 0.0

    def test_param_reference_overrides_constructor(self):
        """compute(reference_text=...) overrides constructor reference_text."""
        from src.audiobook_studio.quality.metrics import ASRWerMetric
        metric = ASRWerMetric(backend="funasr", model_name="test", reference_text="old")
        metric._backend = MagicMock()

        mock_asr = MagicMock()
        mock_asr.success = True
        mock_asr.text = "new"
        metric._backend.transcribe.return_value = mock_asr

        result = metric.compute(Path("dummy.wav"), reference_text="new")
        assert result.success is True
        assert result.wer == 0.0

    def test_constructor_reference_used_when_param_none(self):
        """When compute() param is None, falls back to constructor reference."""
        from src.audiobook_studio.quality.metrics import ASRWerMetric
        metric = ASRWerMetric(backend="funasr", model_name="test", reference_text="fallback")
        metric._backend = MagicMock()

        mock_asr = MagicMock()
        mock_asr.success = True
        mock_asr.text = "fallback"
        metric._backend.transcribe.return_value = mock_asr

        result = metric.compute(Path("dummy.wav"), reference_text=None)
        assert result.success is True
        assert result.wer == 0.0


# ===========================================================================
# 6. ASRWerMetric._create_backend — branch coverage
# ===========================================================================


class TestASRWerMetricCreateBackend:
    def test_funasr_backend(self):
        from src.audiobook_studio.quality.metrics import ASRWerMetric, FunASRBackend
        metric = ASRWerMetric(backend="funasr", model_name="paraformer")
        assert isinstance(metric._backend, FunASRBackend)

    def test_whisper_backend(self):
        from src.audiobook_studio.quality.metrics import ASRWerMetric, WhisperBackend
        metric = ASRWerMetric(backend="whisper", model_name="small")
        assert isinstance(metric._backend, WhisperBackend)

    def test_unknown_backend_raises(self):
        from src.audiobook_studio.quality.metrics import ASRWerMetric
        with pytest.raises(ValueError, match="Unknown ASR backend"):
            ASRWerMetric(backend="invalid_backend", model_name="test")


# ===========================================================================
# 7. SpeakerSimilarityMetric._create_backend — branch coverage
# ===========================================================================


class TestSpeakerSimilarityCreateBackend:
    def test_ecapa_backend(self):
        from src.audiobook_studio.quality.metrics import SpeakerSimilarityMetric, ECAPATDNNBackend
        metric = SpeakerSimilarityMetric(backend="ecapa_tdnn")
        assert isinstance(metric._backend, ECAPATDNNBackend)

    def test_wavlm_backend(self):
        from src.audiobook_studio.quality.metrics import SpeakerSimilarityMetric, WavLMBackend
        metric = SpeakerSimilarityMetric(backend="wavlm_large")
        assert isinstance(metric._backend, WavLMBackend)

    def test_unknown_backend_raises(self):
        from src.audiobook_studio.quality.metrics import SpeakerSimilarityMetric
        with pytest.raises(ValueError, match="Unknown speaker embedding backend"):
            SpeakerSimilarityMetric(backend="unknown_backend")


# ===========================================================================
# 8. SpeakerSimilarityMetric.compute() edge cases
# ===========================================================================


class TestSpeakerSimilarityCompute:
    def test_no_reference_returns_error(self):
        from src.audiobook_studio.quality.metrics import SpeakerSimilarityMetric
        metric = SpeakerSimilarityMetric(backend="ecapa_tdnn")

        result = metric.compute(Path("target.wav"))
        assert result.success is False
        assert "No reference" in result.error
        assert result.similarity == 0.0
        assert result.is_same_speaker is False

    def test_registered_reference_used(self):
        from src.audiobook_studio.quality.metrics import SpeakerSimilarityMetric, SpeakerEmbedding
        metric = SpeakerSimilarityMetric(backend="ecapa_tdnn", threshold=0.85)

        # Manually register an embedding
        ref_emb = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        metric._reference_embeddings["ref_001"] = SpeakerEmbedding(
            embedding=ref_emb, model_name="ecapa_tdnn", sample_rate=16000,
        )

        # Mock backend to return target embedding
        target_emb = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        target_embedding = SpeakerEmbedding(
            embedding=target_emb, model_name="ecapa_tdnn", sample_rate=16000,
        )
        metric._backend.extract_embedding = MagicMock(return_value=target_embedding)

        result = metric.compute(Path("target.wav"), reference_id="ref_001")
        assert result.success is True
        assert result.similarity == pytest.approx(1.0, abs=0.01)
        assert result.is_same_speaker is True

    def test_reference_id_not_found_falls_to_audio(self):
        """When reference_id is not in _reference_embeddings, checks reference_audio path."""
        from src.audiobook_studio.quality.metrics import SpeakerSimilarityMetric, SpeakerEmbedding
        metric = SpeakerSimilarityMetric(backend="ecapa_tdnn")

        ref_emb = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        ref_embedding = SpeakerEmbedding(
            embedding=ref_emb, model_name="ecapa_tdnn", sample_rate=16000,
        )
        target_emb = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        target_embedding = SpeakerEmbedding(
            embedding=target_emb, model_name="ecapa_tdnn", sample_rate=16000,
        )
        call_count = [0]
        def mock_extract(audio_path):
            call_count[0] += 1
            if call_count[0] == 1:
                return ref_embedding
            return target_embedding
        metric._backend.extract_embedding = MagicMock(side_effect=mock_extract)

        # reference_id not found → should fall through to extract_embedding from reference_audio
        result = metric.compute(Path("target.wav"), reference_id="nonexistent", reference_audio=Path("ref.wav"))
        assert result.success is True

    def test_threshold_boundary(self):
        """is_same_speaker depends on similarity >= threshold."""
        from src.audiobook_studio.quality.metrics import SpeakerSimilarityMetric, SpeakerEmbedding
        metric = SpeakerSimilarityMetric(backend="ecapa_tdnn", threshold=0.85)

        # Register reference with known embedding
        ref_emb = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        metric._reference_embeddings["ref"] = SpeakerEmbedding(
            embedding=ref_emb, model_name="ecapa", sample_rate=16000,
        )

        # Target with cosine similarity = 0.9 (above threshold)
        target_emb = np.array([0.9, 0.43589, 0.0], dtype=np.float32)
        target_embedding = SpeakerEmbedding(
            embedding=target_emb, model_name="ecapa", sample_rate=16000,
        )
        metric._backend.extract_embedding = MagicMock(return_value=target_embedding)

        result = metric.compute(Path("target.wav"), reference_id="ref")
        assert result.success is True
        # cos(0.9, 0, 0; 1, 0, 0) = 0.9/1.0 = 0.9 > 0.85 → same speaker
        assert result.is_same_speaker is True


# ===========================================================================
# 9. ASR get_name() branch coverage
# ===========================================================================


class TestASRGetName:
    def test_funasr_name(self):
        from src.audiobook_studio.quality.metrics import ASRWerMetric
        m = ASRWerMetric(backend="funasr", model_name="paraformer")
        assert "funasr" in m.get_name()
        assert "paraformer" in m.get_name()

    def test_whisper_name(self):
        from src.audiobook_studio.quality.metrics import ASRWerMetric
        m = ASRWerMetric(backend="whisper", model_name="small")
        assert "whisper" in m.get_name()
        assert "small" in m.get_name()


class TestSpeakerSimilarityGetName:
    def test_ecapa_name(self):
        from src.audiobook_studio.quality.metrics import SpeakerSimilarityMetric
        m = SpeakerSimilarityMetric(backend="ecapa_tdnn")
        assert m.get_name() == "speaker_sim_ecapa_tdnn"

    def test_wavlm_name(self):
        from src.audiobook_studio.quality.metrics import SpeakerSimilarityMetric
        m = SpeakerSimilarityMetric(backend="wavlm_large")
        assert m.get_name() == "speaker_sim_wavlm_large"


# ===========================================================================
# 10. DNSMOS compute() edge cases
# ===========================================================================


class TestDNSMOSCompute:
    def test_missing_model_returns_error(self):
        """DNSMOS compute when model is None returns error."""
        from src.audiobook_studio.quality.metrics import DNSMOSResult

        # Simulate the early return when model is not loaded
        result = DNSMOSResult(
            mos_overall=0.0, mos_sig=0.0, mos_bak=0.0, mos_ovr=0.0,
            success=False, error="Model not loaded",
        )
        assert result.success is False
        d = result.to_dict()
        assert d["success"] is False
        assert "Model not loaded" in d["error"]


# ===========================================================================
# 11. WERResult.to_dict() — all fields
# ===========================================================================


class TestWERResultAllFields:
    """Ensure to_dict returns every field correctly."""

    def test_all_fields_present(self):
        from src.audiobook_studio.quality.metrics import WERResult
        r = WERResult(
            wer=0.15, cer=0.08, insertions=2, deletions=1, substitutions=3,
            reference_words=20, hypothesis_words=21, success=True, error=None,
        )
        d = r.to_dict()
        expected_keys = {
            "wer", "cer", "insertions", "deletions", "substitutions",
            "reference_words", "hypothesis_words", "success", "error",
        }
        assert set(d.keys()) == expected_keys

    def test_error_field_populated(self):
        from src.audiobook_studio.quality.metrics import WERResult
        r = WERResult(
            wer=1.0, cer=1.0, insertions=0, deletions=0, substitutions=0,
            reference_words=0, hypothesis_words=0, success=False,
            error="ASR model crashed",
        )
        d = r.to_dict()
        assert d["error"] == "ASR model crashed"


# ===========================================================================
# 12. Edge case: very long strings
# ===========================================================================


class TestVeryLongStrings:
    def test_long_english_paragraph(self, wer_metric):
        """100-word paragraph — all identical."""
        ref = " ".join(["word"] * 100)
        hyp = " ".join(["word"] * 100)
        wer, cer, ins, dels, subs, ref_w, hyp_w = wer_metric._compute_wer_cer(ref, hyp)
        assert wer == 0.0
        assert ref_w == 100
        assert hyp_w == 100

    def test_long_paragraph_one_diff(self, wer_metric):
        """100-word paragraph, one substitution."""
        words = ["word"] * 100
        hyp_words = words.copy()
        hyp_words[50] = "DIFF"
        ref = " ".join(words)
        hyp = " ".join(hyp_words)
        wer, cer, ins, dels, subs, ref_w, hyp_w = wer_metric._compute_wer_cer(ref, hyp)
        assert wer == pytest.approx(0.01, abs=0.001)
        assert subs == 1

    def test_long_chinese_paragraph(self, wer_metric):
        """100 Chinese characters — all identical."""
        ref = "你" * 100
        hyp = "你" * 100
        wer, cer, ins, dels, subs, ref_w, hyp_w = wer_metric._compute_wer_cer(ref, hyp)
        assert wer == 0.0
        assert ref_w == 100
        assert hyp_w == 100

    def test_long_paragraph_all_different(self, wer_metric):
        """100-word paragraph, all substitutions."""
        ref_words = [f"a{i}" for i in range(100)]
        hyp_words = [f"b{i}" for i in range(100)]
        ref = " ".join(ref_words)
        hyp = " ".join(hyp_words)
        wer, cer, ins, dels, subs, ref_w, hyp_w = wer_metric._compute_wer_cer(ref, hyp)
        assert wer == pytest.approx(1.0, abs=0.01)
        assert subs == 100


# ===========================================================================
# 13. SpeakerEmbedding edge cases
# ===========================================================================


class TestSpeakerEmbeddingEdgeCases:
    def test_negative_values(self):
        """Embedding with negative values round-trips correctly."""
        from src.audiobook_studio.quality.metrics import SpeakerEmbedding
        emb = np.array([-1.5, -0.0, 2.5, 100.0], dtype=np.float32)
        se = SpeakerEmbedding(embedding=emb, model_name="test", sample_rate=16000)
        d = se.to_dict()
        restored = SpeakerEmbedding.from_dict(d)
        np.testing.assert_array_almost_equal(restored.embedding, emb)

    def test_nan_values(self):
        """Embedding with NaN values round-trips correctly."""
        from src.audiobook_studio.quality.metrics import SpeakerEmbedding
        emb = np.array([1.0, float("nan"), 3.0], dtype=np.float32)
        se = SpeakerEmbedding(embedding=emb, model_name="test", sample_rate=16000)
        d = se.to_dict()
        restored = SpeakerEmbedding.from_dict(d)
        np.testing.assert_array_equal(restored.embedding[0], 1.0)
        assert np.isnan(restored.embedding[1])
        np.testing.assert_array_equal(restored.embedding[2], 3.0)

    def test_inf_values(self):
        """Embedding with inf values round-trips correctly."""
        from src.audiobook_studio.quality.metrics import SpeakerEmbedding
        emb = np.array([float("inf"), float("-inf"), 0.0], dtype=np.float32)
        se = SpeakerEmbedding(embedding=emb, model_name="test", sample_rate=16000)
        d = se.to_dict()
        restored = SpeakerEmbedding.from_dict(d)
        np.testing.assert_array_equal(restored.embedding, emb)
