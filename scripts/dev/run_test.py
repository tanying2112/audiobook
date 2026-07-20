#!/usr/bin/env python
"""Run the specific test"""
import subprocess
import sys

result = subprocess.run(
    [
        sys.executable,
        "-m",
        "pytest",
        "tests/unit/test_quality_check.py::TestQualityCheckPipeline::test_run_mock_mode_multiple_segments",
        "-v",
    ],
    capture_output=True,
    text=True,
    timeout=120,
)

print("STDOUT:")
print(result.stdout)
print("\nSTDERR:")
print(result.stderr)
print(f"\nReturn code: {result.returncode}")
