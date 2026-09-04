"""
Test SpeakerSimilarityMetric dependency handling — 红线A (P2.13 §2.1).

旧契约 (已废弃): 依赖缺失 -> _create_backend 静默退化为 mock_mode=True -> compute 返回
    成功的确定性伪嵌入 (success=True) -> 验收被伪造为"同一说话人". 这是红线A地雷.

新契约 (P2.13): _create_backend 不再因依赖缺失自动置 mock_mode=True.
    - 显式传 mock_mode=True 才走伪嵌入 (测试专用, 真模型不加载).
    - 依赖缺失且未显式 mock -> 后端以真模型模式构造 (不预加载), extract_embedding ->
      _initialize 抛 RuntimeError (依赖 ImportError), compute 捕获 -> success=False,
      上游 orchestrator 据此诚实跳过, 而非伪报同一说话人.
"""

import unittest
from pathlib import Path
from unittest.mock import patch

from src.audiobook_studio.quality.metrics import (
    ECAPATDNNBackend,
    SpeakerSimilarityMetric,
    WavLMBackend,
)


class TestSpeakerSimilarityDependencies(unittest.TestCase):
    """P2.13 §2.1: 不静默退化为 mock; 依赖缺失走诚实降级 (RuntimeError -> success=False)."""

    @patch("src.audiobook_studio.quality.metrics._speechbrain_available", True)
    @patch("src.audiobook_studio.quality.metrics._torch_available", True)
    @patch("src.audiobook_studio.quality.metrics._torchaudio_available", True)
    def test_ecapa_tdnn_backend_mock_mode_false_when_speechbrain_available(self):
        """依赖齐 -> mock_mode=False (真模型)."""
        metric = SpeakerSimilarityMetric(backend="ecapa_tdnn")
        self.assertIsInstance(metric._backend, ECAPATDNNBackend)
        self.assertFalse(metric._backend.mock_mode)

    @patch("src.audiobook_studio.quality.metrics._speechbrain_available", False)
    @patch("src.audiobook_studio.quality.metrics._torch_available", True)
    @patch("src.audiobook_studio.quality.metrics._torchaudio_available", True)
    def test_ecapa_tdnn_backend_NOT_mock_when_speechbrain_unavailable(self):
        """红线A: 依赖缺失 (speechbrain 缺) -> 不静默退化为 mock; mock_mode 保持 False.

        compute 时由 _initialize 抛 RuntimeError -> success=False (诚实降级), 不伪报.
        """
        metric = SpeakerSimilarityMetric(backend="ecapa_tdnn")
        self.assertIsInstance(metric._backend, ECAPATDNNBackend)
        self.assertFalse(metric._backend.mock_mode)

    def test_ecapa_tdnn_backend_explicit_mock_mode_true_stays_mock(self):
        """显式 mock_mode=True -> 保留 mock (测试专用真入口)."""
        metric = SpeakerSimilarityMetric(backend="ecapa_tdnn", mock_mode=True)
        self.assertIsInstance(metric._backend, ECAPATDNNBackend)
        self.assertTrue(metric._backend.mock_mode)

    def test_ecapa_tdnn_compute_returns_error_when_dep_missing_and_not_mock(self):
        """红线A 端到端: 依赖缺失且非 mock -> compute 诚实返回 success=False, 不伪嵌入.

        不信 _initialize 真抛 (依赖真未装/已装难控), 直接 mock 让 _initialize 抛
        RuntimeError 模拟"依赖缺"场景, 验证 compute 捕获并降级 (非 success=True 伪造).
        """
        metric = SpeakerSimilarityMetric(backend="ecapa_tdnn")
        with patch.object(
            metric._backend,
            "_initialize",
            side_effect=RuntimeError("SpeechBrain not installed. Install with: pip install speechbrain"),
        ):
            result = metric.compute(Path("target.wav"), reference_audio=Path("ref.wav"))
        self.assertFalse(result.success)
        self.assertEqual(result.similarity, 0.0)
        self.assertFalse(result.is_same_speaker)
        self.assertIn("SpeechBrain not installed", result.error)

    @patch("src.audiobook_studio.quality.metrics._torch_available", True)
    @patch("src.audiobook_studio.quality.metrics._torchaudio_available", True)
    @patch("src.audiobook_studio.quality.metrics._transformers_available", True)
    def test_wavlm_backend_mock_mode_false_when_torch_and_torchaudio_available(self):
        """依赖齐 -> mock_mode=False (真模型)."""
        metric = SpeakerSimilarityMetric(backend="wavlm_large")
        self.assertIsInstance(metric._backend, WavLMBackend)
        self.assertFalse(metric._backend.mock_mode)

    @patch("src.audiobook_studio.quality.metrics._torch_available", False)
    @patch("src.audiobook_studio.quality.metrics._torchaudio_available", True)
    @patch("src.audiobook_studio.quality.metrics._transformers_available", True)
    def test_wavlm_backend_NOT_mock_when_torch_unavailable(self):
        """红线A: torch 缺 -> 不静默退化为 mock; mock_mode 保持 False."""
        metric = SpeakerSimilarityMetric(backend="wavlm_large")
        self.assertIsInstance(metric._backend, WavLMBackend)
        self.assertFalse(metric._backend.mock_mode)

    @patch("src.audiobook_studio.quality.metrics._torch_available", True)
    @patch("src.audiobook_studio.quality.metrics._torchaudio_available", False)
    @patch("src.audiobook_studio.quality.metrics._transformers_available", True)
    def test_wavlm_backend_NOT_mock_when_torchaudio_unavailable(self):
        """红线A: torchaudio 缺 -> 不静默退化为 mock; mock_mode 保持 False."""
        metric = SpeakerSimilarityMetric(backend="wavlm_large")
        self.assertIsInstance(metric._backend, WavLMBackend)
        self.assertFalse(metric._backend.mock_mode)

    @patch("src.audiobook_studio.quality.metrics._torch_available", False)
    @patch("src.audiobook_studio.quality.metrics._torchaudio_available", False)
    @patch("src.audiobook_studio.quality.metrics._transformers_available", False)
    def test_wavlm_backend_NOT_mock_when_all_unavailable(self):
        """红线A: torch+torchaudio+transformers 全缺 -> 不静默退化为 mock; mock_mode 保持 False."""
        metric = SpeakerSimilarityMetric(backend="wavlm_large")
        self.assertIsInstance(metric._backend, WavLMBackend)
        self.assertFalse(metric._backend.mock_mode)

    def test_wavlm_backend_explicit_mock_mode_true_stays_mock(self):
        """显式 mock_mode=True -> 保留 mock (测试专用真入口)."""
        metric = SpeakerSimilarityMetric(backend="wavlm_large", mock_mode=True)
        self.assertIsInstance(metric._backend, WavLMBackend)
        self.assertTrue(metric._backend.mock_mode)

    def test_wavlm_compute_returns_error_when_dep_missing_and_not_mock(self):
        """红线A 端到端: 依赖缺失且非 mock -> compute 诚实返回 success=False."""
        metric = SpeakerSimilarityMetric(backend="wavlm_large")
        with patch.object(
            metric._backend,
            "_initialize",
            side_effect=RuntimeError(
                "transformers or torch not installed. Install with: pip install transformers torch torchaudio"
            ),
        ):
            result = metric.compute(Path("target.wav"), reference_audio=Path("ref.wav"))
        self.assertFalse(result.success)
        self.assertEqual(result.similarity, 0.0)
        self.assertFalse(result.is_same_speaker)
        self.assertIn("transformers or torch not installed", result.error)


if __name__ == "__main__":
    unittest.main()
