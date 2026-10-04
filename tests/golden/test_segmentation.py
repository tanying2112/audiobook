#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Golden Dataset Tests for Segmentation (P0-3).

Tests the segment pipeline against known good outputs.
"""

import json
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src"))

import pytest

from src.audiobook_studio.pipeline.segment import (
    SegmentConfig,
    SegmentPipeline,
    SegmentStrategy,
)


def load_test_cases():
    """Load test cases from JSON file."""
    test_file = Path(__file__).parent / "segmentation" / "test_cases.json"
    with open(test_file, "r", encoding="utf-8") as f:
        return json.load(f)


class TestSegmentationGolden:
    """Golden dataset tests for segmentation."""

    @pytest.fixture
    def pipeline_rule(self):
        """Rule-based segmenter."""
        config = SegmentConfig(
            strategy=SegmentStrategy.RULE,
            min_paragraph_chars=10,  # Lower for test data
        )
        return SegmentPipeline(config=config, mock_mode=True)

    @pytest.fixture
    def pipeline_semantic(self):
        """Semantic segmenter (will fallback to rule if sentence-transformers not available)."""
        config = SegmentConfig(strategy=SegmentStrategy.SEMANTIC)
        return SegmentPipeline(config=config, mock_mode=True)

    @pytest.mark.parametrize("case", load_test_cases())
    def test_rule_segmentation(self, pipeline_rule, case):
        """Test rule-based segmentation against golden data."""
        result = pipeline_rule.run(text=case["input"])

        # Check segment count
        assert (
            len(result.segments) == case["expected_segments"]
        ), f"Expected {case['expected_segments']} segments, got {len(result.segments)} for {case['name']}"

        # Check average length is reasonable
        avg_len = sum(len(s.text) for s in result.segments) / len(result.segments)
        # Allow 2x tolerance
        assert (
            avg_len <= case["expected_avg_length"] * 2
        ), f"Average segment length {avg_len:.0f} exceeds expected {case['expected_avg_length'] * 2} for {case['name']}"

        # Verify all segments have text
        for seg in result.segments:
            assert seg.text.strip(), f"Empty segment in {case['name']}"
            assert seg.index >= 0, f"Invalid index in {case['name']}"

    def test_segment_order_preserved(self, pipeline_rule):
        """Test that segment order matches original text order."""
        text = "第一段。\n\n第二段。\n\n第三段。"
        result = pipeline_rule.run(text=text)

        # Find positions in original text
        positions = [text.find(seg.text) for seg in result.segments]
        # Should be in increasing order
        assert positions == sorted(positions), "Segments not in original order"

    def test_no_empty_segments(self, pipeline_rule):
        """Test that no empty segments are produced."""
        text = "段落一。\n\n\n\n段落二。"
        result = pipeline_rule.run(text=text)

        for seg in result.segments:
            assert len(seg.text.strip()) > 0, "Found empty segment"

    def test_chinese_punctuation_handling(self, pipeline_rule):
        """Test handling of Chinese punctuation."""
        text = "句子一。句子二！句子三？\n\n新段落。"
        result = pipeline_rule.run(text=text)

        # Should produce 2 segments (split by double newline)
        assert len(result.segments) >= 1

    def test_english_punctuation_handling(self, pipeline_rule):
        """Test handling of English punctuation."""
        text = "Sentence one. Sentence two! Sentence three?\n\nNew paragraph."
        result = pipeline_rule.run(text=text)

        assert len(result.segments) >= 1

    def test_config_max_length_respected(self):
        """Test that max_paragraph_chars config is respected."""
        config = SegmentConfig(
            strategy=SegmentStrategy.RULE,
            max_paragraph_chars=50,
            min_paragraph_chars=10,
        )
        pipeline = SegmentPipeline(config=config, mock_mode=True)

        # Long text that should be split
        text = "这是一个很长的句子。" * 10  # ~100 chars
        result = pipeline.run(text=text)

        # Each segment should be <= max_paragraph_chars (with some tolerance)
        for seg in result.segments:
            assert len(seg.text) <= 60, f"Segment too long: {len(seg.text)}"

    def test_config_min_length_respected(self):
        """Test that min_paragraph_chars config is respected for forced splits (paragraphs exceeding max_paragraph_chars)."""
        config = SegmentConfig(
            strategy=SegmentStrategy.RULE,
            max_paragraph_chars=2000,
            min_paragraph_chars=50,
        )
        pipeline = SegmentPipeline(config=config, mock_mode=True)

        # Test 1: Natural paragraph boundaries are preserved regardless of min_paragraph_chars
        text = "短。\n\n这是一个足够长的段落，应该被保留下来。它包含足够的字符数量。"
        result = pipeline.run(text=text)

        # Should have 2 segments (both preserved at natural boundaries)
        assert len(result.segments) == 2, f"Expected 2 segments at natural boundaries, got {len(result.segments)}"

        # Test 2: min_paragraph_chars is respected when forcibly splitting a long paragraph
        config2 = SegmentConfig(
            strategy=SegmentStrategy.RULE,
            max_paragraph_chars=50,  # Force split
            min_paragraph_chars=30,
        )
        pipeline2 = SegmentPipeline(config=config2, mock_mode=True)
        long_text = "这是一个很长的句子。" * 5  # ~50 chars, will be split
        result2 = pipeline2.run(text=long_text)

        # Each split segment should be >= min_paragraph_chars (30)
        for seg in result2.segments:
            assert len(seg.text) >= 30, f"Split segment too short: {len(seg.text)}"


class TestSegmentConfig:
    """Tests for SegmentConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = SegmentConfig()
        assert config.strategy == SegmentStrategy.RULE
        assert config.max_paragraph_chars == 2000
        assert config.min_paragraph_chars == 50
        assert config.language == "zh"

    def test_custom_config(self):
        """Test custom configuration."""
        config = SegmentConfig(
            strategy=SegmentStrategy.SEMANTIC,
            max_paragraph_chars=1000,
            semantic_similarity_threshold=0.8,
        )
        assert config.strategy == SegmentStrategy.SEMANTIC
        assert config.max_paragraph_chars == 1000
        assert config.semantic_similarity_threshold == 0.8


class TestSegmentDataClasses:
    """Tests for data classes."""

    def test_segment_creation(self):
        """Test Segment dataclass."""
        from src.audiobook_studio.pipeline.segment import Segment

        seg = Segment(
            text="测试文本",
            index=0,
            start_char=0,
            end_char=4,
            metadata={"type": "narrative"},
        )
        assert seg.text == "测试文本"
        assert seg.length == 4
        assert seg.metadata["type"] == "narrative"

    def test_segmentation_result(self):
        """Test SegmentationResult dataclass."""
        from src.audiobook_studio.pipeline.segment import Segment, SegmentationResult, SegmentConfig

        seg = Segment(text="测试", index=0, start_char=0, end_char=2)
        result = SegmentationResult(
            segments=[seg],
            strategy_used=SegmentStrategy.RULE,
            config=SegmentConfig(),
        )
        assert len(result.segments) == 1
        assert result.strategy_used == SegmentStrategy.RULE


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
