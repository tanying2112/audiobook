"""Tests for _match_retry_input — 质检重试回调的段落输入精确匹配.

回归背景 (2026-10-13 Run B 全书): 旧实现用子串包含判断
``f"_p{idx}" in seg_id``, seg_id "..._p10" 命中 "_p1", 导致 p10-p19 段的
质检重试拿到 p1 的输入, 重试产物是 p1 文本的音频, 复检只验音质不验文本
而通过, 被换进对应槽位 —— 全书 21/33 章出现大段重复朗读。
"""

import pytest

from src.audiobook_studio.pipeline.synthesize import _match_retry_input
from src.audiobook_studio.schemas import TtsRoutingInput


def _make_input(paragraph_index: int, text: str) -> TtsRoutingInput:
    from src.audiobook_studio.schemas import (
        CharacterVoiceBinding,
        ParagraphAnnotation,
    )

    voice_map = [
        CharacterVoiceBinding(
            canonical_name="旁白",
            aliases=[],
            gender="neutral",
            age_range="adult",
            suggested_voice_id="zh-CN-XiaoxiaoNeural",
            sample_quote="旁白样本",
            cost_limit_per_book=20.0,
            cost_limit_per_chapter=5.0,
            prefer_local=True,
            contract_version=1,
        )
    ]
    annotation = ParagraphAnnotation(
        paragraph_index=paragraph_index,
        speaker_canonical_name="旁白",
        is_dialogue=False,
        emotion="neutral",
        emotion_intensity=0.5,
        speech_rate=1.0,
        pitch_shift_semitones=0,
        pause_before_ms=300,
        pause_after_ms=500,
        confidence=0.9,
        needs_sfx=False,
        sfx_tags=[],
    )
    return TtsRoutingInput(
        paragraph_annotation=annotation,
        text=text,
        character_voice_map=voice_map,
        book_id="book1",
        chapter_index=1,
        paragraph_index=paragraph_index,
        prefer_local=True,
        cumulative_cost_usd=0.0,
        cost_limit_per_book=20.0,
        cost_limit_per_chapter=5.0,
        contract_version=1,
    )


@pytest.fixture
def inputs():
    """p1, p2, p10, p20 与一个幽灵段 (9999) —— 覆盖全部子串误配形态."""
    return [
        _make_input(1, "第一段文本"),
        _make_input(2, "第二段文本"),
        _make_input(10, "第十段文本"),
        _make_input(20, "第二十段文本"),
        _make_input(9999, "幽灵合并段文本"),
    ]


class TestMatchRetryInput:
    def test_p10_matches_p10_not_p1(self, inputs):
        """核心回归: "..._p10" 必须命中 p10, 不能被子串误配成 p1."""
        got = _match_retry_input(inputs, "book1_ch1_p10")
        assert got is not None
        assert got.paragraph_index == 10
        assert got.text == "第十段文本"

    def test_p20_matches_p20_not_p2(self, inputs):
        got = _match_retry_input(inputs, "book1_ch1_p20")
        assert got is not None
        assert got.paragraph_index == 20

    def test_single_digit_exact(self, inputs):
        assert _match_retry_input(inputs, "book1_ch1_p1").paragraph_index == 1
        assert _match_retry_input(inputs, "book1_ch1_p2").paragraph_index == 2

    def test_ghost_paragraph_9999(self, inputs):
        got = _match_retry_input(inputs, "book1_ch1_p9999")
        assert got is not None
        assert got.paragraph_index == 9999

    def test_unknown_paragraph_returns_none(self, inputs):
        assert _match_retry_input(inputs, "book1_ch1_p99") is None

    def test_seg_id_without_paragraph_suffix_returns_none(self, inputs):
        assert _match_retry_input(inputs, "book1_ch1") is None
        assert _match_retry_input(inputs, "") is None

    def test_retry_suffix_is_not_part_of_id(self, inputs):
        """retry 文件名形如 f"{seg_id}_retry{attempt}", 回调拿到的是不含
        后缀的 seg_id; 即便误传带后缀的串也不得匹配错段."""
        assert _match_retry_input(inputs, "book1_ch1_p10_retry1") is None
