"""E2E Integration Tests for Audiobook Studio Pipeline.

Tests the full pipeline from text input to audio output using real LLM and TTS services.
These tests require valid API keys and should be run selectively.

Usage:
    # Run all E2E tests (requires API keys)
    pytest tests/e2e/ -v --e2e

    # Run specific test
    pytest tests/e2e/test_llm_pipeline.py::test_extract_stage -v

    # Skip E2E tests by default (need --e2e flag)
    pytest tests/unit/ -v  # E2E tests skipped
"""

import asyncio
import os
from pathlib import Path
from typing import Optional

import pytest


# Test configuration
SAMPLE_TEXT = """
第一章：开始

"你好，"李明说道。他今天心情很好，阳光明媚，鸟儿在枝头歌唱。

王芳转过身来，微笑着回答："是啊，今天真是个美好的一天。"

他们一起走向公园，享受着这难得的宁静时光。
"""


class E2ETestConfig:
    """Configuration for E2E tests."""

    @staticmethod
    def get_api_key(provider: str) -> Optional[str]:
        """Get API key for specified provider."""
        key_map = {
            "openrouter": "OPENROUTER_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
        }
        env_var = key_map.get(provider.lower(), f"{provider.upper()}_API_KEY")
        return os.environ.get(env_var)

    @staticmethod
    def check_api_key(provider: str) -> bool:
        """Check if API key is available."""
        return E2ETestConfig.get_api_key(provider) is not None


@pytest.fixture
def sample_text():
    """Provide sample Chinese text for testing."""
    return SAMPLE_TEXT


@pytest.fixture
def temp_output_dir(tmp_path):
    """Create temporary output directory."""
    output_dir = tmp_path / "e2e_output"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir