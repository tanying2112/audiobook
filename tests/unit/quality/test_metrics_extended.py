import sys
import os
from unittest.mock import MagicMock, patch, AsyncMock
import unittest
import numpy as np

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

from audiobook_studio.quality.metrics import (
    DNSMOSMetric,
    ASRWerMetric,
    SpeakerSimilarityMetric,
    DNSMOSResult,
    WERResult,
    SpeakerSimilarityResult,
)

class TestDNSMOSMetric(unittest.TestCase):
    def setUp(self):
        self.metric = DNSMOSMetric()

    @patch.object(DNSMOSMetric, '_preprocess_audio')
    @patch.object(DNSMOSMetric, '_compute_dnsmos')
    def test_compute_success(self, mock_compute, mock_preprocess):
        # Mock preprocessing to return a dummy audio array
        mock_preprocess.return_value = np.array([0.1, 0.2, 0.3], dtype=np.float32)
        # Mock the computation to return fixed MOS scores
        mock_compute.return_value = (4.0, 3.5, 4.0, 3.8)  # overall, sig, bak, ovr

        result = self.metric.compute("dummy.wav")
        self.assertIsInstance(result, DNSMOSResult)
        self.assertTrue(result.success)
        self.assertEqual(result.mos_overall, 4.0)
        self.assertEqual(result.mos_sig, 3.5)
        self.assertEqual(result.mos_bak, 4.0)
        self.assertEqual(result.mos_ovr, 3.8)

    @patch.object(DNSMOSMetric, '_preprocess_audio')
    def test_compute_preprocess_failure(self, mock_preprocess):
        mock_preprocess.side_effect = Exception("Preprocessing failed")
        result = self.metric.compute("dummy.wav")
        self.assertFalse(result.success)
        self.assertEqual(result.mos_overall, 0.0)
        self.assertIn("Preprocessing failed", result.error)

    @patch.object(DNSMOSMetric, '_preprocess_audio')
    @patch.object(DNSMOSMetric, '_compute_dnsmos')
    def test_compute_computation_failure(self, mock_compute, mock_preprocess):
        mock_preprocess.return_value = np.array([0.1, 0.2], dtype=np.float32)
        mock_compute.side_effect = Exception("Computation error")
        result = self.metric.compute("dummy.wav")
        self.assertFalse(result.success)
        self.assertEqual(result.mos_overall, 0.0)
        self.assertIn("Computation error", result.error)

    def test_ensure_model_success(self):
        with patch.object(self.metric, '_ensure_model', return_value=True):
            with patch.object(self.metric, '_initialize'):
                self.metric._initialize()
                self.assertTrue(self.metric._initialized)

    def test_ensure_model_failure(self):
        with patch.object(self.metric, '_ensure_model', return_value=False):
            with self.assertRaises(RuntimeError):
                self.metric._initialize()

class TestASRWerMetric(unittest.TestCase):
    def setUp(self):
        self.metric = ASRWerMetric()

    def test_compute_wer_cer(self):
        # Test English words
        wer, cer, ins, dels, subs, ref_w, hyp_w = self.metric._compute_wer_cer('hello world', 'hello word')
        self.assertEqual(subs, 1)
        self.assertEqual(ins, 0)
        self.assertEqual(dels, 0)
        self.assertAlmostEqual(wer, 0.5)

        # Test Chinese characters
        wer, cer, ins, dels, subs = self.metric._compute_wer_cer('你好世界', '你好')
        self.assertEqual(dels, 2)
        self.assertEqual(ins, 0)
        self.assertEqual(subs, 0)
        self.assertAlmostEqual(wer, 1.0)

        # Test identical strings
        wer, cer, ins, dels, subs = self.metric._compute_wer_cer('test', 'test')
        self.assertEqual(ins, 0)
        self.assertEqual(dels, 0)
        self.assertEqual(subs, 0)
        self.assertAlmostEqual(wer, 0.0)

    @patch('audiobook_studio.quality.metrics.whisper')
    @patch.object(ASRWerMetric, '_load_audio')
    def test_compute_asr(self, mock_load_audio, mock_whisper):
        # Mock the whisper model and its transcribe method
        mock_model = MagicMock()
        mock_model.transcribe.return_value = {"text": "hello world"}
        mock_whisper.load_model.return_value = mock_model

        # Mock _load_audio to return a dummy audio array and sample rate
        mock_load_audio.return_value = (np.array([0.1, 0.2], dtype=np.float32), 16000)

        text = self.metric._compute_asr("dummy.wav")
        self.assertEqual(text, "hello world")

    @patch.object(ASRWerMetric, '_load_audio')
    @patch.object(ASRWerMetric, '_compute_asr')
    @patch.object(ASRWerMetric, '_compute_wer_cer')
    def test_compute(self, mock_wer_cer, mock_asr, mock_load_audio):
        mock_load_audio.return_value = (np.array([0.1, 0.2], dtype=np.float32), 16000)
        mock_asr.return_value = "hello world"
        mock_wer_cer.return_value = (0.5, 0.0, 0, 1, 0, 2, 2)  # wer, cer, ins, dels, subs, ref_w, hyp_w

        result = self.metric.compute("dummy.wav", "hello world")
        self.assertIsInstance(result, WERResult)
        self.assertEqual(result.wer, 0.5)
        self.assertTrue(result.success)

    @patch.object(ASRWerMetric, '_load_audio')
    @patch.object(ASRWerMetric, '_compute_asr')
    def test_compute_asr_failure(self, mock_asr, mock_load_audio):
        mock_load_audio.return_value = (np.array([0.1, 0.2], dtype=np.float32), 16000)
        mock_asr.side_effect = Exception("ASR failed")
        result = self.metric.compute("dummy.wav", "hello world")
        self.assertFalse(result.success)
        self.assertEqual(result.wer, 0.0)
        self.assertIn("ASR failed", result.error)

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

    @patch('audiobook_studio.quality.metrics.torchaudio')
    @patch('audiobook_studio.quality.metrics.torch')
    def test_get_embedding(self, mock_torch, mock_torchaudio):
        # Mock the torchaudio.load to return a waveform and sample rate
        mock_waveform = MagicMock()
        mock_torchaudio.load.return_value = (mock_waveform, 16000)
        
        # Mock torch tensor operations if needed
        mock_torch.tensor.return_value = mock_waveform
        
        # Mock the model's encode_batch method
        mock_model = MagicMock()
        mock_model.encode_batch.return_value = [[0.1, 0.2, 0.3]]
        
        # Set the encoder on the metric instance
        self.metric.encoder = mock_model

        embedding = self.metric._get_embedding("dummy.wav")
        self.assertEqual(embedding, [0.1, 0.2, 0.3])

    @patch.object(SpeakerSimilarityMetric, '_get_embedding')
    @patch.object(SpeakerSimilarityMetric, '_cosine_similarity')
    def test_compute(self, mock_cos, mock_emb):
        mock_emb.side_effect = [[0.1, 0.2], [0.1, 0.2]]
        mock_cos.return_value = 0.95

        result = self.metric.compute("ref.wav", "hyp.wav")
        self.assertIsInstance(result, SpeakerSimilarityResult)
        self.assertEqual(result.similarity, 0.95)
        self.assertTrue(result.success)

    @patch.object(SpeakerSimilarityMetric, '_get_embedding')
    @patch.object(SpeakerSimilarityMetric, '_cosine_similarity')
    def test_compute_embedding_failure(self, mock_cos, mock_emb):
        mock_emb.side_effect = Exception("Embedding failed")
        result = self.metric.compute("ref.wav", "hyp.wav")
        self.assertFalse(result.success)
        self.assertEqual(result.similarity, 0.0)
        self.assertIn("Embedding failed", result.error)

if __name__ == '__main__':
    unittest.main()
