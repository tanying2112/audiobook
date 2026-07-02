"""Tests for benchmarks module coverage."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestBenchCost:
    """Test bench_cost module functions."""

    def test_parse_args(self):
        """Test parse_args function."""
        from src.audiobook_studio.benchmarks.bench_cost import parse_args

        with patch("sys.argv", ["test", "--mock", "--stages", "extract", "analyze"]):
            args = parse_args()
            assert args.mock is True
            assert "extract" in args.stages

    def test_load_baseline_missing_file(self):
        """Test load_baseline with missing file."""
        from src.audiobook_studio.benchmarks.bench_cost import load_baseline

        result = load_baseline("/nonexistent/path.json")
        assert result is None

    def test_load_baseline_valid(self, tmp_path):
        """Test load_baseline with valid file."""
        from src.audiobook_studio.benchmarks.bench_cost import load_baseline

        baseline_file = tmp_path / "baseline.json"
        baseline_file.write_text('{"cost_usd": {"extract": 0.01}}')
        result = load_baseline(str(baseline_file))
        assert result == {"extract": 0.01}

    def test_save_baseline(self, tmp_path):
        """Test save_baseline function."""
        from src.audiobook_studio.benchmarks.bench_cost import save_baseline

        output_file = tmp_path / "output.json"
        save_baseline({"extract": 0.01}, str(output_file))
        assert output_file.exists()

    def test_measure_stage_cost_mock(self):
        """Test measure_stage_cost in mock mode."""
        from src.audiobook_studio.benchmarks.bench_cost import measure_stage_cost

        with patch("time.sleep"):
            cost = measure_stage_cost("extract", mock=True)
            assert isinstance(cost, float)
            assert cost > 0

    def test_measure_stage_cost_all_stages(self):
        """Test measure_stage_cost for all stages."""
        from src.audiobook_studio.benchmarks.bench_cost import measure_stage_cost

        stages = ["extract", "analyze", "annotate", "edit", "synthesize", "quality"]
        with patch("time.sleep"):
            for stage in stages:
                cost = measure_stage_cost(stage, mock=True)
                assert isinstance(cost, float)

    def test_get_test_data_for_stage(self):
        """Test _get_test_data_for_stage function."""
        from src.audiobook_studio.benchmarks.bench_cost import _get_test_data_for_stage

        data = _get_test_data_for_stage("extract")
        assert "file_path" in data

    def test_evaluate_performance_no_baseline(self):
        """Test evaluate_performance without baseline."""
        from src.audiobook_studio.benchmarks.bench_cost import evaluate_performance

        current = {"extract": 0.01}
        passed, issues = evaluate_performance(current, None, 110.0)
        assert passed is True
        assert issues == []

    def test_evaluate_performance_with_regression(self):
        """Test evaluate_performance with cost regression."""
        from src.audiobook_studio.benchmarks.bench_cost import evaluate_performance

        current = {"extract": 0.02}
        baseline = {"extract": 0.01}
        passed, issues = evaluate_performance(current, baseline, 110.0)
        assert passed is False
        assert len(issues) == 1

    def test_main_mock_mode(self):
        """Test main function in mock mode."""
        from src.audiobook_studio.benchmarks.bench_cost import main

        with patch("sys.argv", ["test", "--mock", "--stages", "extract"]):
            with patch("sys.exit") as mock_exit:
                with patch("time.sleep"):
                    main()


class TestBenchLatency:
    """Test bench_latency module functions."""

    def test_parse_args(self):
        """Test parse_args function."""
        from src.audiobook_studio.benchmarks.bench_latency import parse_args

        with patch("sys.argv", ["test", "--mock"]):
            args = parse_args()
            assert args.mock is True

    def test_measure_latency_mock(self):
        """Test measure_latency in mock mode."""
        from src.audiobook_studio.benchmarks.bench_latency import measure_stage_latency

        with patch("time.sleep"):
            latency = measure_stage_latency("extract", mock=True)
            assert isinstance(latency, float)

    def test_main_mock_mode(self):
        """Test main function in mock mode."""
        from src.audiobook_studio.benchmarks.bench_latency import main

        with patch("sys.argv", ["test", "--mock"]):
            with patch("sys.exit") as mock_exit:
                with patch("time.sleep"):
                    main()


class TestBenchVoxcpm2:
    """Test bench_voxcpm2 module functions."""

    def test_parse_args(self):
        """Test parse_args function."""
        from src.audiobook_studio.benchmarks.bench_voxcpm2 import parse_args

        with patch("sys.argv", ["test", "--skip-tts", "--json-only"]):
            args = parse_args()
            assert args.skip_tts is True
            assert args.json_only is True

    def test_detect_hardware(self):
        """Test detect_hardware function."""
        from src.audiobook_studio.benchmarks.bench_voxcpm2 import detect_hardware

        hw = detect_hardware()
        assert hw.system != ""
        assert hw.cpu_cores > 0

    def test_compute_voxcpm2_projection(self):
        """Test compute_voxcpm2_projection function."""
        from src.audiobook_studio.benchmarks.bench_voxcpm2 import HardwareProfile, compute_voxcpm2_projection

        hw = HardwareProfile()
        proj = compute_voxcpm2_projection(hw)
        assert proj.fp16_vram_gb > 0
        assert proj.int8_vram_gb > 0

    def test_benchmark_edge_tts_skip(self):
        """Test benchmark_edge_tts with skip mode."""
        from src.audiobook_studio.benchmarks.bench_voxcpm2 import benchmark_edge_tts

        results = benchmark_edge_tts(skip=True)
        assert len(results) > 0
        assert all(r.success for r in results)

    def test_build_summary(self):
        """Test build_summary function."""
        from src.audiobook_studio.benchmarks.bench_voxcpm2 import (
            HardwareProfile,
            TtsBenchmarkResult,
            VoxCPM2Projection,
            build_summary,
        )

        hw = HardwareProfile()
        proj = VoxCPM2Projection()
        tts_results = [
            TtsBenchmarkResult(
                engine="test",
                text_length_chars=100,
                audio_duration_sec=20.0,
                synthesis_time_sec=4.0,
                rtf=0.2,
                throughput_cps=25.0,
                success=True,
            )
        ]
        summary = build_summary(hw, proj, tts_results)
        assert "hardware_assessment" in summary

    def test_build_recommendations(self):
        """Test build_recommendations function."""
        from src.audiobook_studio.benchmarks.bench_voxcpm2 import (
            HardwareProfile,
            VoxCPM2Projection,
            build_recommendations,
        )

        hw = HardwareProfile()
        proj = VoxCPM2Projection()
        recs = build_recommendations(hw, proj)
        assert len(recs) > 0

    def test_build_acceptance_criteria(self):
        """Test build_acceptance_criteria function."""
        from src.audiobook_studio.benchmarks.bench_voxcpm2 import (
            HardwareProfile,
            TtsBenchmarkResult,
            VoxCPM2Projection,
            build_acceptance_criteria,
        )

        hw = HardwareProfile()
        proj = VoxCPM2Projection()
        tts_results = [TtsBenchmarkResult(engine="test", success=True)]
        criteria = build_acceptance_criteria(hw, proj, tts_results)
        assert "vram_footprint_documented" in criteria

    def test_render_markdown_report(self):
        """Test render_markdown_report function."""
        from src.audiobook_studio.benchmarks.bench_voxcpm2 import (
            BenchmarkReport,
            HardwareProfile,
            TtsBenchmarkResult,
            VoxCPM2Projection,
            render_markdown_report,
        )

        hw = HardwareProfile()
        proj = VoxCPM2Projection()
        tts_results = [TtsBenchmarkResult(engine="test", success=True)]
        report = BenchmarkReport(
            hardware=hw, voxcpm2_projection=proj, edge_tts_results=tts_results, acceptance_criteria_met={"test": True}
        )
        md = render_markdown_report(report)
        assert "VoxCPM2" in md
        assert "RTF" in md

    def test_run_benchmark(self):
        """Test run_benchmark function."""
        from src.audiobook_studio.benchmarks.bench_voxcpm2 import run_benchmark

        with patch("time.sleep"):
            report = run_benchmark(skip_tts=True)
            assert report.hardware is not None
            assert report.voxcpm2_projection is not None

    def test_main_skip_tts(self):
        """Test main function with skip_tts."""
        from src.audiobook_studio.benchmarks.bench_voxcpm2 import main

        with patch("sys.argv", ["test", "--skip-tts", "--json-only"]):
            with patch("sys.exit") as mock_exit:
                with patch("time.sleep"):
                    with patch("pathlib.Path.mkdir"):
                        with patch("builtins.open", create=True):
                            main()


class TestBenchmarksInit:
    """Test benchmarks __init__.py."""

    def test_module_imports(self):
        """Test benchmarks module can be imported."""
        from src.audiobook_studio.benchmarks import bench_cost, bench_latency, bench_voxcpm2

        assert bench_cost is not None
        assert bench_latency is not None
        assert bench_voxcpm2 is not None
