#!/usr/bin/env python3
"""Run pytest with coverage and generate report."""

import sys
import subprocess
import json
from pathlib import Path
from datetime import datetime

# Run pytest with coverage
result = subprocess.run(
    [
        sys.executable, "-m", "pytest",
        "--cov=src/audiobook_studio",
        "--cov-report=json",
        "--cov-report=term-missing",
        "-q",
    ],
    capture_output=True,
    text=True,
    timeout=180,
)

print("STDOUT:", result.stdout)
print("STDERR:", result.stderr)
print("Return code:", result.returncode)

if Path("coverage.json").exists():
    with open("coverage.json", "r") as f:
        cov_data = json.load(f)

    totals = cov_data.get("totals", {})
    print(f"\nOverall Coverage: {totals.get('percent_covered', 0):.1f}%")
    print(f"Covered lines: {totals.get('covered_lines', 0)}")
    print(f"Total statements: {totals.get('num_statements', 0)}")
else:
    print("No coverage.json generated")