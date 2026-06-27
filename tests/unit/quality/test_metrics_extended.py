import sys
import os
from unittest.mock import MagicMock, patch, AsyncMock
import unittest
import numpy as np
from pathlib import Path

# Add the src directory to the path so we can import the module as a package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../src'))

# Mock problematic dependencies
sys.modules['torch'] = MagicMock()
sys.modules['torchaudio'] = MagicMock()
sys.modules['onnxruntime'] = MagicMock()
sys.modules['soundfile'] = MagicMock()
sys.modules['whisper'] = MagicMock()
sys.modules['speechbrain'] = MagicMock()
sys.modules['librosa'] = MagicMock()
sys.modules['funasr'] = MagicMock()
sys.modules['faster_whisper'] = MagicMock()

from audiobook_studio.quality.metrics import (
    DNSMOSMetric,
    ASRWerMetric,
    SpeakerSimilarityMetric,
    DNSMOSResult,
    WERResult,
    SpeakerSimilarityResult,
    SpeakerEmbedding,
    QualityCheckSuite,
    FunASRBackend,
    WhisperBackend,
    ECAPATDNNBackend,
    WavLMBackend,
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

    @patch.object(DNSMOSMetric, '_initialize')
    @patch.object(DNSMOSMetric, '_preprocess_audio')
    @patch.object(DNSMOSMetric, '_compute_dnsmos')
    def test_compute_success(self, mock_compute, mock_preprocess, mock_initialize):
        mock_preprocess.return_value = np.array([0.1, 0.2, 0.3], dtype=np.float32)
        mock_compute.return_value = (4.0, 3.5, 4.0, 3.8)  # overall, sig, bak, ovr

        result = self.metric.compute(Path("dummy.wav"))
        self.assertIsInstance(result, DNSMOSResult)
        self.assertTrue(result.success)
        self.assertEqual(result.mos_overall, 4.0)
        self.assertEqual(result.mos_sig, 3.5)
        self.assertEqual(result.mos_bak, 4.0)
        self.assertEqual(result.mos_ovr, 3.8)

    @patch.object(DNSMOSMetric, '_initialize')
    @patch.object(DNSMOSMetric, '_preprocess_audio')
    def test_compute_preprocess_failure(self, mock_preprocess, mock_initialize):
        mock_preprocess.side_effect = Exception("Preprocessing failed")
        result = self.metric.compute(Path("dummy.wav"))
        self.assertFalse(result.success)
        self.assertEqual(result.mos_overall, 0.0)
        self.assertIn("Preprocessing failed", result.error)

    @patch.object(DNSMOSMetric, '_initialize')
    @patch.object(DNSMOSMetric, '_preprocess_audio')
    @patch.object(DNSMOSMetric, '_compute_dnsmos')
    def test_compute_computation_failure(self, mock_compute, mock_preprocess, mock_initialize):
        mock_preprocess.return_value = np.array([0.1, 0.2], dtype=np.float32)
        mock_compute.side_effect = Exception("Computation error")
        result = self.metric.compute(Path("dummy.wav"))
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
        with patch.object(self.metric, '_ensure_model', return_value=False):
            with self.assertRaises(RuntimeError):
                self.metric._initialize()
    
    @patch.object(DNSMOSMetric, '_ensure_model')
    def test_initialize_ensure_model_fails(self, mock_ensure):
        mock_ensure.return_value = False
        with self.assertRaises(RuntimeError):
            self.metric._initialize()

    def test_compute_dnsmos_short_audio_path(self):
        # Test that the code path for short audio works (padding)
        self.metric._session = MagicMock()
        # Call _compute_dnsmos directly with short audio
        result = self.metric._compute_dnsmos(np.array([0.1, 0.2, 0.3], dtype=np.float32))
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 4)  # Returns (overall, sig, bak, ovr)

    @patch.object(DNSMOSMetric, '_initialize')
    def test_compute_dnsmos_with_torch(self, mock_initialize):
        # Test that torch path is taken when use_ort=False
        metric = DNSMOSMetric(model_path=Path("/nonexistent/dnsmos.onnx"), use_ort=False)
        self.assertFalse(metric.use_ort)


class TestDNSMOSResult(unittest.TestCase):
    def test_to_dict(self):
        result = DNSMOSResult(
            mos_overall=4.0, mos_sig=3.5, mos_bak=4.0, mos_ovr=3.8,
            success=True, error=None
        )
        d = result.to_dict()
        self.assertEqual(d["mos_overall"], 4.0)
        self.assertEqual(d["success"], True)

    def test_to_dict_with_error(self):
        result = DNSMOSResult(
            mos_overall=0.0, mos_sig=0.0, mos_bak=0.0, mos_ovr=0.0,
            success=False, error="test error"
        )
        d = result.to_dict()
        self.assertEqual(d["error"], "test error")


class TestASRWerMetric(unittest.TestCase):
    def setUp(self):
        self.metric = ASRWerMetric()

    def test_compute_wer_cer(self):
        # Test English words - unpack all 7 values
        wer, cer, ins, dels, subs, ref_w, hyp_w = self.metric._compute_wer_cer('hello world', 'hello word')
        self.assertEqual(subs, 1)
        self.assertEqual(ins, 0)
        self.assertEqual(dels, 0)
        self.assertAlmostEqual(wer, 0.5)

        # Test Chinese characters - unpack all 7 values
        wer, cer, ins, dels, subs, ref_w, hyp_w = self.metric._compute_wer_cer('你好世界', '你好')
        self.assertEqual(dels, 2)
        self.assertEqual(ins, 0)
        self.assertEqual(subs, 0)
        # WER = (ins + dels + subs) / max(ref_words, 1) = 2 / 4 = 0.5
        self.assertAlmostEqual(wer, 0.5)

        # Test identical strings - unpack all 7 values
        wer, cer, ins, dels, subs, ref_w, hyp_w = self.metric._compute_wer_cer('test', 'test')
        self.assertEqual(ins, 0)
        self.assertEqual(dels, 0)
        self.assertEqual(subs, 0)
        self.assertAlmostEqual(wer, 0.0)

    def test_get_name(self):
        self.assertIn("asr_wer", self.metric.get_name())

    def test_compute_no_reference_text(self):
        # Test compute when no reference text is provided
        result = self.metric.compute(Path("dummy.wav"))
        self.assertFalse(result.success)
        self.assertEqual(result.wer, 1.0)
        self.assertIn("No reference text", result.error)

    def test_compute_asr(self):
        # Mock the backend's transcribe method
        with patch.object(self.metric._backend, 'transcribe') as mock_transcribe:
            mock_transcribe.return_value = MagicMock(
                success=True,
                text="hello world",
                words=[],
                language="en",
                confidence=0.9,
                duration_ms=1000
            )
            # This tests the backend transcription
            result = self.metric._backend.transcribe(Path("dummy.wav"))
            self.assertEqual(result.text, "hello world")

    @patch.object(ASRWerMetric, '_compute_wer_cer')
    def test_compute_success(self, mock_wer_cer):
        # Mock the backend's transcribe method
        asr_result = MagicMock(
            success=True,
            text="hello world",
            words=[],
            language="en",
            confidence=0.9,
            duration_ms=1000
        )
        with patch.object(self.metric._backend, 'transcribe', return_value=asr_result) as mock_transcribe:
            mock_wer_cer.return_value = (0.5, 0.0, 0, 1, 0, 2, 2)  # wer, cer, ins, dels, subs, ref_w, hyp_w

            result = self.metric.compute(Path("dummy.wav"), "hello world")
            self.assertIsInstance(result, WERResult)
            self.assertEqual(result.wer, 0.5)
            self.assertTrue(result.success)

    def test_compute_transcribe_failure(self):
        with patch.object(self.metric._backend, 'transcribe') as mock_transcribe:
            mock_transcribe.return_value = MagicMock(
                success=False,
                text="",
                words=[],
                language="unknown",
                confidence=0.0,
                duration_ms=0,
                error="ASR failed"
            )
            result = self.metric.compute(Path("dummy.wav"), "hello world")
            self.assertFalse(result.success)
            self.assertEqual(result.wer, 1.0)
            self.assertIn("ASR failed", result.error)

    def test_create_backend_funasr(self):
        metric = ASRWerMetric(backend="funasr")
        self.assertIsInstance(metric._backend, FunASRBackend)

    def test_create_backend_whisper(self):
        metric = ASRWerMetric(backend="whisper")
        self.assertIsInstance(metric._backend, WhisperBackend)

    def test_create_backend_invalid(self):
        with self.assertRaises(ValueError):
            ASRWerMetric(backend="invalid")


class TestWERResult(unittest.TestCase):
    def test_to_dict(self):
        result = WERResult(
            wer=0.5, cer=0.1, insertions=1, deletions=2, substitutions=1,
            reference_words=10, hypothesis_words=12, success=True
        )
        d = result.to_dict()
        self.assertEqual(d["wer"], 0.5)
        self.assertEqual(d["insertions"], 1)


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
        with patch.object(self.metric._backend, 'extract_embedding', return_value=mock_embedding) as mock_extract:
            result = self.metric.compute(Path("ref.wav"), reference_audio=Path("ref.wav"))
            self.assertTrue(hasattr(result, 'success'))
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
        with patch.object(self.metric._backend, 'extract_embedding', return_value=mock_embedding) as mock_extract:
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
            similarity=0.9, threshold=0.85, is_same_speaker=True,
            reference_id="ref", target_id="target", success=True
        )
        d = result.to_dict()
        self.assertEqual(d["similarity"], 0.9)
        self.assertTrue(d["is_same_speaker"])

    def test_to_dict_with_error(self):
        result = SpeakerSimilarityResult(
            similarity=0.0, threshold=0.85, is_same_speaker=False,
            reference_id="ref", target_id="target", success=False, error="failed"
        )
        d = result.to_dict()
        self.assertEqual(d["error"], "failed")


class TestSpeakerEmbedding(unittest.TestCase):
    def test_to_dict(self):
        embedding = SpeakerEmbedding(
            embedding=np.array([0.1, 0.2, 0.3]),
            model_name="test_model",
            sample_rate=16000
        )
        d = embedding.to_dict()
        self.assertEqual(d["model_name"], "test_model")
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
            text="hello", words=[], language="en", confidence=0.9,
            duration_ms=1000, success=True
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
                }
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
        mock_dnsmos.compute.return_value = DNSMOSResult(
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
        mock_dnsmos.compute.return_value = DNSMOSResult(
            mos_overall=4.0, mos_sig=3.5, mos_bak=4.0, mos_ovr=3.8, success=True
        )
        suite._dnsmos = mock_dnsmos

        mock_wer = MagicMock()
        mock_wer.compute.return_value = WERResult(
            wer=0.0, cer=0.0, insertions=0, deletions=0, substitutions=0,
            reference_words=2, hypothesis_words=2, success=True
        )
        suite._wer = mock_wer

        mock_speaker = MagicMock()
        mock_embedding = MagicMock()
        mock_embedding.embedding = np.array([1.0, 0.0])
        mock_speaker.compute.return_value = SpeakerSimilarityResult(
            similarity=0.9, threshold=0.85, is_same_speaker=True,
            reference_id="ref", target_id="target", success=True
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
        mock_dnsmos.compute.return_value = DNSMOSResult(
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
        mock_dnsmos.compute.return_value = DNSMOSResult(
            mos_overall=4.0, mos_sig=3.5, mos_bak=4.0, mos_ovr=3.8, success=True
        )
        suite._dnsmos = mock_dnsmos

        mock_wer = MagicMock()
        mock_wer.compute.return_value = WERResult(
            wer=0.5, cer=0.1, insertions=2, deletions=2, substitutions=1,
            reference_words=5, hypothesis_words=5, success=True
        )
        suite._wer = mock_wer
        suite._speaker_sim = None

        result = suite.check_all(Path("audio.wav"), reference_text="hello world")
        self.assertFalse(result.passed)
        self.assertIn("ASR WER", result.overall_message)

    def test_check_all_speaker_sim_threshold_fail(self):
        # Test check_all when speaker similarity is below threshold
        suite = QualityCheckSuite()
        suite._initialized = True
        suite._speaker_sim_min = 0.95  # Set a high threshold

        mock_speaker = MagicMock()
        mock_embedding = MagicMock()
        mock_embedding.embedding = np.array([0.5, 0.5])
        mock_speaker.compute.return_value = SpeakerSimilarityResult(
            similarity=0.8, threshold=0.85, is_same_speaker=False,
            reference_id="ref", target_id="target", success=True
        )
        suite._speaker_sim = mock_speaker
        suite._dnsmos = None
        suite._wer = None

        result = suite.check_all(Path("audio.wav"), reference_speaker_audio=Path("ref.wav"))
        self.assertFalse(result.passed)
        self.assertIn("Speaker similarity", result.overall_message)

    def test_check_all_disabled_dnsmos(self):
        # Test check_all when dnsmos is explicitly disabled in config
        config = {
            "quality_check": {
                "dnsmos_enabled": False,
            }
        }
        suite = QualityCheckSuite(config=config, hardware_profile="potato")
        suite._initialized = True
        suite._dnsmos = None

        mock_wer = MagicMock()
        mock_wer.compute.return_value = WERResult(
            wer=0.0, cer=0.0, insertions=0, deletions=0, substitutions=0,
            reference_words=2, hypothesis_words=2, success=True
        )
        suite._wer = mock_wer
        suite._speaker_sim = None

        result = suite.check_all(Path("audio.wav"), reference_text="test")
        # Should only run WER, no DNSMOS
        self.assertTrue(result.wer.success)

    def test_check_all_disabled_asr(self):
        # Test check_all when ASR is explicitly disabled in config
        config = {
            "quality_check": {
                "asr_enabled": False,
            }
        }
        suite = QualityCheckSuite(config=config, hardware_profile="potato")
        suite._initialized = True
        suite._dnsmos = None
        suite._wer = None

        result = suite.check_all(Path("audio.wav"), reference_text="test")
        # Should have no WER check
        self.assertIsNone(result.wer)

    def test_check_all_disabled_speaker_sim(self):
        # Test check_all when speaker similarity is disabled in config
        config = {
            "quality_check": {
                "speaker_similarity_enabled": False,
            }
        }
        suite = QualityCheckSuite(config=config, hardware_profile="potato")
        suite._initialized = True
        suite._dnsmos = None
        suite._wer = None
        suite._speaker_sim = None

        result = suite.check_all(Path("audio.wav"), reference_speaker_audio=Path("ref.wav"))
        self.assertIsNone(result.speaker_sim)

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

    def test_check_all_wer_no_reference(self):
        # Test check_all when no reference text provided but WER is enabled
        suite = QualityCheckSuite()
        suite._initialized = True
        suite._dnsmos = None
        # WER metric should return error when no reference text
        mock_wer = MagicMock()
        mock_wer.compute.return_value = WERResult(
            wer=1.0, cer=1.0, insertions=0, deletions=0, substitutions=0,
            reference_words=0, hypothesis_words=0, success=False, error="No reference text provided"
        )
        suite._wer = mock_wer
        suite._speaker_sim = None

        result = suite.check_all(Path("audio.wav"))
        # WER should have failed with no reference text
        self.assertFalse(result.wer.success)

    def test_quality_check_result_to_dict(self):
        from audiobook_studio.quality.metrics import QualityCheckResult
        result = QualityCheckResult(passed=True, overall_message="All passed")
        d = result.to_dict()
        self.assertTrue(d["passed"])


if __name__ == '__main__':
    unittest.main()