#!/usr/bin/env python3
"""Run E2E long book verification script directly."""

import sys
import os

# Add src to path
sys.path.insert(0, "src")

# Import and run the E2E script
sys.path.insert(0, "tests/e2e")
from e2e_long_book import run_e2e_long_book, save_report, print_summary
from pathlib import Path

novel_path = Path("data/long_novel/hongloumeng.txt")

if not novel_path.exists():
    print(f"Novel file not found: {novel_path}")
    sys.exit(1)

print("Running E2E verification...")
report = run_e2e_long_book(
    novel_path=novel_path,
    book_id="hongloumeng",
    title_hint="红楼梦",
    max_paragraphs=50  # Start with 50 for faster verification
)

save_report(report, Path("reports/e2e_long_book_report.json"))
print_summary(report)

sys.exit(0 if report.passed else 1)