"""P0.1 DoD test — ``create_feedback`` 写库同时入队 SOP collector.

对应执行手册 docs/EVOLUTION_ROADMAP.md P0.1 子任务 #3 的验收标准：
  ① ``create_feedback`` 末尾调 ``get_correction_collector().add_correction_dict(...)``；
  ② 路由顺序：先入库后入队，入队失败仅 log 不影响 feedback 响应；
  ③ 新增单测 ``test_feedback_feeds_sop_collector``。

红线 #1 主路径真实性：本测试对真实 ``CorrectionCollector``（全局单例）入队，断言队列真实增长、
字段映射正确、非整数 book_id 静默跳过、collector 异常不污染 feedback 响应。
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import patch

import pytest


def _drain_collector() -> int:
    """清空当前 collector 队列并返回释放前的长度。便于测试隔离。"""
    from src.audiobook_studio.pipeline.sop_reflection import get_correction_collector

    collector = get_correction_collector()
    size = collector.queue_size()
    # get_batch 会排空队列
    collector.get_batch(max_size=size + 100, timeout=0.05)
    return size


class TestFeedbackFeedsSopCollector:
    """create_feedback → CorrectionCollector 入队行为。"""

    def setup_method(self):
        from src.audiobook_studio.api.feedback import _feedback_store

        _feedback_store.clear()
        _drain_collector()

    def test_feedback_feeds_sop_collector(self):
        """整数 book_id 的反馈应入队 SOP collector，且字段映射正确。"""
        from src.audiobook_studio.api.feedback import FeedbackCreate, create_feedback
        from src.audiobook_studio.pipeline.sop_reflection import get_correction_collector

        collector = get_correction_collector()
        assert collector.queue_size() == 0

        fb = FeedbackCreate(
            source="human_edit",
            stage="annotation",
            book_id="77",  # 整数 → 可入队
            chapter_index=2,
            paragraph_index=5,
            input_snapshot={"text": "I'm fine"},
            llm_output={"emotion": "neutral"},
            corrected_output={"emotion": "angry"},
            rationale="情感不对，应表现为愤怒，需要更强。",
        )
        result = asyncio.run(create_feedback(fb))

        # ① feedback 响应不受影响（先入库）— 主路径真实
        assert result.id is not None
        assert "emotion_mismatch" in result.pattern_tags

        # ① 入队确实发生
        assert collector.queue_size() == 1

        # 字段映射：emotion_mismatch → field="emotion"，原始=llm_output，修正=corrected_output
        batch = collector.get_batch(max_size=10, timeout=0.05)
        assert len(batch) == 1
        corr = batch[0]
        assert corr.project_id == 77
        assert corr.chapter_index == 2
        assert corr.paragraph_index == 5
        assert corr.field == "emotion"
        assert corr.original_value == {"emotion": "neutral"}
        assert corr.corrected_value == {"emotion": "angry"}
        assert corr.genre == "default"

    def test_feedback_non_numeric_book_id_skips_sop(self):
        """非整数 book_id 静默跳过投喂（不崩溃、不入队）。"""
        from src.audiobook_studio.api.feedback import FeedbackCreate, create_feedback
        from src.audiobook_studio.pipeline.sop_reflection import get_correction_collector

        collector = get_correction_collector()
        assert collector.queue_size() == 0

        fb = FeedbackCreate(
            source="human_edit",
            stage="annotation",
            book_id="not-a-number",  # 非整数 → 跳过
            chapter_index=0,
            paragraph_index=0,
            input_snapshot={},
            llm_output={},
            corrected_output={},
            rationale="Whatever reason here.",
        )
        result = asyncio.run(create_feedback(fb))

        # feedback 主路径不受影响
        assert result.id is not None
        # ② 非整数跳过：队列不变 + 不崩溃
        assert collector.queue_size() == 0

    @pytest.mark.parametrize(
        "rationale,expected_field",
        [
            ("Speaker is wrong, should be male voice.", "speaker_canonical_name"),
            ("语速太快了，需要慢一点", "speech_rate"),
            ("音高不正确，需要降低音调", "pitch_shift_semitones"),
            ("Some unrelated rationale here.", "output"),
        ],
    )
    def test_feedback_pattern_tag_maps_to_sop_field(self, rationale: str, expected_field: str):
        """推断的 pattern_tag 应映射到正确的 SOP correction field。"""
        from src.audiobook_studio.api.feedback import FeedbackCreate, create_feedback
        from src.audiobook_studio.pipeline.sop_reflection import get_correction_collector

        _drain_collector()
        fb = FeedbackCreate(
            source="human_edit",
            stage="annotation",
            book_id="88",
            chapter_index=1,
            paragraph_index=1,
            input_snapshot={},
            llm_output={"v": "old"},
            corrected_output={"v": "new"},
            rationale=rationale,
        )
        asyncio.run(create_feedback(fb))

        batch = get_correction_collector().get_batch(max_size=10, timeout=0.05)
        assert len(batch) == 1
        assert batch[0].field == expected_field

    def test_feedback_sop_feed_failure_is_silent(self, caplog):
        """② 入队失败（add_correction_dict 异常）绝不影响 feedback 响应，仅记日志。"""
        from src.audiobook_studio.api.feedback import FeedbackCreate, create_feedback
        from src.audiobook_studio.pipeline.sop_reflection import get_correction_collector

        caplog.set_level(logging.WARNING, logger="src.audiobook_studio.api.feedback")

        # 让真实 collector.add_correction_dict 抛异常 → 助手应吞掉并记日志
        collector = get_correction_collector()
        with patch.object(collector, "add_correction_dict", side_effect=RuntimeError("boom")):
            fb = FeedbackCreate(
                source="human_edit",
                stage="annotation",
                book_id="99",
                chapter_index=1,
                paragraph_index=1,
                input_snapshot={},
                llm_output={"v": "old"},
                corrected_output={"v": "new"},
                rationale="A rationale long enough.",
            )
            result = asyncio.run(create_feedback(fb))

        # 主路径不受影响：feedback 仍正常返回
        assert result.id is not None
        # 入队失败被静默降级（recorded warning），非崩溃
        assert any("静默降级" in rec.message for rec in caplog.records) or any(
            "boom" in rec.message for rec in caplog.records
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
