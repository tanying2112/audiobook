#!/usr/bin/env python3
"""Run pytest with coverage programmatically."""

import pytest
import sys

# Run pytest with coverage programmatically
sys.exit(pytest.main([
    "--cov=src/audiobook_studio",
    "--cov-report=json",
    "--cov-report=term-missing",
    "-q",
]))