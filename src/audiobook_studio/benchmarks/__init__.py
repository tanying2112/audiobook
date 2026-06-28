# Audiobook Studio - Benchmarks Module
"""Performance and cost benchmarking utilities."""

from .bench_voxcpm2 import (
    BenchmarkReport,
    HardwareProfile,
    TtsBenchmarkResult,
    VoxCPM2Projection,
    compute_voxcpm2_projection,
    detect_hardware,
    render_markdown_report,
    run_benchmark,
)

__all__ = [
    # VoxCPM2 benchmark (Issue 0.4)
    "HardwareProfile",
    "TtsBenchmarkResult",
    "VoxCPM2Projection",
    "BenchmarkReport",
    "detect_hardware",
    "compute_voxcpm2_projection",
    "run_benchmark",
    "render_markdown_report",
]
