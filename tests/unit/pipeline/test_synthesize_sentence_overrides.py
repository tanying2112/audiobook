"""#10 (2026-10-14): 句级 voice-aware 字典应用首测.

验证 _synthesize_paragraph_with_overrides 内:
- 按句切分用 original_text (字典前原文)
- 每句在 voice 归一化后按该句实际音色 apply_pronunciation_dict
- voice_variants 分音色选注音: 不同音色命中不同 variant
- FakeRemoteTTSPort 捕获逐句 payload.text/voice_id 断言
"""

import pytest
from unittest.mock import MagicMock, patch

from audiobook_studio.pipeline.synthesize import SynthesizePipeline, _split_sentences
from audiobook_studio.schemas.tts_routing import TtsRoutingInput
from audiobook_studio.schemas.paragraph import ParagraphAnnotation
from audiobook_studio.schemas.book import CharacterVoiceBinding
from audiobook_studio.tts.pronunciation_dict import DictEntry


class TestSentenceOverridesVoiceAwarePronunciation:
    """句级 voice override + voice_variants 分音色注音."""

    def _make_registry(self):
        """模拟 Lenda 分支 C 矩阵: am_adam 用默认 "Len da", am_onyx 需 "Lenn-dah"."""
        return {
            "Lenda": DictEntry(
                phoneme="Len da",
                source="heuristic",
                voice_variants={
                    "am_adam": "Len da",
                    "am_onyx": "Lenn-dah",
                },
            )
        }

    def _make_input(self, sentence_overrides):
        return TtsRoutingInput(
            paragraph_annotation=ParagraphAnnotation(
                paragraph_index=0,
                speaker_canonical_name="Narrator",
                is_dialogue=False,
                emotion="neutral",
                emotion_intensity=0.5,
                speech_rate=1.0,
                pitch_shift_semitones=0,
                pause_before_ms=300,
                pause_after_ms=500,
                confidence=0.9,
                difficulty="A",
            ),
            text="Lenda runs. Lenda scores.",  # 两句
            character_voice_map=[
                CharacterVoiceBinding(
                    canonical_name="Narrator",
                    aliases=[],
                    gender="neutral",
                    age_range="adult",
                    suggested_voice_id="am_adam",
                    sample_quote="",
                )
            ],
            book_id="test",
            chapter_index=1,
            paragraph_index=0,
            language="en",
            prefer_local=True,
            sentence_overrides=sentence_overrides,
            difficulty="A",
        )

    @pytest.mark.asyncio
    async def test_sentence_overrides_voice_aware_pronunciation(self, tmp_path):
        """句级 voice override → 句级字典应用：不同音色命中不同 voice_variants."""
        # 准备：注入含 voice_variants 的 registry
        test_registry = self._make_registry()

        # monkeypatch load_pronunciation_dict 返回测试 registry
        # 注意：run() 内部 from ..tts.pronunciation_dict import load_pronunciation_dict
        with patch("audiobook_studio.tts.pronunciation_dict.load_pronunciation_dict") as mock_load:
            mock_load.return_value = test_registry

            pipe = SynthesizePipeline(mock_mode=True, output_dir=str(tmp_path))
            # 不 mock _synthesize_via_port，让 FakeRemoteTTSPort 真跑捕获逐句 payload

            inp = self._make_input([
                {"idx": 0, "voice_id": "am_adam"},   # 第1句用 am_adam → "Len da"
                {"idx": 1, "voice_id": "am_onyx"},   # 第2句用 am_onyx → "Lenn-dah"
            ])
            await pipe.run([inp])

            # 检查 FakeRemoteTTSPort 捕获的逐句 payload
            port = pipe._port
            task_ids = [tid for tid in port._tasks if tid.startswith("test_ch1_p0_s")]
            assert len(task_ids) == 2, f"期望 2 个句子 task，实际 {len(task_ids)}: {task_ids}"

            # task_id 格式: {segment_id}_s{k}-{ts}，按 k 排序
            sorted_tids = sorted(task_ids, key=lambda x: int(x.split("_s")[1].split("-")[0]))
            texts = [port._tasks[tid].payload.text for tid in sorted_tids]
            voices = [port._tasks[tid].payload.voice_anchor.voice_id for tid in sorted_tids]

            # 第1句文本应含 "Len da"，第2句应含 "Lenn-dah"
            assert "Len da" in texts[0], f"句1 未应用 am_adam variant: {texts[0]}"
            assert "Lenn-dah" in texts[1], f"句2 未应用 am_onyx variant: {texts[1]}"
            assert voices[0] == "am_adam"
            assert voices[1] == "am_onyx"

    @pytest.mark.asyncio
    async def test_sentence_overrides_fallback_default_when_no_variant(self, tmp_path):
        """句级音色不在 variants → 回落默认 phoneme (与段落级行为一致)."""
        test_registry = self._make_registry()

        with patch("audiobook_studio.tts.pronunciation_dict.load_pronunciation_dict") as mock_load:
            mock_load.return_value = test_registry

            pipe = SynthesizePipeline(mock_mode=True, output_dir=str(tmp_path))

            # 用 am_fenrir (registry 无此音色) → 应回落默认 "Len da"
            inp = self._make_input([
                {"idx": 0, "voice_id": "am_fenrir"},
                {"idx": 1, "voice_id": "am_fenrir"},
            ])
            await pipe.run([inp])

            port = pipe._port
            task_ids = [tid for tid in port._tasks if tid.startswith("test_ch1_p0_s")]
            assert len(task_ids) == 2
            sorted_tids = sorted(task_ids, key=lambda x: int(x.split("_s")[1].split("-")[0]))
            texts = [port._tasks[tid].payload.text for tid in sorted_tids]

            # 两句都应回落默认 "Len da"
            assert "Len da" in texts[0], f"句1 回落失败: {texts[0]}"
            assert "Len da" in texts[1], f"句2 回落失败: {texts[1]}"

    @pytest.mark.asyncio
    async def test_split_sentences_preserves_original_text(self):
        """_split_sentences 用 original_text 切句，不依赖已字典化文本."""
        # 这个测试确保 run() 传给句路径的是字典前原文
        # 由 run() 的 original_text_by_seg 机制保证，此处仅测试切句函数本身
        text = "Lenda runs. Lenda scores."
        sentences = _split_sentences(text)
        assert sentences == ["Lenda runs.", "Lenda scores."]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])