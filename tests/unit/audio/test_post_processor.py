"""AudioPostProcessor 单元测试 - 语义到物理声学参数映射.

测试覆盖:
1. 情绪翻译验证: angry -> speed=1.15, volume_db=+1.5, pitch=+2Hz
2. 标点动态增量验证: "!" vs "，" 的 pause_after_ms 差值
3. 段落过渡临界测试: narration -> dialogue 停顿拉大
4. 文本长度缓冲验证: 长文本额外缓冲上限 200ms
"""

import pytest

from src.audiobook_studio.pipeline.audio_postprocess import (
    AudioPostProcessor,
    PhysicalAudioSegment,
    generate_acoustic_schedule,
)
from src.audiobook_studio.config.acoustic_mapping import (
    EMOTION_ACOUSTIC_MAP,
    TRANSITION_PAUSE_MAP,
)


class TestEmotionAcousticMapping:
    """情绪到声学参数的映射验证."""

    def test_angry_emotion_mapping(self):
        """愤怒情绪应产生: 加速、增大音量、升高音调."""
        processor = AudioPostProcessor()
        # 使用 narration 避免对话加速干扰基准值测试
        segments = processor.generate_acoustic_schedule([
            {"text": "气死我了！", "speaker": "主角", "emotion": "angry", "is_dialogue": False, "paragraph_type": "narration"}
        ])
        seg = segments[0]
        # EMOTION_ACOUSTIC_MAP["angry"] = {speed: 1.15, volume_db: 1.5, pitch: +20Hz}
        # clamp_speed 四舍五入到 0.1: 1.15 -> 1.2
        assert seg.speed == pytest.approx(1.2, rel=0.01), f"angry speed 应为 1.2(四舍五入后), 实际 {seg.speed}"
        assert seg.volume_db == pytest.approx(1.5, rel=0.01), f"angry volume_db 应为 1.5, 实际 {seg.volume_db}"
        assert seg.pitch_hz == pytest.approx(20.0, rel=0.01), f"angry pitch_hz 应为 +20Hz, 实际 {seg.pitch_hz}"

    def test_sad_emotion_mapping(self):
        """悲伤情绪应产生: 减速、降低音量、降低音调."""
        processor = AudioPostProcessor()
        segments = processor.generate_acoustic_schedule([
            {"text": "真遗憾。", "speaker": "主角", "emotion": "sad", "is_dialogue": False, "paragraph_type": "narration"}
        ])
        seg = segments[0]
        # EMOTION_ACOUSTIC_MAP["sad"] = {speed: 0.85, volume_db: -2.0, pitch: -10Hz}
        # clamp_speed 标准四舍五入: 0.85 * 10 = 8.5 -> 9 -> 0.9
        assert seg.speed == pytest.approx(0.9, rel=0.01), f"sad speed 应为 0.9(四舍五入后), 实际 {seg.speed}"
        assert seg.volume_db == pytest.approx(-2.0, rel=0.01), f"sad volume_db 应为 -2.0, 实际 {seg.volume_db}"
        assert seg.pitch_hz == pytest.approx(-10.0, rel=0.01), f"sad pitch_hz 应为 -10Hz, 实际 {seg.pitch_hz}"

    def test_fear_emotion_mapping(self):
        """恐惧情绪应产生: 加速、略降音量、大幅升调."""
        processor = AudioPostProcessor()
        segments = processor.generate_acoustic_schedule([
            {"text": "救命！", "speaker": "主角", "emotion": "fearful", "is_dialogue": True, "paragraph_type": "dialogue"}
        ])
        seg = segments[0]
        # EMOTION_ACOUSTIC_MAP["fearful"] = {speed: 1.20, volume_db: -1.0, pitch: +40Hz}
        # + DIALOGUE_SPEED_BOOST (0.05) = 1.25 -> clamp_speed -> 1.3 (SPEED_MAX)
        assert seg.speed == pytest.approx(1.3, rel=0.01), f"fearful speed 应为 1.3(钳制后), 实际 {seg.speed}"
        assert seg.volume_db == pytest.approx(-1.0, rel=0.01), f"fearful volume_db 应为 -1.0, 实际 {seg.volume_db}"
        assert seg.pitch_hz == pytest.approx(40.0, rel=0.01), f"fearful pitch_hz 应为 +40Hz, 实际 {seg.pitch_hz}"

    def test_neutral_emotion_mapping(self):
        """中性情绪应产生基准参数."""
        processor = AudioPostProcessor()
        segments = processor.generate_acoustic_schedule([
            {"text": "这是旁白。", "speaker": "旁白", "emotion": "neutral", "is_dialogue": False}
        ])
        seg = segments[0]
        assert seg.speed == pytest.approx(1.0, rel=0.01)
        assert seg.volume_db == pytest.approx(0.0, rel=0.01)
        assert seg.pitch_hz == pytest.approx(0.0, rel=0.01)

    def test_all_emotions_have_mapping(self):
        """确保所有枚举情绪都有声学映射."""
        expected_emotions = [
            "neutral", "happy", "sad", "angry", "fearful", "surprised",
            "disgusted", "tense", "tender", "contemplative", "whisper",
            "cold_laugh", "sigh", "sarcastic"
        ]
        for emo in expected_emotions:
            assert emo in EMOTION_ACOUSTIC_MAP, f"缺少情绪 {emo} 的声学映射"
            mapping = EMOTION_ACOUSTIC_MAP[emo]
            # EmotionAcousticProfile 是 dataclass，检查字段属性
            assert hasattr(mapping, "speed"), f"{emo} 缺少 speed 字段"
            assert hasattr(mapping, "volume_db"), f"{emo} 缺少 volume_db 字段"
            assert hasattr(mapping, "pitch_hz"), f"{emo} 缺少 pitch_hz 字段"


class TestPunctuationDynamicPause:
    """标点符号动态停顿增量验证."""

    def test_exclamation_vs_comma_pause_delta(self):
        """感叹号应比逗号产生更大的 pause_after_ms."""
        processor = AudioPostProcessor()

        # 带感叹号
        seg_excl = processor.generate_acoustic_schedule([
            {"text": "太好了！", "speaker": "主角", "emotion": "happy", "is_dialogue": True}
        ])[0]

        # 带逗号
        seg_comma = processor.generate_acoustic_schedule([
            {"text": "好吧，", "speaker": "主角", "emotion": "neutral", "is_dialogue": True}
        ])[0]

        # 感叹号基础停顿应大于逗号
        # 注意：总停顿 = base_pause + punct_pause + length_buffer
        # 由于文本长度不同，我们比较 punct_pause 部分
        # 通过控制相同文本长度来隔离标点影响
        seg_excl2 = processor.generate_acoustic_schedule([
            {"text": "太好了！", "speaker": "主角", "emotion": "neutral", "is_dialogue": False}
        ])[0]
        seg_comma2 = processor.generate_acoustic_schedule([
            {"text": "太好了，", "speaker": "主角", "emotion": "neutral", "is_dialogue": False}
        ])[0]

        # 感叹号 pause_after 应该明显大于逗号 (差值约 250ms: 350-100)
        delta = seg_excl2.pause_after_ms - seg_comma2.pause_after_ms
        assert delta >= 200, f"感叹号应比逗号多 ~250ms 停顿, 实际差值 {delta}ms"

    def test_period_pause(self):
        """句号应产生标准停顿."""
        processor = AudioPostProcessor()
        seg = processor.generate_acoustic_schedule([
            {"text": "故事结束。", "speaker": "旁白", "emotion": "neutral", "is_dialogue": False}
        ])[0]
        # 句号标点延迟 250ms + 基础过渡 300ms + 长度缓冲
        assert seg.pause_after_ms > 500

    def test_question_mark_pause(self):
        """问号应产生较大停顿."""
        processor = AudioPostProcessor()
        seg = processor.generate_acoustic_schedule([
            {"text": "你是谁？", "speaker": "主角", "emotion": "surprised", "is_dialogue": True}
        ])[0]
        assert seg.pause_after_ms > 500


class TestParagraphTransitionPause:
    """段落过渡类型停顿验证."""

    def test_narration_to_dialogue_pause_larger(self):
        """旁白转对话：停顿应拉大 (预留戏剧感)."""
        processor = AudioPostProcessor()
        segments = processor.generate_acoustic_schedule([
            {"text": "旁白描述场景。", "speaker": "旁白", "emotion": "neutral", "is_dialogue": False, "paragraph_type": "narration"},
            {"text": "你好啊！", "speaker": "主角", "emotion": "happy", "is_dialogue": True, "paragraph_type": "dialogue"},
        ])

        # 第一个段落是 narration，下一个是 dialogue
        # TRANSITION_PAUSE_MAP[("narration", "dialogue")] = 550
        # 对比 narration->narration = 300
        seg1 = segments[0]
        # 由于有标点和长度缓冲，总停顿应显著大于 300
        assert seg1.pause_after_ms >= 550, f"narration->dialogue 应 >= 550ms, 实际 {seg1.pause_after_ms}ms"

    def test_dialogue_to_narration_pause_largest(self):
        """对话转旁白：停顿最大 (600ms)."""
        processor = AudioPostProcessor()
        segments = processor.generate_acoustic_schedule([
            {"text": "再见！", "speaker": "主角", "emotion": "sad", "is_dialogue": True, "paragraph_type": "dialogue"},
            {"text": "故事继续。", "speaker": "旁白", "emotion": "neutral", "is_dialogue": False, "paragraph_type": "narration"},
        ])

        seg1 = segments[0]
        # TRANSITION_PAUSE_MAP[("dialogue", "narration")] = 600
        assert seg1.pause_after_ms >= 600, f"dialogue->narration 应 >= 600ms, 实际 {seg1.pause_after_ms}ms"

    def test_dialogue_to_dialogue_pause(self):
        """对话转对话：中等停顿."""
        processor = AudioPostProcessor()
        segments = processor.generate_acoustic_schedule([
            {"text": "你好吗？", "speaker": "甲", "emotion": "happy", "is_dialogue": True, "paragraph_type": "dialogue"},
            {"text": "我很好。", "speaker": "乙", "emotion": "neutral", "is_dialogue": True, "paragraph_type": "dialogue"},
        ])

        seg1 = segments[0]
        # TRANSITION_PAUSE_MAP[("dialogue", "dialogue")] = 400
        assert seg1.pause_after_ms >= 400

    def test_narration_to_narration_pause(self):
        """旁白转旁白：基础停顿."""
        processor = AudioPostProcessor()
        segments = processor.generate_acoustic_schedule([
            {"text": "第一段旁白。", "speaker": "旁白", "emotion": "neutral", "is_dialogue": False, "paragraph_type": "narration"},
            {"text": "第二段旁白。", "speaker": "旁白", "emotion": "neutral", "is_dialogue": False, "paragraph_type": "narration"},
        ])

        seg1 = segments[0]
        # TRANSITION_PAUSE_MAP[("narration", "narration")] = 300
        assert seg1.pause_after_ms >= 300


class TestLengthBuffer:
    """文本长度缓冲计算验证."""

    def test_short_text_minimal_buffer(self):
        """短文本长度缓冲极小."""
        processor = AudioPostProcessor()
        seg = processor.generate_acoustic_schedule([
            {"text": "好。", "speaker": "旁白", "emotion": "neutral", "is_dialogue": False, "paragraph_type": "narration"}
        ])[0]
        # 2字 * 1.5ms = 3ms，上限 200ms
        # 总停顿 = base(300) + punct(250) + length(3) = 553ms
        assert 550 <= seg.pause_after_ms <= 560

    def test_long_text_buffer_capped_at_200ms(self):
        """长文本缓冲封顶 200ms."""
        processor = AudioPostProcessor()
        long_text = "这是一个很长的段落文本。" * 20  # ~200字
        seg = processor.generate_acoustic_schedule([
            {"text": long_text, "speaker": "旁白", "emotion": "neutral", "is_dialogue": False, "paragraph_type": "narration"}
        ])[0]
        # 长度缓冲应被封顶在 200ms
        # 总停顿 = base(300) + punct(250) + length(200) = 750ms
        assert seg.pause_after_ms <= 800  # 留一些余量

    def test_medium_text_buffer_proportional(self):
        """中等长度文本缓冲成比例."""
        processor = AudioPostProcessor()
        # 50字 -> 75ms 缓冲
        medium_text = "中等长度的段落文本用于测试长度缓冲计算。"  # ~20字
        seg = processor.generate_acoustic_schedule([
            {"text": medium_text, "speaker": "旁白", "emotion": "neutral", "is_dialogue": False, "paragraph_type": "narration"}
        ])[0]
        # 验证在合理范围内
        assert 550 < seg.pause_after_ms < 700


class TestIntensityAdjustment:
    """情感强度微调验证."""

    def test_high_intensity_boost(self):
        """高强度 (>0.8) 应略微加速、增大偏移."""
        processor = AudioPostProcessor()
        # 使用 narration 避免对话加速干扰
        seg_normal = processor.generate_acoustic_schedule([
            {"text": "测试。", "speaker": "主角", "emotion": "angry", "is_dialogue": False, "paragraph_type": "narration", "emotion_intensity": 0.5}
        ])[0]
        seg_high = processor.generate_acoustic_schedule([
            {"text": "测试。", "speaker": "主角", "emotion": "angry", "is_dialogue": False, "paragraph_type": "narration", "emotion_intensity": 0.9}
        ])[0]

        # 高强度应比正常强度音量大 (volume_db 不受 0.1 钳制影响)
        assert seg_high.volume_db > seg_normal.volume_db
        # pitch 也应增大
        assert seg_high.pitch_hz > seg_normal.pitch_hz

    def test_low_intensity_reduce(self):
        """低强度 (<0.3) 应减速、减小偏移."""
        processor = AudioPostProcessor()
        seg_normal = processor.generate_acoustic_schedule([
            {"text": "测试。", "speaker": "主角", "emotion": "angry", "is_dialogue": False, "paragraph_type": "narration", "emotion_intensity": 0.5}
        ])[0]
        seg_low = processor.generate_acoustic_schedule([
            {"text": "测试。", "speaker": "主角", "emotion": "angry", "is_dialogue": False, "paragraph_type": "narration", "emotion_intensity": 0.2}
        ])[0]

        assert seg_low.volume_db < seg_normal.volume_db
        assert seg_low.pitch_hz < seg_normal.pitch_hz


class TestDialogueSpeedBoost:
    """对话默认加速验证."""

    def test_dialogue_faster_than_narration(self):
        """相同情绪下，对话应比旁白略快."""
        processor = AudioPostProcessor()
        seg_dialogue = processor.generate_acoustic_schedule([
            {"text": "你好。", "speaker": "主角", "emotion": "neutral", "is_dialogue": True, "paragraph_type": "dialogue"}
        ])[0]
        seg_narration = processor.generate_acoustic_schedule([
            {"text": "你好。", "speaker": "旁白", "emotion": "neutral", "is_dialogue": False, "paragraph_type": "narration"}
        ])[0]

        assert seg_dialogue.speed > seg_narration.speed
        # DIALOGUE_SPEED_BOOST = 0.05, clamp to 0.1 -> 1.05 -> 1.1, diff = 0.1
        assert seg_dialogue.speed - seg_narration.speed == pytest.approx(0.1, rel=0.1)


class TestClamping:
    """参数钳制范围验证."""

    def test_speed_clamped_to_range(self):
        """语速钳制在 [0.7, 1.3]."""
        processor = AudioPostProcessor()
        # 构造极端情绪组合
        seg = processor.generate_acoustic_schedule([
            {"text": "测试。", "speaker": "主角", "emotion": "fear", "is_dialogue": True, "emotion_intensity": 0.9}
        ])[0]
        assert 0.7 <= seg.speed <= 1.3

    def test_volume_clamped_to_range(self):
        """音量钳制在合理范围."""
        processor = AudioPostProcessor()
        seg = processor.generate_acoustic_schedule([
            {"text": "测试。", "speaker": "主角", "emotion": "angry", "is_dialogue": True, "emotion_intensity": 0.9}
        ])[0]
        # 音量范围约 -10 到 +10 dB
        assert -10.0 <= seg.volume_db <= 10.0

    def test_pitch_clamped_to_range(self):
        """音调钳制在 [-20, +20] Hz."""
        processor = AudioPostProcessor()
        seg = processor.generate_acoustic_schedule([
            {"text": "测试。", "speaker": "主角", "emotion": "fear", "is_dialogue": True, "emotion_intensity": 0.9}
        ])[0]
        assert -20.0 <= seg.pitch_hz <= 20.0


class TestConvenienceFunction:
    """模块级便捷函数测试."""

    def test_generate_acoustic_schedule_function(self):
        """generate_acoustic_schedule 便捷函数应正常工作."""
        segments = generate_acoustic_schedule([
            {"text": "测试文本。", "speaker": "旁白", "emotion": "neutral", "is_dialogue": False}
        ])
        assert len(segments) == 1
        assert isinstance(segments[0], PhysicalAudioSegment)
        assert segments[0].text == "测试文本。"
        assert segments[0].speaker == "旁白"

    def test_custom_emotion_map_override(self):
        """自定义情绪映射应覆盖默认值."""
        from src.audiobook_studio.config.acoustic_mapping import EmotionAcousticProfile
        # 使用在钳制范围内的值
        custom_profile = EmotionAcousticProfile(speed=1.2, volume_db=2.0, pitch_hz=5.0)
        processor = AudioPostProcessor(emotion_map={"test": custom_profile})
        segments = processor.generate_acoustic_schedule([
            {"text": "测试。", "speaker": "旁白", "emotion": "test", "is_dialogue": False}
        ])
        assert segments[0].speed == pytest.approx(1.2, rel=0.01)


class TestEdgeCases:
    """边界情况测试."""

    def test_empty_list_returns_empty(self):
        """空列表输入返回空列表."""
        processor = AudioPostProcessor()
        assert processor.generate_acoustic_schedule([]) == []

    def test_missing_emotion_defaults_to_neutral(self):
        """缺失 emotion 字段默认 neutral."""
        processor = AudioPostProcessor()
        seg = processor.generate_acoustic_schedule([
            {"text": "测试。", "speaker": "旁白"}  # 无 emotion
        ])[0]
        assert seg.emotion == "neutral"
        assert seg.speed == pytest.approx(1.0, rel=0.01)

    def test_missing_paragraph_type_inferred_from_dialogue(self):
        """缺失 paragraph_type 从 is_dialogue 推断."""
        processor = AudioPostProcessor()
        seg_dialogue = processor.generate_acoustic_schedule([
            {"text": "对话。", "speaker": "主角", "emotion": "neutral", "is_dialogue": True}
        ])[0]
        seg_narration = processor.generate_acoustic_schedule([
            {"text": "旁白。", "speaker": "旁白", "emotion": "neutral", "is_dialogue": False}
        ])[0]
        assert seg_dialogue.paragraph_type == "dialogue"
        assert seg_narration.paragraph_type == "narration"

    def test_last_paragraph_transition_to_end(self):
        """最后一段过渡到 end 类型."""
        processor = AudioPostProcessor()
        segments = processor.generate_acoustic_schedule([
            {"text": "第一段。", "speaker": "旁白", "emotion": "neutral", "is_dialogue": False, "paragraph_type": "narration"},
            {"text": "最后一段。", "speaker": "旁白", "emotion": "neutral", "is_dialogue": False, "paragraph_type": "narration"},
        ])
        # 最后一段的 next_para_type = "end"
        # TRANSITION_PAUSE_MAP[("narration", "end")] 不存在，使用默认 300
        # 所以最后一段 pause_after 应该是 base(300) + punct + length
        last_seg = segments[-1]
        assert last_seg.pause_after_ms >= 300

    def test_process_single_with_next_para_type(self):
        """process_single 方法支持指定下一段落类型."""
        processor = AudioPostProcessor()
        # 单独处理，指定下一段是 dialogue
        seg = processor.process_single(
            {"text": "测试段落。", "speaker": "旁白", "emotion": "neutral", "is_dialogue": False},
            next_para_type="dialogue"
        )
        # narration -> dialogue = 550ms base pause
        assert seg.pause_after_ms >= 550
        assert seg.paragraph_type == "narration"

    def test_process_single_dialogue_to_narration(self):
        """process_single: 对话转旁白过渡."""
        processor = AudioPostProcessor()
        seg = processor.process_single(
            {"text": "再见！", "speaker": "主角", "emotion": "sad", "is_dialogue": True},
            next_para_type="narration"
        )
        # dialogue -> narration = 600ms base pause
        assert seg.pause_after_ms >= 600
        assert seg.paragraph_type == "dialogue"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])