#!/usr/bin/env python3
"""Run pytest with coverage and generate baseline report."""

import sys

import pytest

# Run pytest with coverage
exit_code = pytest.main(
    [
        "--cov=src/audiobook_studio",
        "--cov-report=json:coverage_full.json",
        "--cov-report=term-missing",
        "-q",
        "--tb=short",
    ]
)

sys.exit(exit_code)
