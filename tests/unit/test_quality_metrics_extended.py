"""Extended tests for metrics.py - branch coverage."""

import sys
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from audiobook_studio.quality.metrics import (
    ASRResult,
    ASRWerMetric,
    DNSMOSMetric,
    DNSMOSResult,
    QualityCheckResult,
    SpeakerEmbedding,
    SpeakerSimilarityResult,
    WERResult,
)


class TestDNSMOSMetric:
    """Tests for DNSMOSMetric compute functions."""

    def setup_method(self):
        self.metric = DNSMOSMetric(mock_mode=True)

    def test_compute_mock_mode(self):
        """DNSMOS compute in mock mode returns fixed scores."""
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            tmp_path = f.name
        try:
            result = self.metric.compute(tmp_path)
            assert result == 4.2  # mock score
        finally:
            os.unlink(tmp_path)

    def test_compute_detailed_mock_mode(self):
        """DNSMOS compute_detailed in mock mode returns fixed result."""
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            tmp_path = f.name
        try:
            result = self.metric.compute_detailed(tmp_path)
            assert result.mos_overall == 4.2
            assert result.mos_sig == 4.1
            assert result.mos_bak == 4.3
            assert result.mos_ovr == 4.2
            assert result.success is True
        finally:
            os.unlink(tmp_path)

    def test_compute_with_nonexistent_file(self):
        """DNSMOS compute with nonexistent file returns 0.0."""
        from pathlib import Path
        result = self.metric.compute(Path("/nonexistent/file.wav"))
        assert result == 0.0


class TestASRWerMetric:
    """Tests for ASRWerMetric compute functions."""

    def setup_method(self):
        self.metric = ASRWerMetric(mock_mode=True, reference_text="测试参考文本")

    def test_compute_wer_mock_mode(self):
        """ASR WER compute in mock mode returns fixed value."""
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            tmp_path = f.name
        try:
            result = self.metric.compute_wer(tmp_path)
            assert result == 0.0  # mock returns 0
        finally:
            os.unlink(tmp_path)

    def test_compute_wer_no_reference(self):
        """ASR WER compute without reference text returns 1.0."""
        metric_no_ref = ASRWerMetric(mock_mode=True, reference_text="")
        import tempfile
        import os
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            tmp_path = f.name
        try:
            result = metric_no_ref.compute_wer(tmp_path)
            assert result == 1.0  # no reference
        finally:
            os.unlink(tmp_path)

    def test_compute_wer_with_text(self):
        """ASR WER compute with text processes correctly."""
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            tmp_path = f.name
        try:
            result = self.metric.compute(tmp_path)
            assert result.success or result.wer == 1.0
        finally:
            os.unlink(tmp_path)


class TestWERResult:
    """Tests for WERResult data class."""

    def test_wer_result_creation(self):
        """WERResult can be created and to_dict works."""
        result = WERResult(
            wer=0.15,
            cer=0.1,
            insertions=3,
            deletions=2,
            substitutions=1,
            reference_words=100,
            hypothesis_words=105,
            success=True,
        )
        assert result.wer == 0.15
        assert result.cer == 0.1
        assert result.insertions == 3
        assert result.deletions == 2
        assert result.substitutions == 1
        assert result.reference_words == 100
        assert result.hypothesis_words == 105
        assert result.success is True

        d = result.to_dict()
        assert d["wer"] == 0.15
        assert d["cer"] == 0.1
        assert d["insertions"] == 3
        assert d["deletions"] == 2
        assert d["substitutions"] == 1
        assert d["reference_words"] == 100
        assert d["hypothesis_words"] == 105
        assert d["success"] is True


class TestASRResult:
    """Tests for ASRResult data class edge cases."""

    def test_asr_result_minimal(self):
        """ASRResult with minimal fields."""
        result = ASRResult(
            text="hello",
            words=[],
            language="en",
            confidence=1.0,
            duration_ms=0.0,
            success=True,
        )
        assert result.text == "hello"
        assert result.language == "en"
        assert result.confidence == 1.0
        assert result.duration_ms == 0.0
        assert result.success is True


class TestDNSMOSResultEdgeCases:
    """Tests for DNSMOSResult edge cases."""

    def test_dnsmos_result_boundary_values(self):
        """DNSMOSResult with boundary MOS values."""
        result = DNSMOSResult(
            mos_overall=1.0,
            mos_sig=1.0,
            mos_bak=5.0,
            mos_ovr=3.0,
            success=True,
        )
        assert result.mos_overall == 1.0
        assert result.mos_sig == 1.0
        assert result.mos_bak == 5.0
        assert result.mos_ovr == 3.0

    def test_dnsmos_result_to_dict(self):
        """DNSMOSResult to_dict works correctly."""
        result = DNSMOSResult(4.5, 4.0, 5.0, 4.5, True, "test error")
        d = result.to_dict()
        assert d["mos_overall"] == 4.5
        assert d["mos_sig"] == 4.0
        assert d["mos_bak"] == 5.0
        assert d["mos_ovr"] == 4.5
        assert d["success"] is True
        assert d["error"] == "test error"


class TestQualityCheckResultEdgeCases:
    """Tests for QualityCheckResult with various combinations."""

    def test_quality_check_result_partial(self):
        """QualityCheckResult with partial results."""
        from audiobook_studio.quality.metrics import (
            DNSMOSResult,
            WERResult,
            SpeakerSimilarityResult,
        )
        result = QualityCheckResult(
            passed=False,
            dnsmos=DNSMOSResult(4.0, 4.0, 4.0, 4.0, True),
            wer=None,
            speaker_sim=SpeakerSimilarityResult(0.5, 0.8, True, "ref", "tgt", True),
            overall_message="Partial OK",
        )
        assert result.passed is False
        assert result.overall_message == "Partial OK"

    def test_quality_check_result_to_dict_partial(self):
        """QualityCheckResult to_dict with partial results."""
        from audiobook_studio.quality.metrics import (
            DNSMOSResult,
            WERResult,
            SpeakerSimilarityResult,
        )
        dnsmos = DNSMOSResult(4.0, 4.0, 4.0, 4.0, True)
        wer = WERResult(0.1, 0.05, 0, 0, 0, 10, 10, True)
        speaker_sim = SpeakerSimilarityResult(0.85, 0.8, True, "ref1", "tgt1", True, None)
        result = QualityCheckResult(
            passed=True,
            dnsmos=dnsmos,
            wer=wer,
            speaker_sim=speaker_sim,
            overall_message="All good",
        )
        d = result.to_dict()
        assert d["passed"] is True
        assert d["dnsmos"] is not None
        assert d["wer"] is not None
        assert d["speaker_sim"] is not None
        assert d["overall_message"] == "All good"