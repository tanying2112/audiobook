#!/usr/bin/env python3
"""Run pytest directly without subprocess."""

import pytest
import sys

# Run tests with coverage
sys.exit(pytest.main([
    "tests/unit/test_orchestrator.py",
    "-v",
    "--cov=src/audiobook_studio/pipeline/orchestrator",
    "--cov-report=term-missing",
    "--cov-report=json:coverage_orchestrator.json",
    "-x",  # Stop on first failure for speed
]))