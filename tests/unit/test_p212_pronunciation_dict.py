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


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
