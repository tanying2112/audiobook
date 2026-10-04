#!/usr/bin/env python3
"""Run coverage check and E2E test in one script."""

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

print("=" * 70)
print("STEP 1: Running Coverage Check")
print("=" * 70)

# Run pytest with coverage
result = subprocess.run(
    [
        sys.executable,
        "-m",
        "pytest",
        "--cov=src/audiobook_studio",
        "--cov-report=json:coverage_check.json",
        "--cov-report=term-missing",
        "-q",
    ],
    capture_output=True,
    text=True,
    timeout=180,
)

print("STDOUT:")
print(result.stdout)
print("STDERR:")
print(result.stderr)
print(f"Return code: {result.returncode}")

if Path("coverage_check.json").exists():
    with open("coverage_check.json", "r") as f:
        cov_data = json.load(f)

    totals = cov_data.get("totals", {})
    print(f"\nOverall Coverage: {totals.get('percent_covered', 0):.1f}%")
    print(f"Covered lines: {totals.get('covered_lines', 0)}")
    print(f"Total statements: {totals.get('num_statements', 0)}")

print("\n" + "=" * 70)
print("STEP 2: Running E2E Long Book Verification")
print("=" * 70)

# Add src to path
sys.path.insert(0, "src")

# Run E2E
sys.path.insert(0, "tests/e2e")
from pathlib import Path

from e2e_long_book import print_summary, run_e2e_long_book, save_report

novel_path = Path("data/long_novel/hongloumeng.txt")

if not novel_path.exists():
    print(f"Novel file not found: {novel_path}")
else:
    report = run_e2e_long_book(
        novel_path=novel_path,
        book_id="hongloumeng",
        title_hint="红楼梦",
        max_paragraphs=50,
    )
    save_report(report, Path("reports/e2e_long_book_report.json"))
    print_summary(report)
    print(f"\nE2E Result: {'PASSED' if report.passed else 'FAILED'}")
