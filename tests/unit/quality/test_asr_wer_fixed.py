import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# Mock litellm as a package to avoid network calls and import errors
mock_litellm = types.ModuleType('litellm')
mock_litellm._logging = types.ModuleType('litellm._logging')
sys.modules['litellm'] = mock_litellm
sys.modules['litellm._logging'] = mock_litellm._logging

# Mock other heavy dependencies
sys.modules['torch'] = MagicMock()
sys.modules['torchaudio'] = MagicMock()
sys.modules['funasr'] = MagicMock()
sys.modules['whisper'] = MagicMock()
sys.modules['faster_whisper'] = MagicMock()
sys.modules['onnxruntime'] = MagicMock()
sys.modules['speechbrain'] = MagicMock()

# Now we can import the module
from src.audiobook_studio.quality.metrics import ASRWerMetric, ASRResult, WERResult

class TestASRWerMetric(unittest.TestCase):
    def setUp(self):
        self.reference = "hello world"
        self.metric = ASRWerMetric(backend='funasr', model_name='dummy', device='cpu', reference_text=self.reference)

    def _mock_backend_success(self, transcribed_text):
        with patch('src.audiobook_studio.quality.metrics.FunASRBackend') as MockBackend:
            instance = MockBackend.return_value
            instance.transcribe.return_value = ASRResult(
                text=transcribed_text, words=[], language='en', confidence=0.9,
                duration_ms=1000, success=True
            )
            self.metric._backend = instance
            return MockBackend

    def test_compute_no_reference(self):
        metric = ASRWerMetric(backend='funasr', model_name='dummy', device='cpu')
        result = metric.compute('/fake.wav', reference_text=None)
        self.assertFalse(result.success)
        self.assertEqual(result.wer, 1.0)
        self.assertIn('No reference text', result.error)

    def test_compute_backend_failure(self):
        with patch('src.audiobook_studio.quality.metrics.FunASRBackend') as MockBackend:
            instance = MockBackend.return_value
            instance.transcribe.return_value = ASRResult(
                text='', words=[], language='unknown', confidence=0.0,
                duration_ms=0, success=False, error='model not found'
            )
            self.metric._backend = instance
            result = self.metric.compute('/fake.wav', reference_text='hello')
        self.assertFalse(result.success)
        self.assertEqual(result.wer, 1.0)
        self.assertIn('model not found', result.error)

    def test_compute_success(self):
        with self._mock_backend_success('hello world') as _:
            result = self.metric.compute('/fake.wav', reference_text=self.reference)
        self.assertTrue(result.success)
        self.assertEqual(result.wer, 0.0)
        self.assertEqual(result.cer, 0.0)
        self.assertEqual(result.insertions, 0)
        self.assertEqual(result.deletions, 0)
        self.assertEqual(result.substitutions, 0)
        self.assertEqual(result.reference_words, 2)
        self.assertEqual(result.hypothesis_words, 2)

    def test_compute_wer_substitution(self):
        with self._mock_backend_success('hello word') as _:
            result = self.metric.compute('/fake.wav', reference_text=self.reference)
        self.assertTrue(result.success)
        self.assertEqual(result.substitutions, 1)
        self.assertEqual(result.insertions, 0)
        self.assertEqual(result.deletions, 0)
        self.assertEqual(result.reference_words, 2)
        self.assertEqual(result.hypothesis_words, 2)
        self.assertAlmostEqual(result.wer, 0.5)

    def test_compute_wer_insertion(self):
        with self._mock_backend_success('hello a world') as _:
            result = self.metric.compute('/fake.wav', reference_text=self.reference)
        self.assertTrue(result.success)
        self.assertEqual(result.insertions, 1)
        self.assertEqual(result.deletions, 0)
        self.assertEqual(result.substitutions, 0)
        self.assertAlmostEqual(result.wer, 0.5)

    def test_compute_wer_deletion(self):
        with self._mock_backend_success('hello') as _:
            result = self.metric.compute('/fake.wav', reference_text=self.reference)
        self.assertTrue(result.success)
        self.assertEqual(result.deletions, 1)
        self.assertEqual(result.insertions, 0)
        self.assertEqual(result.substitutions, 0)
        self.assertAlmostEqual(result.wer, 0.5)

    def test_compute_wer_cer_direct(self):
        m = self.metric
        # English tokenization (space)
        # Identical
        wer, cer, ins, dels, subs, ref_w, hyp_w = m._compute_wer_cer('hello world', 'hello world')
        self.assertEqual((wer, cer, ins, dels, subs), (0.0, 0.0, 0, 0, 0))
        # Substitution
        wer, cer, ins, dels, subs, ref_w, hyp_w = m._compute_wer_cer('hello world', 'hello word')
        self.assertEqual(subs, 1)
        self.assertEqual(ins, 0)
        self.assertEqual(dels, 0)
        self.assertAlmostEqual(wer, 0.5)
        # Insertion
        wer, cer, ins, dels, subs, ref_w, hyp_w = m._compute_wer_cer('hello world', 'hello awesome world')
        self.assertEqual(ins, 1)
        self.assertEqual(dels, 0)
        self.assertEqual(subs, 0)
        self.assertAlmostEqual(wer, 0.5)
        # Deletion
        wer, cer, ins, dels, subs, ref_w, hyp_w = m._compute_wer_cer('hello world', 'hello')
        self.assertEqual(dels, 1)
        self.assertEqual(ins, 0)
        self.assertEqual(subs, 0)
        self.assertAlmostEqual(wer, 0.5)
        # Mixed: one substitution, one insertion
        wer, cer, ins, dels, subs, ref_w, hyp_w = m._compute_wer_cer('the cat sat', 'the cat sat on the mat')
        self.assertEqual(ins, 3)
        self.assertEqual(dels, 0)
        self.assertEqual(subs, 0)
        self.assertAlmostEqual(wer, 1.0)
        # Chinese tokenization (by character)
        wer, cer, ins, dels, subs, ref_w, hyp_w = m._compute_wer_cer('你好世界', '你好')
        self.assertEqual(dels, 2)
        self.assertEqual(ins, 0)
        self.assertEqual(subs, 0)
        self.assertAlmostEqual(wer, 0.5)
        self.assertEqual(ref_w, 4)
        self.assertEqual(hyp_w, 2)

if __name__ == '__main__':
    unittest.main()
