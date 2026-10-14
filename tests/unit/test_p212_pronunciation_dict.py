"""P2.12 发音字典 — 注音替换 + 项目级覆盖 + 向后兼容 测试.

红线A 区分: 本测验**接线/替换逻辑** (字典加载、长词优先、项目覆盖、空字典透传),
不验真实音频读音 (那是引擎层, 由 §38 验收脚本互补)。
"""

import os

from audiobook_studio.tts.pronunciation_dict import (
    apply_pronunciation_dict,
    load_pronunciation_dict,
)


class TestP212PronunciationDict:
    def test_empty_registry_passes_text_through(self):
        """无字典条目 → 原样透传 (向后兼容, 主路径不破)。"""
        out = apply_pronunciation_dict("普通文本无任何生造词", {})
        assert out == "普通文本无任何生造词"

    def test_replacement_uses_phoneme(self):
        """有条目 → 替换为 phoneme 正文。"""
        out = apply_pronunciation_dict("帝释天", {"帝释天": type("E", (), {"phoneme": "dì shì tiān"})()})
        assert out == "dì shì tiān"

    def test_long_word_priority_short_does_not_eat_long(self):
        """长词优先: '帝' 不应吃掉 '帝释天' 内的子串。"""
        from audiobook_studio.tts.pronunciation_dict import DictEntry

        reg = {
            "帝": DictEntry(phoneme="dì", source="rule_ns"),
            "帝释天": DictEntry(phoneme="dì shì tiān", source="rule_ns"),
        }
        out = apply_pronunciation_dict("帝释天降临", reg)
        # 长词先替换 → '帝释天' 整体被换, '帝'(短词)不应残留误吃
        assert "dì shì tiān" in out
        assert "帝释天" not in out

    def test_phoneme_equal_to_word_skipped(self):
        """替换体与原词相同 → 跳过空操作。"""
        from audiobook_studio.tts.pronunciation_dict import DictEntry

        reg = {"无操作": DictEntry(phoneme="无操作", source="rule_ns")}
        out = apply_pronunciation_dict("这段无操作", reg)
        assert out == "这段无操作"

    def test_global_dict_loads_from_repo_config(self):
        """全局字典 (config/pronunciation_dict.yaml) 真实加载到条目。"""
        reg = load_pronunciation_dict()
        assert len(reg) > 0, "全局字典应有示例条目"
        assert "帝释天" in reg  # 该条目在 repo config 中标 rule_ns

    def test_project_dict_overrides_global_same_name(self):
        """项目级字典同名词目覆盖全局; 不同名词目补充。"""
        import tempfile
        from pathlib import Path

        d = tempfile.mkdtemp()
        with open(os.path.join(d, "pronunciation_dict.yaml"), "w", encoding="utf-8") as f:
            f.write(
                "entries:\n"
                "  帝释天:\n    phoneme: PROJ_OVERRIDE\n    source: manual\n"
                "  项目专属词:\n    phoneme: proj-only\n    source: manual\n"
            )
        reg = load_pronunciation_dict(project_dir=Path(d))
        assert reg["帝释天"].phoneme == "PROJ_OVERRIDE", "项目级未覆盖全局同名条目"
        assert reg["项目专属词"].phoneme == "proj-only", "项目独有条目应补充进来"
        # 全局独有的条目 (如 仙尊) 仍保留
        assert reg["仙尊"].phoneme == "xiān zūn" or reg.get("仙尊") is not None

    def test_missing_project_dict_keeps_global(self):
        """项目级不存在 → 仅用全局 (降级不崩)。"""
        import tempfile
        from pathlib import Path

        d = tempfile.mkdtemp()  # 空目录, 无项目级字典
        reg = load_pronunciation_dict(project_dir=Path(d))
        assert len(reg) > 0, "项目级缺失应保留全局条目"


class TestVoiceVariants:
    """Gap #7 (2026-10-13) 词条音色矩阵 → voice_variants 分音色注音。

    矩阵实证 (kokoro 10 音色 × SenseVoice 回听整词命中, 见
    scratch/ff_system/f_pron_voice_matrix.py + f_pron_validation/matrix/):
    "Len da" 6/10 音色命中; am_liam/am_michael/am_puck 一致失败但
    "Lenn-dah" 命中; am_onyx 词条+6 变体全失败 (池内不可修, 回落默认)。
    本类验接线/选注音逻辑; 音频实证在矩阵脚本 (红线A 区分)。
    """

    def _lenda_reg(self):
        from audiobook_studio.tts.pronunciation_dict import DictEntry

        return {
            "Lenda": DictEntry(
                phoneme="Len da",
                source="heuristic",
                voice_variants={
                    "am_liam": "Lenn-dah",
                    "am_michael": "Lenn-dah",
                    "am_puck": "Lenn-dah",
                },
            )
        }

    def test_no_voice_id_keeps_default_phoneme(self):
        """不传 voice_id → 默认 phoneme (向后兼容: 旧调用方语义不变)。"""
        out = apply_pronunciation_dict("The second is Lenda.", self._lenda_reg())
        assert out == "The second is Len da."

    def test_voice_id_selects_variant(self):
        """音色命中 variants → 该音色专用注音。"""
        out = apply_pronunciation_dict(
            "The second is Lenda.", self._lenda_reg(), voice_id="am_liam"
        )
        assert out == "The second is Lenn-dah."

    def test_voice_id_not_in_variants_falls_back(self):
        """音色不在 variants (如 am_onyx 池内不可修) → 回落默认 phoneme。"""
        out = apply_pronunciation_dict(
            "The second is Lenda.", self._lenda_reg(), voice_id="am_onyx"
        )
        assert out == "The second is Len da."

    def test_identity_variant_reads_original_word(self):
        """恒等变体 (值=原词拼写) → 该音色按原词读 (不伤害红线); 其他音色仍走默认。"""
        from audiobook_studio.tts.pronunciation_dict import DictEntry

        reg = {"futsal": DictEntry(phoneme="foot-sal", voice_variants={"am_puck": "futsal"})}
        out = apply_pronunciation_dict("We played futsal.", reg, voice_id="am_puck")
        assert out == "We played futsal."
        out2 = apply_pronunciation_dict("We played futsal.", reg, voice_id="am_adam")
        assert out2 == "We played foot-sal."

    def test_entry_without_variants_ignores_voice_id(self):
        """无 voice_variants 条目 → voice_id 不产生任何效果。"""
        from audiobook_studio.tts.pronunciation_dict import DictEntry

        reg = {"Lenda": DictEntry(phoneme="Len da", source="heuristic")}
        out = apply_pronunciation_dict("Lenda", reg, voice_id="am_liam")
        assert out == "Len da"

    def test_voices_block_parsed_from_yaml(self):
        """yaml voices: 块 → voice_variants (空值滤除; 项目级覆盖全局同名词)。"""
        import tempfile
        from pathlib import Path

        d = tempfile.mkdtemp()
        with open(os.path.join(d, "pronunciation_dict.yaml"), "w", encoding="utf-8") as f:
            f.write(
                "entries:\n"
                "  Lenda:\n"
                '    phoneme: "Len da"\n'
                "    source: heuristic\n"
                "    voices:\n"
                '      am_liam: "Lenn-dah"\n'
                '      am_michael: "Lenn-dah"\n'
                '      am_puck: "Lenn-dah"\n'
                '      am_onyx: ""\n'
            )
        reg = load_pronunciation_dict(project_dir=Path(d))
        assert reg["Lenda"].voice_variants == {
            "am_liam": "Lenn-dah",
            "am_michael": "Lenn-dah",
            "am_puck": "Lenn-dah",
        }, "voices: 块应解析为 voice_variants 且空值被滤除"


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
