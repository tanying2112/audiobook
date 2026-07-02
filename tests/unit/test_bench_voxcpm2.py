"""
Unit tests for VoxCPM2 benchmark module (Issue 0.4).

Tests cover:
  - Hardware detection output validity
  - VRAM projection calculations
  - RTF / throughput projection sanity checks
  - Edge-TTS simulation mode
  - Report generation (JSON + Markdown structure)
  - Acceptance criteria evaluation
"""

import json
import math
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.audiobook_studio.benchmarks.bench_voxcpm2 import (
    BenchmarkReport,
    HardwareProfile,
    TtsBenchmarkResult,
    VoxCPM2Projection,
    benchmark_edge_tts,
    build_acceptance_criteria,
    build_recommendations,
    build_summary,
    compute_voxcpm2_projection,
    detect_hardware,
    render_markdown_report,
    run_benchmark,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_hw_low() -> HardwareProfile:
    """低显存硬件（不满足要求）。"""
    return HardwareProfile(
        system="Darwin arm64",
        cpu_model="Intel Core i5-4690",
        cpu_cores=4,
        ram_gb=16.0,
        gpu_model="AMD Radeon R9 M295X",
        gpu_vram_gb=4.0,
        cuda_available=False,
        mps_available=False,
        metal_support=True,
        python_version="3.14.5",
        meets_int8_min=False,
        meets_fp16_min=False,
        recommended_mode="cpu_simulation",
    )


@pytest.fixture()
def sample_hw_mid() -> HardwareProfile:
    """中等显存硬件（满足 INT8 要求）。"""
    return HardwareProfile(
        system="Linux x86_64",
        cpu_model="Intel Core i9-13900K",
        cpu_cores=24,
        ram_gb=64.0,
        gpu_model="NVIDIA RTX 3080 10GB",
        gpu_vram_gb=10.0,
        cuda_available=True,
        mps_available=False,
        metal_support=False,
        python_version="3.11.0",
        meets_int8_min=True,
        meets_fp16_min=False,
        recommended_mode="int8_gpu",
    )


@pytest.fixture()
def sample_hw_high() -> HardwareProfile:
    """高显存硬件（满足 FP16 要求）。"""
    return HardwareProfile(
        system="Linux x86_64",
        cpu_model="AMD EPYC 7742",
        cpu_cores=64,
        ram_gb=256.0,
        gpu_model="NVIDIA A100 80GB",
        gpu_vram_gb=80.0,
        cuda_available=True,
        mps_available=False,
        metal_support=False,
        python_version="3.11.0",
        meets_int8_min=True,
        meets_fp16_min=True,
        recommended_mode="fp16_gpu",
    )


@pytest.fixture()
def sample_projection(sample_hw_low) -> VoxCPM2Projection:
    return compute_voxcpm2_projection(sample_hw_low)


@pytest.fixture()
def sample_tts_results() -> list:
    return [
        TtsBenchmarkResult(
            engine="edge_tts",
            text_length_chars=50,
            audio_duration_sec=8.0,
            synthesis_time_sec=1.6,
            rtf=0.2,
            throughput_cps=31.25,
            success=True,
        ),
        TtsBenchmarkResult(
            engine="edge_tts",
            text_length_chars=150,
            audio_duration_sec=24.0,
            synthesis_time_sec=4.2,
            rtf=0.175,
            throughput_cps=35.7,
            success=True,
        ),
        TtsBenchmarkResult(
            engine="edge_tts",
            text_length_chars=300,
            audio_duration_sec=48.0,
            synthesis_time_sec=9.0,
            rtf=0.188,
            throughput_cps=33.3,
            success=True,
        ),
    ]


# ---------------------------------------------------------------------------
# A. 硬件检测测试
# ---------------------------------------------------------------------------


class TestHardwareDetection:
    def test_detect_hardware_returns_profile(self):
        hw = detect_hardware()
        assert isinstance(hw, HardwareProfile)

    def test_detect_hardware_has_system(self):
        hw = detect_hardware()
        assert hw.system != ""

    def test_detect_hardware_has_cpu(self):
        hw = detect_hardware()
        assert hw.cpu_cores > 0

    def test_detect_hardware_has_ram(self):
        hw = detect_hardware()
        assert hw.ram_gb > 0

    def test_detect_hardware_recommended_mode_valid(self):
        hw = detect_hardware()
        assert hw.recommended_mode in ("cpu_simulation", "int8_gpu", "fp16_gpu")

    def test_meets_int8_consistent_with_vram(self):
        hw = detect_hardware()
        if hw.gpu_vram_gb >= 8.0:
            assert hw.meets_int8_min is True
        else:
            assert hw.meets_int8_min is False

    def test_meets_fp16_consistent_with_vram(self):
        hw = detect_hardware()
        if hw.gpu_vram_gb >= 16.0:
            assert hw.meets_fp16_min is True
        else:
            assert hw.meets_fp16_min is False


# ---------------------------------------------------------------------------
# B. VoxCPM2 显存推算测试
# ---------------------------------------------------------------------------


class TestVoxCPM2Projection:
    def test_fp16_vram_positive(self, sample_projection):
        assert sample_projection.fp16_vram_gb > 0

    def test_int8_vram_positive(self, sample_projection):
        assert sample_projection.int8_vram_gb > 0

    def test_fp32_vram_positive(self, sample_projection):
        assert sample_projection.fp32_vram_gb > 0

    def test_vram_ordering(self, sample_projection):
        """INT8 < FP16 < FP32 显存占用。"""
        assert sample_projection.int8_vram_gb < sample_projection.fp16_vram_gb
        assert sample_projection.fp16_vram_gb < sample_projection.fp32_vram_gb

    def test_fp16_vram_reasonable_range(self, sample_projection):
        """300M 参数 FP16 约 0.6 GB，加上 overhead 预计 1-4 GB。"""
        assert 0.5 < sample_projection.fp16_vram_gb < 5.0

    def test_int8_vram_reasonable_range(self, sample_projection):
        assert 0.3 < sample_projection.int8_vram_gb < 3.0

    def test_rtf_a100_positive(self, sample_projection):
        assert sample_projection.fp16_rtf_a100 > 0
        assert sample_projection.int8_rtf_a100 > 0

    def test_int8_faster_than_fp16(self, sample_projection):
        """INT8 推理应比 FP16 更快（更低 RTF）。"""
        assert sample_projection.int8_rtf_a100 < sample_projection.fp16_rtf_a100

    def test_rtx3090_slower_than_a100(self, sample_projection):
        """RTX 3090 RTF 应大于 A100（速度更慢）。"""
        assert sample_projection.fp16_rtf_3090 > sample_projection.fp16_rtf_a100

    def test_cpu_rtf_much_larger(self, sample_projection):
        """CPU 模式 RTF 应远大于 GPU（慢很多）。"""
        assert sample_projection.cpu_rtf_estimate > 5.0

    def test_throughput_a100_positive(self, sample_projection):
        assert sample_projection.fp16_throughput_cps_a100 > 0
        assert sample_projection.int8_throughput_cps_a100 > 0

    def test_int8_throughput_higher_than_fp16(self, sample_projection):
        """INT8 批量吞吐量应高于 FP16。"""
        assert sample_projection.int8_throughput_cps_a100 > sample_projection.fp16_throughput_cps_a100

    def test_notes_not_empty(self, sample_projection):
        assert len(sample_projection.notes) > 0

    def test_param_count_matches(self, sample_projection):
        assert sample_projection.param_count_m == 300.0

    def test_projection_high_hw(self, sample_hw_high):
        proj = compute_voxcpm2_projection(sample_hw_high)
        # 高显存硬件的推算数值应与低显存一致（推算基于模型架构，不受当前硬件影响）
        assert proj.fp16_vram_gb > 0
        assert proj.int8_vram_gb > 0


# ---------------------------------------------------------------------------
# C. Edge-TTS 模拟模式测试
# ---------------------------------------------------------------------------


class TestEdgeTtsBenchmark:
    def test_skip_tts_returns_simulated(self):
        results = benchmark_edge_tts(skip=True)
        assert len(results) == 3
        for r in results:
            assert r.engine == "edge_tts_simulated"
            assert r.rtf > 0
            assert r.success is True

    def test_skip_tts_rtf_reasonable(self):
        results = benchmark_edge_tts(skip=True)
        for r in results:
            assert 0.01 < r.rtf < 2.0

    def test_skip_tts_throughput_positive(self):
        results = benchmark_edge_tts(skip=True)
        for r in results:
            assert r.throughput_cps > 0

    def test_skip_tts_text_lengths_increasing(self):
        results = benchmark_edge_tts(skip=True)
        lengths = [r.text_length_chars for r in results]
        assert lengths[0] < lengths[1] < lengths[2]


# ---------------------------------------------------------------------------
# D. 报告生成测试
# ---------------------------------------------------------------------------


class TestBuildSummary:
    def test_summary_has_hardware_assessment(self, sample_hw_low, sample_projection, sample_tts_results):
        s = build_summary(sample_hw_low, sample_projection, sample_tts_results)
        assert "hardware_assessment" in s
        assert s["hardware_assessment"]["vram_gb"] == 4.0

    def test_summary_has_vram_footprint(self, sample_hw_low, sample_projection, sample_tts_results):
        s = build_summary(sample_hw_low, sample_projection, sample_tts_results)
        assert "voxcpm2_vram_footprint" in s
        assert s["voxcpm2_vram_footprint"]["fp16_gb"] == sample_projection.fp16_vram_gb

    def test_summary_has_rtf_projections(self, sample_hw_low, sample_projection, sample_tts_results):
        s = build_summary(sample_hw_low, sample_projection, sample_tts_results)
        assert "voxcpm2_rtf_projections" in s

    def test_summary_edge_tts_avg_rtf(self, sample_hw_low, sample_projection, sample_tts_results):
        s = build_summary(sample_hw_low, sample_projection, sample_tts_results)
        avg_rtf = s["baseline_edge_tts"]["avg_rtf"]
        assert avg_rtf is not None
        assert avg_rtf > 0

    def test_summary_empty_tts_results(self, sample_hw_low, sample_projection):
        s = build_summary(sample_hw_low, sample_projection, [])
        assert s["baseline_edge_tts"]["avg_rtf"] is None


class TestBuildRecommendations:
    def test_low_hw_contains_urgent_warning(self, sample_hw_low, sample_projection):
        recs = build_recommendations(sample_hw_low, sample_projection)
        assert any("紧急" in r or "不满足" in r for r in recs)

    def test_high_hw_no_urgent_warning(self, sample_hw_high, sample_projection):
        proj_high = compute_voxcpm2_projection(sample_hw_high)
        recs = build_recommendations(sample_hw_high, proj_high)
        assert not any("紧急" in r for r in recs)

    def test_recommendations_not_empty(self, sample_hw_low, sample_projection):
        recs = build_recommendations(sample_hw_low, sample_projection)
        assert len(recs) >= 3


class TestAcceptanceCriteria:
    def test_all_criteria_met_with_valid_data(self, sample_hw_low, sample_projection, sample_tts_results):
        criteria = build_acceptance_criteria(sample_hw_low, sample_projection, sample_tts_results)
        assert criteria["vram_footprint_documented"] is True
        assert criteria["rtf_benchmarked"] is True
        assert criteria["batch_throughput_documented"] is True
        assert criteria["hardware_assessment_complete"] is True
        assert criteria["report_generated"] is True

    def test_baseline_tts_benchmarked_with_success(self, sample_hw_low, sample_projection, sample_tts_results):
        criteria = build_acceptance_criteria(sample_hw_low, sample_projection, sample_tts_results)
        assert criteria["baseline_tts_benchmarked"] is True

    def test_baseline_tts_false_all_failed(self, sample_hw_low, sample_projection):
        failed_results = [TtsBenchmarkResult(engine="edge_tts", success=False, error="timeout")]
        criteria = build_acceptance_criteria(sample_hw_low, sample_projection, failed_results)
        assert criteria["baseline_tts_benchmarked"] is False


class TestMarkdownReport:
    @pytest.fixture()
    def full_report(self, sample_hw_low, sample_projection, sample_tts_results) -> BenchmarkReport:
        import datetime

        summary = build_summary(sample_hw_low, sample_projection, sample_tts_results)
        recs = build_recommendations(sample_hw_low, sample_projection)
        criteria = build_acceptance_criteria(sample_hw_low, sample_projection, sample_tts_results)
        return BenchmarkReport(
            timestamp=datetime.datetime.now().isoformat(),
            hardware=sample_hw_low,
            edge_tts_results=sample_tts_results,
            voxcpm2_projection=sample_projection,
            summary=summary,
            recommendations=recs,
            acceptance_criteria_met=criteria,
        )

    def test_markdown_contains_title(self, full_report):
        md = render_markdown_report(full_report)
        assert "VoxCPM2" in md

    def test_markdown_contains_vram_table(self, full_report):
        md = render_markdown_report(full_report)
        assert "FP16" in md and "INT8" in md

    def test_markdown_contains_rtf_section(self, full_report):
        md = render_markdown_report(full_report)
        assert "RTF" in md

    def test_markdown_contains_throughput(self, full_report):
        md = render_markdown_report(full_report)
        assert "吞吐量" in md

    def test_markdown_contains_recommendations(self, full_report):
        md = render_markdown_report(full_report)
        assert "建议" in md

    def test_markdown_contains_criteria_section(self, full_report):
        md = render_markdown_report(full_report)
        assert "验收标准" in md


# ---------------------------------------------------------------------------
# E. 完整 run_benchmark 集成测试
# ---------------------------------------------------------------------------


class TestRunBenchmark:
    def test_run_benchmark_skip_tts_returns_report(self):
        report = run_benchmark(skip_tts=True)
        assert isinstance(report, BenchmarkReport)

    def test_run_benchmark_hardware_not_empty(self):
        report = run_benchmark(skip_tts=True)
        assert report.hardware.system != ""
        assert report.hardware.cpu_cores > 0

    def test_run_benchmark_projection_valid(self):
        report = run_benchmark(skip_tts=True)
        assert report.voxcpm2_projection.fp16_vram_gb > 0
        assert report.voxcpm2_projection.int8_vram_gb > 0

    def test_run_benchmark_tts_results_present(self):
        report = run_benchmark(skip_tts=True)
        assert len(report.edge_tts_results) > 0

    def test_run_benchmark_acceptance_criteria_set(self):
        report = run_benchmark(skip_tts=True)
        assert len(report.acceptance_criteria_met) > 0

    def test_run_benchmark_report_serializable(self):
        """报告必须可序列化为 JSON。"""
        from dataclasses import asdict

        report = run_benchmark(skip_tts=True)
        data = asdict(report)
        json_str = json.dumps(data, ensure_ascii=False)
        assert len(json_str) > 100

    def test_run_benchmark_markdown_renderable(self):
        report = run_benchmark(skip_tts=True)
        md = render_markdown_report(report)
        assert len(md) > 500
