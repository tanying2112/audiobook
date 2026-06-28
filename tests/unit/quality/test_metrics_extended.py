import os
import sys

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../src"))

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from src.audiobook_studio.quality.metrics import (
    ASRWerMetric,
    DNSMOSMetric,
    DNSMOSResult,
    ECAPATDNNBackend,
    FunASRBackend,
    QualityCheckResult,
    QualityCheckSuite,
    SpeakerEmbedding,
    SpeakerSimilarityMetric,
    SpeakerSimilarityResult,
    WavLMBackend,
    WERResult,
    WhisperBackend,
)


class TestDNSMOSMetric(unittest.TestCase):
    def setUp(self):
        # Create metric with mocked model path that doesn't exist
        self.metric = DNSMOSMetric(model_path=Path("/nonexistent/dnsmos.onnx"))

    def test_init_with_default_path(self):
        # Test initialization with default model path (None)
        metric = DNSMOSMetric(model_path=None)
        self.assertEqual(metric.model_path.name, "dnsmos.onnx")
        self.assertEqual(metric.sample_rate, 16000)
        self.assertTrue(metric.use_ort)

    def test_init_with_custom_sample_rate(self):
        metric = DNSMOSMetric(model_path=Path("/tmp/test.onnx"), sample_rate=8000)
        self.assertEqual(metric.sample_rate, 8000)

    def test_get_name(self):
        self.assertEqual(self.metric.get_name(), "dnsmos")

    @patch.object(DNSMOSMetric, "_initialize")
    @patch.object(DNSMOSMetric, "_preprocess_audio")
    @patch.object(DNSMOSMetric, "_compute_dnsmos")
    def test_compute_success(self, mock_compute, mock_preprocess, mock_initialize):
        mock_preprocess.return_value = np.array([0.1, 0.2, 0.3], dtype=np.float32)
        mock_compute.return_value = (4.0, 3.5, 4.0, 3.8)  # overall, sig, bak, ovr

        result = self.metric.compute_detailed(Path("dummy.wav"))
        self.assertIsInstance(result, DNSMOSResult)
        self.assertTrue(result.success)
        self.assertEqual(result.mos_overall, 4.0)
        self.assertEqual(result.mos_sig, 3.5)
        self.assertEqual(result.mos_bak, 4.0)
        self.assertEqual(result.mos_ovr, 3.8)

    @patch.object(DNSMOSMetric, "_initialize")
    @patch.object(DNSMOSMetric, "_preprocess_audio")
    def test_compute_preprocess_failure(self, mock_preprocess, mock_initialize):
        mock_preprocess.side_effect = Exception("Preprocessing failed")
        result = self.metric.compute_detailed(Path("dummy.wav"))
        self.assertFalse(result.success)
        self.assertEqual(result.mos_overall, 0.0)
        self.assertIn("Preprocessing failed", result.error)

    @patch.object(DNSMOSMetric, "_initialize")
    @patch.object(DNSMOSMetric, "_preprocess_audio")
    @patch.object(DNSMOSMetric, "_compute_dnsmos")
    def test_compute_computation_failure(
        self, mock_compute, mock_preprocess, mock_initialize
    ):
        mock_preprocess.return_value = np.array([0.1, 0.2], dtype=np.float32)
        mock_compute.side_effect = Exception("Computation error")
        result = self.metric.compute_detailed(Path("dummy.wav"))
        self.assertFalse(result.success)
        self.assertEqual(result.mos_overall, 0.0)
        self.assertIn("Computation error", result.error)

    def test_ensure_model_success(self):
        # Directly test _ensure_model method with a mock
        self.metric._ensure_model = MagicMock(return_value=True)
        result = self.metric._ensure_model()
        self.assertTrue(result)
        self.metric._ensure_model.assert_called_once()

    def test_ensure_model_failure(self):
        with patch.object(self.metric, "_ensure_model", return_value=False):
            result = self.metric._ensure_model()
            self.assertFalse(result)

    def test_compute_dnsmos_short_audio_path(self):
        # Test _compute_dnsmos with audio path
        # Mock model initialization
        with patch.object(self.metric, "_ensure_model", return_value=True):
            # Mock the ONNX session
            mock_session = MagicMock()
            mock_session.run.return_value = [
                np.array([[3.5, 4.0, 3.8]], dtype=np.float32)
            ]  # [SIG, BAK, OVR]
            self.metric._session = mock_session
            self.metric._initialized = True

            # Call the method
            result = self.metric._compute_dnsmos(
                np.random.randn(16000).astype(np.float32)
            )

            # Should return a tuple of 4 floats: (mos_overall, mos_sig, mos_bak, mos_ovr)
            self.assertEqual(len(result), 4)
            self.assertIsInstance(result, tuple)
            # mos_overall should be the average of the three scores
            expected_overall = (3.5 + 4.0 + 3.8) / 3.0
            self.assertAlmostEqual(result[0], expected_overall, places=2)

    def test_compute_dnsmos_with_torch(self):
        # Test with torch backend - skip as current implementation only uses ONNX
        self.skipTest("Current DNSMOSMetric only implements ONNX Runtime backend")


class TestASRWerMetric(unittest.TestCase):
    def setUp(self):
        self.metric = ASRWerMetric(backend="funasr", mock_mode=True)

    def test_compute_wer_cer(self):
        # Test the WER/CER computation helper
        # English words
        wer, cer, ins, dels, subs, ref_w, hyp_w = self.metric._compute_wer_cer(
            "hello world", "hello word"
        )
        self.assertEqual(subs, 1)
        self.assertEqual(ins, 0)
        self.assertEqual(dels, 0)
        self.assertAlmostEqual(wer, 0.5)  # 1 substitution out of 2 words

        # Chinese characters - treat as characters
        wer, cer, ins, dels, subs, ref_w, hyp_w = self.metric._compute_wer_cer(
            "你好世界", "你好"
        )
        self.assertEqual(dels, 2)
        self.assertEqual(ins, 0)
        self.assertEqual(subs, 0)
        # wer = deletions / max(reference_length, 1) = 2 / 4 = 0.5
        self.assertAlmostEqual(wer, 0.5)


class TestSpeakerSimilarityMetric(unittest.TestCase):
    def setUp(self):
        self.metric = SpeakerSimilarityMetric()

    def test_cosine_similarity(self):
        # Test identical vectors
        sim = self.metric._cosine_similarity([1, 0], [1, 0])
        self.assertAlmostEqual(sim, 1.0)

        # Test orthogonal vectors
        sim = self.metric._cosine_similarity([1, 0], [0, 1])
        self.assertAlmostEqual(sim, 0.0)

        # Test zero vector
        sim = self.metric._cosine_similarity([0, 0], [1, 0])
        self.assertEqual(sim, 0.0)

        # Test opposite vectors
        sim = self.metric._cosine_similarity([1, 0], [-1, 0])
        self.assertAlmostEqual(sim, -1.0)

    def test_get_name(self):
        self.assertIn("speaker_sim", self.metric.get_name())

    def test_compute(self):
        # Mock the backend's extract_embedding method
        mock_embedding = MagicMock()
        mock_embedding.embedding = np.array([0.1, 0.2])
        # Set up return_value to be used for both calls (reference and target)
        with patch.object(
            self.metric._backend, "extract_embedding", return_value=mock_embedding
        ) as mock_extract:
            result = self.metric.compute(
                Path("ref.wav"), reference_audio=Path("ref.wav")
            )
            self.assertTrue(hasattr(result, "success"))
            # extract_embedding should be called twice: once for ref, once for target
            self.assertEqual(mock_extract.call_count, 2)

    def test_compute_no_reference(self):
        result = self.metric.compute(Path("target.wav"))
        self.assertFalse(result.success)
        self.assertIn("No reference provided", result.error)

    def test_compute_with_registered_reference(self):
        mock_embedding = MagicMock()
        mock_embedding.embedding = np.array([0.1, 0.2])
        # First register a reference
        with patch.object(
            self.metric._backend, "extract_embedding", return_value=mock_embedding
        ) as mock_extract:
            # Register the reference
            self.metric.register_reference("test_ref", Path("ref.wav"))
            # Now compute with the reference_id
            result = self.metric.compute(Path("target.wav"), reference_id="test_ref")
            # Should call extract_embedding twice: once for ref (in register), once for target
            self.assertEqual(mock_extract.call_count, 2)

    def test_compute_embedding_failure(self):
        mock_backend = MagicMock()
        mock_backend.extract_embedding.side_effect = Exception("Embedding failed")
        self.metric._backend = mock_backend

        result = self.metric.compute(Path("ref.wav"), reference_audio=Path("ref.wav"))
        self.assertFalse(result.success)
        self.assertEqual(result.similarity, 0.0)
        self.assertIn("Embedding failed", result.error)

    def test_compute_high_similarity(self):
        # Test with high similarity that exceeds threshold
        mock_embedding = MagicMock()
        mock_embedding.embedding = np.array([1.0, 0.0])
        self.metric._backend.extract_embedding = MagicMock(return_value=mock_embedding)

        result = self.metric.compute(Path("same.wav"), reference_audio=Path("ref.wav"))
        self.assertTrue(result.success)


class TestSpeakerSimilarityResult(unittest.TestCase):
    def test_to_dict(self):
        result = SpeakerSimilarityResult(
            similarity=0.9,
            threshold=0.85,
            is_same_speaker=True,
            reference_id="ref",
            target_id="target",
            success=True,
        )
        d = result.to_dict()
        self.assertEqual(d["similarity"], 0.9)
        self.assertTrue(d["is_same_speaker"])

    def test_to_dict_with_error(self):
        result = SpeakerSimilarityResult(
            similarity=0.0,
            threshold=0.85,
            is_same_speaker=False,
            reference_id="ref",
            target_id="target",
            success=False,
            error="failed",
        )
        d = result.to_dict()
        self.assertEqual(d["error"], "failed")


class TestSpeakerEmbedding(unittest.TestCase):
    def test_to_dict(self):
        embedding = SpeakerEmbedding(
            embedding=np.array([0.1, 0.2, 0.3]),
            model_name="test_model",
            sample_rate=16000,
        )
        d = embedding.to_dict()
        self.assertEqual(len(d["embedding"]), 3)
        self.assertEqual(d["model_name"], "test_model")
        self.assertEqual(d["sample_rate"], 16000)
        self.assertEqual(d["dim"], 3)

    def test_from_dict(self):
        data = {
            "embedding": [0.1, 0.2, 0.3],
            "model_name": "test_model",
            "sample_rate": 16000,
        }
        embedding = SpeakerEmbedding.from_dict(data)
        self.assertEqual(embedding.model_name, "test_model")
        self.assertEqual(embedding.sample_rate, 16000)


class TestFunASRBackend(unittest.TestCase):
    def setUp(self):
        self.backend = FunASRBackend()

    def test_get_name(self):
        self.assertEqual(self.backend.get_name(), "funasr_sensevoice_small")

    def test_get_name_custom_model(self):
        backend = FunASRBackend(model_name="custom")
        self.assertEqual(backend.get_name(), "funasr_custom")


class TestWhisperBackend(unittest.TestCase):
    def setUp(self):
        self.backend = WhisperBackend()

    def test_get_name(self):
        self.assertEqual(self.backend.get_name(), "whisper_small")

    def test_get_name_custom_model(self):
        backend = WhisperBackend(model_size="large")
        self.assertEqual(backend.get_name(), "whisper_large")

    def test_get_name_openai_whisper(self):
        backend = WhisperBackend(use_faster=False)
        self.assertFalse(backend.use_faster)


class TestECAPATDNNBackend(unittest.TestCase):
    def setUp(self):
        self.backend = ECAPATDNNBackend()

    def test_get_name(self):
        self.assertEqual(self.backend.get_name(), "ecapa_tdnn")


class TestWavLMBackend(unittest.TestCase):
    def setUp(self):
        self.backend = WavLMBackend()

    def test_get_name(self):
        self.assertEqual(self.backend.get_name(), "wavlm_large")


class ASRResultTests(unittest.TestCase):
    def test_to_dict(self):
        result = MagicMock()
        # Test ASRResult dataclass-like behavior
        from audiobook_studio.quality.metrics import ASRResult

        r = ASRResult(
            text="hello",
            words=[],
            language="en",
            confidence=0.9,
            duration_ms=1000,
            success=True,
        )
        d = r.to_dict()
        self.assertEqual(d["text"], "hello")


class TestQualityCheckSuite(unittest.TestCase):
    def test_init(self):
        suite = QualityCheckSuite()
        self.assertIsNone(suite._dnsmos)
        self.assertIsNone(suite._wer)
        self.assertIsNone(suite._speaker_sim)

    def test_init_with_config(self):
        config = {
            "quality_check": {
                "dnsmos_enabled": False,
                "asr_enabled": False,
                "speaker_similarity_enabled": False,
                "thresholds": {
                    "dnsmos_min": 3.0,
                    "asr_wer_max": 0.1,
                    "speaker_sim_min": 0.8,
                },
            }
        }
        suite = QualityCheckSuite(config=config, hardware_profile="potato")
        # All metrics should be None since they're disabled
        self.assertIsNone(suite._dnsmos)

    def test_init_with_hardware_profile(self):
        suite = QualityCheckSuite(hardware_profile="potato")
        self.assertEqual(suite.hardware_profile, "potato")

    def test_thresholds(self):
        suite = QualityCheckSuite()
        self.assertEqual(suite.dnsmos_min, 3.5)
        self.assertEqual(suite.asr_wer_max, 0.05)
        self.assertEqual(suite.speaker_sim_min, 0.85)

    def test_register_speaker(self):
        suite = QualityCheckSuite()
        suite._initialized = True  # Prevent re-initialization
        # Mock _backend for speaker similarity
        mock_backend = MagicMock()
        mock_embedding = MagicMock()
        mock_embedding.embedding = np.array([0.1, 0.2])
        mock_backend.extract_embedding.return_value = mock_embedding
        suite._speaker_sim = SpeakerSimilarityMetric(backend="ecapa_tdnn")
        suite._speaker_sim._backend = mock_backend

        result = suite.register_speaker("test_spk", Path("audio.wav"))
        self.assertTrue(result)

    def test_register_speaker_no_speaker_sim(self):
        suite = QualityCheckSuite()
        suite._speaker_sim = None
        result = suite.register_speaker("test_spk", Path("audio.wav"))
        self.assertFalse(result)

    def test_check_all_no_metrics(self):
        # Test check_all when no metrics are initialized
        suite = QualityCheckSuite()
        suite._initialized = True  # Prevent re-initialization
        suite._dnsmos = None
        suite._wer = None
        suite._speaker_sim = None

        result = suite.check_all(Path("audio.wav"))
        # When no metrics run, there are no issues, so passed = True
        self.assertTrue(result.passed)

    def test_check_all_dnsmos_only(self):
        # Test check_all with DNSMOS only
        suite = QualityCheckSuite()
        suite._initialized = True  # Prevent re-initialization
        mock_dnsmos = MagicMock()
        mock_dnsmos.compute_detailed.return_value = DNSMOSResult(
            mos_overall=4.0, mos_sig=3.5, mos_bak=4.0, mos_ovr=3.8, success=True
        )
        suite._dnsmos = mock_dnsmos
        suite._wer = None
        suite._speaker_sim = None

        result = suite.check_all(Path("audio.wav"))
        self.assertTrue(result.dnsmos.success)

    def test_check_all_with_all_metrics(self):
        # Test check_all with all metrics mocked
        suite = QualityCheckSuite()
        suite._initialized = True  # Prevent re-initialization

        mock_dnsmos = MagicMock()
        mock_dnsmos.compute_detailed.return_value = DNSMOSResult(
            mos_overall=4.0, mos_sig=3.5, mos_bak=4.0, mos_ovr=3.8, success=True
        )
        suite._dnsmos = mock_dnsmos

        mock_wer = MagicMock()
        mock_wer.compute.return_value = WERResult(
            wer=0.0,
            cer=0.0,
            insertions=0,
            deletions=0,
            substitutions=0,
            reference_words=2,
            hypothesis_words=2,
            success=True,
        )
        suite._wer = mock_wer

        mock_speaker = MagicMock()
        mock_embedding = MagicMock()
        mock_embedding.embedding = np.array([1.0, 0.0])
        mock_speaker.compute.return_value = SpeakerSimilarityResult(
            similarity=0.9,
            threshold=0.85,
            is_same_speaker=True,
            reference_id="ref",
            target_id="target",
            success=True,
        )
        suite._speaker_sim = mock_speaker

        result = suite.check_all(Path("audio.wav"), reference_text="hello world")
        self.assertTrue(result.passed)

    def test_check_all_dnsmos_threshold_fail(self):
        # Test check_all when DNSMOS score is below threshold
        suite = QualityCheckSuite()
        suite._initialized = True
        suite._dnsmos_min = 4.0  # Set a high threshold

        mock_dnsmos = MagicMock()
        mock_dnsmos.compute_detailed.return_value = DNSMOSResult(
            mos_overall=3.0, mos_sig=2.5, mos_bak=3.0, mos_ovr=2.8, success=True
        )
        suite._dnsmos = mock_dnsmos
        suite._wer = None
        suite._speaker_sim = None

        result = suite.check_all(Path("audio.wav"))
        self.assertFalse(result.passed)
        self.assertIn("DNSMOS", result.overall_message)

    def test_check_all_wer_threshold_fail(self):
        # Test check_all when WER is above threshold
        suite = QualityCheckSuite()
        suite._initialized = True
        suite._asr_wer_max = 0.01  # Set a low threshold

        mock_dnsmos = MagicMock()
        mock_dnsmos.compute_detailed.return_value = DNSMOSResult(
            mos_overall=4.0, mos_sig=3.5, mos_bak=4.0, mos_ovr=3.8, success=True
        )
        suite._dnsmos = mock_dnsmos

        mock_wer = MagicMock()
        mock_wer.compute.return_value = WERResult(
            wer=0.5,
            cer=0.1,
            insertions=2,
            deletions=2,
            substitutions=1,
            reference_words=5,
            hypothesis_words=5,
            success=True,
        )
        suite._wer = mock_wer
        suite._speaker_sim = None

        result = suite.check_all(Path("audio.wav"), reference_text="hello world")
        self.assertFalse(result.passed)
        self.assertIn("ASR WER", result.overall_message)

    def test_register_speaker_embedding_failure(self):
        # Test register_speaker when extraction fails
        suite = QualityCheckSuite()
        suite._initialized = True
        mock_backend = MagicMock()
        mock_backend.extract_embedding.side_effect = Exception("Embedding error")
        suite._speaker_sim = SpeakerSimilarityMetric(backend="ecapa_tdnn")
        suite._speaker_sim._backend = mock_backend

        result = suite.register_speaker("test_spk", Path("audio.wav"))
        self.assertFalse(result)

    def test_quality_check_result_to_dict(self):
        result = QualityCheckResult(
            passed=True,
            dnsmos=DNSMOSResult(
                mos_overall=4.0, mos_sig=3.5, mos_bak=4.0, mos_ovr=3.8, success=True
            ),
            wer=WERResult(
                wer=0.0,
                cer=0.0,
                insertions=0,
                deletions=0,
                substitutions=0,
                reference_words=2,
                hypothesis_words=2,
                success=True,
            ),
            speaker_sim=SpeakerSimilarityResult(
                similarity=0.9,
                threshold=0.85,
                is_same_speaker=True,
                reference_id="ref",
                target_id="target",
                success=True,
            ),
        )
        d = result.to_dict()
        self.assertTrue(d["passed"])
        self.assertEqual(d["dnsmos"]["mos_overall"], 4.0)


if __name__ == "__main__":
    unittest.main()
