#!/usr/bin/env python3
"""Simple test runner."""

import sys

import pytest

# Run a simple test to check pytest works
result = pytest.main(["--version"])
print(f"pytest version test exit code: {result}")

# Run one test file with coverage
result = pytest.main(
    [
        "tests/unit/test_orchestrator.py::TestWriteExtract",
        "-v",
        "--cov=src/audiobook_studio/pipeline/orchestrator",
        "--cov-report=term-missing",
    ]
)
print(f"Test exit code: {result}")
sys.exit(result)
