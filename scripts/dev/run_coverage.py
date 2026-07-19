#!/usr/bin/env python3
"""Run coverage check directly without subprocess."""

import json
import sys
from pathlib import Path

# Import the coverage_check module
sys.path.insert(0, str(Path(__file__).parent))

from scripts.coverage_check import generate_report, print_summary, save_report

if __name__ == "__main__":
    report = generate_report()
    if report:
        print_summary(report)
        save_report(report, "reports/coverage_baseline.json")
        if not report["targets_check"]["overall_pass"]:
            print("\n⚠️  Some category targets not met.")
            sys.exit(1)
    else:
        print("Failed to generate report")
        sys.exit(1)
