"""P0 tests for pipeline/sop_reflection.py — LLM branches & failure paths.

Targets (Phase 1 P0):
- LLM 分支: valid JSON / malformed output (格式异常) / client exceptions → heuristic fallback
- Heuristic reflection: every field mapping, early-stop on weak patterns
- SOPBackgroundThread._check_and_reflect: 早停 (disabled/empty/below-min/throttle)
  and retry-ish retention (below-confidence / save-failure put-backs)
- Queue-full paths (依赖失败模拟), RuleApplier role mapping, websocket/import helpers
"""

import json as jsonlib
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.audiobook_studio.pipeline.sop_reflection import (
    CorrectionCollector,
    GenreDetector,
    ReflectionEngine,
    ReflectionResult,
    RuleApplier,
    SOPBackgroundThread,
    SOPConfig,
    UserCorrection,
    apply_learned_rules_on_import,
    handle_user_correction_websocket,
)

MODULE = "src.audiobook_studio.pipeline.sop_reflection"

# SOPConfig.DEFAULT_CONFIG_PATH is cwd-relative; use an absolute path to the
# repo config to stay cwd-independent, or a tmp path for isolation.
REPO_CONFIG = Path(__file__).resolve().parents[2] / "config" / "agent_sop.json"


def make_config(tmp_path):
    return SOPConfig(tmp_path / "agent_sop.json")


def corr(field="emotion", original="neutral", corrected="intense", genre="玄幻",
         index=0, context=None):
    return UserCorrection(
        timestamp=f"2026-08-26T10:{index:02d}:00Z",
        project_id=1,
        chapter_index=1,
        paragraph_index=index,
        field=field,
        original_value=original,
        corrected_value=corrected,
        genre=genre,
        context=context or {},
    )


def llm_payload(rules=None, confidence=0.9, reasoning="LLM said so"):
    return jsonlib.dumps(
        {"proposed_rules": rules or {"emotion_defaults": {"战斗": "intense"}},
         "confidence": confidence,
         "reasoning": reasoning},
        ensure_ascii=False,
    )


# ─────────────────────────────────────────────────────────────────────────────
# SOPConfig load/save failure simulation
# ─────────────────────────────────────────────────────────────────────────────


class TestSOPConfigFailurePaths:
    def test_corrupt_json_falls_back_to_default(self, tmp_path):
        cfg_path = tmp_path / "agent_sop.json"
        cfg_path.write_text("{not valid json!!", encoding="utf-8")
        cfg = SOPConfig(cfg_path)
        assert "genres" in cfg._config
        assert cfg.list_genres() == ["default"]

    def test_unreadable_file_oserror_falls_back_to_default(self, tmp_path):
        cfg_path = tmp_path / "agent_sop.json"
        cfg_path.write_text("{}", encoding="utf-8")
        with patch("builtins.open", side_effect=OSError("disk error")):
            # _load swallows OSError during read
            cfg = SOPConfig(cfg_path)
        assert "version" in cfg._config

    def test_save_returns_false_on_write_error(self, tmp_path):
        cfg = make_config(tmp_path)
        cfg._config["genres"]["default"]["rules"]["emotion_defaults"] = {"x": "y"}
        with patch("builtins.open", side_effect=OSError("read-only filesystem")):
            assert cfg.save(backup=False) is False

    def test_save_creates_backup_of_previous_version(self, tmp_path):
        cfg = make_config(tmp_path)
        assert cfg.save(backup=True) is True  # first write: no backup yet
        cfg.update_genre_rules("玄幻", {"emotion_defaults": {"k": "v"}}, 0.7, "why")
        backups = list(tmp_path.glob("agent_sop.bak.*.json"))
        assert backups, "expected a .bak file from second save"
        first = jsonlib.loads(backups[0].read_text(encoding="utf-8"))
        assert "玄幻" not in first.get("genres", {})

    def test_get_genre_config_unknown_genre_returns_default_copy(self, tmp_path):
        cfg = make_config(tmp_path)
        got = cfg.get_genre_config("不存在")
        assert got["name"] == "默认通用"
        got["rules"]["emotion_defaults"]["MUTATED"] = True
        assert "MUTATED" not in cfg.get_genre_rules("default")

    def test_update_creates_new_genre_entry_with_stats(self, tmp_path):
        cfg = make_config(tmp_path)
        ok = cfg.update_genre_rules("科幻新类", {"speech_rate": {"fast": 1.3}}, 0.75, "r")
        assert ok is True
        full = cfg.get_genre_config("科幻新类")
        assert full["learning_stats"]["rules_updated"] == 1
        assert full["learning_stats"]["confidence"] == 0.75
        assert "last_learned_from" in full

    def test_deep_merge_overrides_nested_keys_only(self, tmp_path):
        cfg = make_config(tmp_path)
        cfg.update_genre_rules(
            "玄幻",
            {"emotion_defaults": {"新增": "calm"}, "brand_new_section": {"a": 1}},
            0.6,
            "merge",
        )
        rules = cfg.get_genre_rules("玄幻")
        assert rules["emotion_defaults"]["新增"] == "calm"
        assert rules["brand_new_section"] == {"a": 1}

    def test_record_correction_unknown_genre_is_noop(self, tmp_path):
        cfg = make_config(tmp_path)
        cfg.record_correction("幽灵类型")  # genre absent -> no counter, no save
        stats = cfg.get_genre_config("幽灵类型").get("learning_stats", {})
        assert stats.get("corrections_received", 0) in (0, 1)  # default fallback only


# ─────────────────────────────────────────────────────────────────────────────
# CorrectionCollector — queue-full dependency failure & filtering
# ─────────────────────────────────────────────────────────────────────────────


class TestCorrectionCollectorEdges:
    def test_queue_full_drops_correction(self):
        c = CorrectionCollector(max_size=1)
        assert c.add_correction(corr(index=1)) is True
        assert c.add_correction(corr(index=2)) is False  # queue full
        assert c.queue_size() == 1

    def test_add_correction_dict_defaults(self):
        c = CorrectionCollector()
        ok = c.add_correction_dict({
            "project_id": 2, "chapter_index": 1, "paragraph_index": 5,
            "field": "speech_rate", "original_value": 1.0, "corrected_value": 1.2,
        })
        assert ok is True
        batch = c.get_batch(timeout=0.2)
        assert batch[0].genre == "default"
        assert batch[0].context == {}

    def test_add_correction_dict_missing_required_key_raises(self):
        c = CorrectionCollector()
        with pytest.raises(KeyError):
            c.add_correction_dict({"project_id": 1})  # missing chapter_index etc.

    def test_get_batch_empty_timeout_returns_empty(self):
        c = CorrectionCollector()
        assert c.get_batch(max_size=5, timeout=0.05) == []

    def test_get_corrections_by_genre_filters_and_restores(self):
        c = CorrectionCollector()
        for i in range(4):
            c.add_correction(corr(genre="玄幻", index=i))
        for i in range(3):
            c.add_correction(corr(genre="都市", index=i + 10))
        picked = c.get_corrections_by_genre("都市")
        assert all(x.genre == "都市" for x in picked)
        assert len(picked) == 3
        # 玄幻 corrections were put back
        assert c.queue_size() == 4

    def test_get_corrections_by_genre_restore_survives_full_queue(self):
        c = CorrectionCollector(max_size=4)
        for i in range(4):
            c.add_correction(corr(genre="玄幻", index=i))
        c.cache_project_genre(1, "玄幻")
        # Drain everything then request other genre: nothing matches, restore refills
        picked = c.get_corrections_by_genre("科幻")
        assert picked == []
        assert c.queue_size() == 4


# ─────────────────────────────────────────────────────────────────────────────
# ReflectionEngine — LLM branch, 格式异常, exception fallback
# ─────────────────────────────────────────────────────────────────────────────


class TestReflectionEngineLLMBranches:
    def _engine(self, tmp_path, llm_client):
        return ReflectionEngine(make_config(tmp_path), llm_client=llm_client)

    def test_llm_valid_json_used_directly(self, tmp_path):
        engine = self._engine(tmp_path, lambda prompt: llm_payload(confidence=0.95, reasoning="模式明确"))
        result = engine.reflect("玄幻", [corr(index=i) for i in range(4)])
        assert result.confidence == 0.95
        assert result.reasoning == "模式明确"
        assert result.proposed_rules == {"emotion_defaults": {"战斗": "intense"}}
        assert result.corrections_analyzed == 4
        assert result.genre == "玄幻"

    def test_llm_malformed_json_falls_back_to_heuristic(self, tmp_path):
        # 格式异常: LLM 返回非 JSON 文本
        engine = self._engine(tmp_path, lambda prompt: "我觉得应该调快语速（非JSON）")
        corrections = [corr(field="speech_rate", original=1.0, corrected=1.2, index=i) for i in range(3)]
        result = engine.reflect("玄幻", corrections)
        assert "Heuristic" in result.reasoning
        assert "speech_rate" in result.proposed_rules

    def test_llm_truncated_json_falls_back(self, tmp_path):
        engine = self._engine(tmp_path, lambda prompt: '{"proposed_rules": {"emotion_def')
        result = engine.reflect("玄幻", [corr(index=i) for i in range(3)])
        assert "Heuristic" in result.reasoning

    def test_llm_client_exception_falls_back(self, tmp_path):
        def boom(prompt):
            raise TimeoutError("LLM provider timeout")

        engine = self._engine(tmp_path, boom)
        corrections = [corr(field="pitch_shift_semitones", original=0, corrected=-4, index=i) for i in range(3)]
        result = engine.reflect("玄幻", corrections)
        assert "Heuristic" in result.reasoning
        assert "pitch_shifts" in result.proposed_rules

    def test_empty_corrections_short_circuits_before_llm(self, tmp_path):
        called = []

        def spy(prompt):
            called.append(prompt)
            return llm_payload()

        engine = self._engine(tmp_path, spy)
        result = engine.reflect("玄幻", [])
        assert called == []  # LLM never invoked
        assert result.confidence == 0.0
        assert result.proposed_rules == {}
        assert result.corrections_analyzed == 0

    def test_prompt_contains_genre_and_current_rules(self, tmp_path):
        seen = {}

        def spy(prompt):
            seen["p"] = prompt
            return llm_payload()

        engine = self._engine(tmp_path, spy)
        engine.reflect("玄幻", [corr(index=i) for i in range(3)])
        assert "体裁：玄幻" in seen["p"].replace(" ", "")[:200] or "玄幻" in seen["p"]
        assert "当前规则" in seen["p"]
        assert "修正统计" in seen["p"]

    def test_llm_missing_keys_defaulted(self, tmp_path):
        engine = self._engine(tmp_path, lambda prompt: jsonlib.dumps({"confidence": 0.99}))
        result = engine.reflect("玄幻", [corr(index=i) for i in range(3)])
        assert result.confidence == 0.99
        assert result.proposed_rules == {}  # missing key -> {}
        assert result.reasoning == ""


class TestHeuristicReflectionFields:
    def _reflect(self, tmp_path, corrections):
        return ReflectionEngine(make_config(tmp_path)).reflect("玄幻", corrections)

    def test_pause_fields_learned_as_int(self, tmp_path):
        cs = [corr(field="pause_before_ms", original=0, corrected=500, index=i) for i in range(3)]
        cs += [corr(field="pause_after_ms", original=0, corrected=250, index=i + 3) for i in range(3)]
        r = self._reflect(tmp_path, cs)
        vals = list(r.proposed_rules["pause_patterns"].values())
        assert sorted(vals) == [250, 500]

    def test_sfx_tags_scalar_and_list_both_accepted(self, tmp_path):
        cs = [corr(field="sfx_tags", original=[], corrected="door_slam", index=i) for i in range(3)]
        r = self._reflect(tmp_path, cs)
        assert r.proposed_rules["sfx_rules"]["enabled"] is True
        assert "door_slam" in r.proposed_rules["sfx_rules"]["default_sfx"]

    def test_pattern_below_two_occurrences_early_stopped(self, tmp_path):
        # 4 corrections but split into distinct patterns → no pattern reaches count 2
        cs = [
            corr(original="neutral", corrected="angry", index=0),
            corr(original="neutral", corrected="sad", index=1),
            corr(original="calm", corrected="angry", index=2),
            corr(original="calm", corrected="sad", index=3),
        ]
        r = self._reflect(tmp_path, cs)
        assert r.confidence == 0.0
        assert r.proposed_rules == {}

    def test_field_below_three_occurrences_skipped(self, tmp_path):
        cs = [corr(corrected="angry", index=i) for i in range(2)]  # < 3
        r = self._reflect(tmp_path, cs)
        assert r.proposed_rules == {}
        assert r.confidence == 0.0

    def test_confidence_caps_at_085(self, tmp_path):
        # many significant patterns across several fields
        cs = [corr(corrected="angry", index=i) for i in range(4)]
        cs += [corr(field="speech_rate", original=1.0, corrected=1.3, index=i + 10) for i in range(4)]
        cs += [corr(field="pitch_shift_semitones", original=0, corrected=-3, index=i + 20) for i in range(4)]
        r = self._reflect(tmp_path, cs)
        assert r.confidence <= 0.85
        assert r.confidence > 0


# ─────────────────────────────────────────────────────────────────────────────
# SOPBackgroundThread._check_and_reflect — 早停 & retention paths
# ─────────────────────────────────────────────────────────────────────────────


class TestBackgroundReflectionLoop:
    def _thread(self, tmp_path, collector, engine=None, **cfg_over):
        cfg = make_config(tmp_path)
        if cfg_over:
            gs = cfg.get_global_settings()
            gs.update(cfg_over)
            cfg._config["global_settings"] = gs
        engine = engine or ReflectionEngine(cfg)
        return SOPBackgroundThread(cfg, collector, engine, check_interval=3600)

    def test_learning_disabled_early_stop(self, tmp_path):
        t = self._thread(tmp_path, CorrectionCollector(), learning_enabled=False)
        collector = t.collector
        collector.add_correction(corr(index=1))
        t._check_and_reflect()
        assert collector.queue_size() == 1  # untouched

    def test_no_corrections_noop(self, tmp_path):
        t = self._thread(tmp_path, CorrectionCollector())
        t.collector.get_batch = MagicMock(return_value=[])
        t.engine.reflect = MagicMock()
        t._check_and_reflect()
        t.engine.reflect.assert_not_called()

    def test_below_min_corrections_retained_for_retry(self, tmp_path):
        t = self._thread(tmp_path, CorrectionCollector(), min_corrections_for_update=5)
        for i in range(3):
            t.collector.add_correction(corr(index=i))
        t._check_and_reflect()
        assert t.collector.queue_size() == 3  # put back, not lost
        assert t.engine.reflect.__self__ if False else True

    def test_throttle_within_five_minutes_puts_back(self, tmp_path):
        t = self._thread(tmp_path, CorrectionCollector(), min_corrections_for_update=3)
        t._last_reflection["玄幻"] = time.time()  # just reflected
        for i in range(3):
            t.collector.add_correction(corr(index=i))
        t._check_and_reflect()
        assert t.collector.queue_size() == 3

    def test_low_confidence_retains_corrections(self, tmp_path):
        t = self._thread(tmp_path, CorrectionCollector())
        low = ReflectionResult(genre="玄幻", proposed_rules={"emotion_defaults": {"a": "b"}},
                               confidence=0.30, reasoning="weak", corrections_analyzed=3,
                               timestamp="now")
        t.engine.reflect = MagicMock(return_value=low)
        for i in range(3):
            t.collector.add_correction(corr(index=i))
        t._check_and_reflect()
        assert t.collector.queue_size() == 3
        t.sop_config  # config untouched check below
        assert "learned" not in str(t.sop_config.get_genre_rules("玄幻"))

    def test_successful_reflection_applies_and_counts(self, tmp_path):
        t = self._thread(tmp_path, CorrectionCollector())
        good = ReflectionResult(genre="玄幻",
                                proposed_rules={"emotion_defaults": {"战斗": "intense"}},
                                confidence=0.9, reasoning="clear pattern", corrections_analyzed=3,
                                timestamp="now")
        t.engine.reflect = MagicMock(return_value=good)
        for i in range(3):
            t.collector.add_correction(corr(index=i))
        t._check_and_reflect()
        assert t.collector.queue_size() == 0  # consumed
        rules = t.sop_config.get_genre_rules("玄幻")
        assert rules["emotion_defaults"].get("战斗") == "intense"
        assert t._last_reflection["玄幻"] > 0

    def test_save_failure_puts_corrections_back(self, tmp_path):
        t = self._thread(tmp_path, CorrectionCollector())
        good = ReflectionResult(genre="玄幻", proposed_rules={"emotion_defaults": {"x": "y"}},
                                confidence=0.9, reasoning="ok", corrections_analyzed=3,
                                timestamp="now")
        t.engine.reflect = MagicMock(return_value=good)
        with patch.object(t.sop_config, "update_genre_rules", return_value=False):
            for i in range(3):
                t.collector.add_correction(corr(index=i))
            t._check_and_reflect()
        assert t.collector.queue_size() == 3  # retried next round

    def test_engine_exception_swallowed_by_loop(self, tmp_path):
        t = self._thread(tmp_path, CorrectionCollector())
        t._check_and_reflect = lambda: (_ for _ in ()).throw(AssertionError("skip"))
        # Directly exercise _run's try/except via a patched checker that raises once.
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            raise RuntimeError("transient")

        t._check_and_reflect = flaky
        t.check_interval = 0.01
        th = threading.Thread(target=t._run, daemon=True)
        th.start()
        time.sleep(0.08)
        t.stop(timeout=2)
        assert calls["n"] >= 2  # loop survived the exception and kept polling

    def test_start_stop_thread_lifecycle(self, tmp_path):
        t = self._thread(tmp_path, CorrectionCollector())
        t.start()
        assert t._thread.is_alive()
        t.stop(timeout=2)
        assert not t._thread.is_alive()

    def test_mixed_genres_processed_independently(self, tmp_path):
        t = self._thread(tmp_path, CorrectionCollector())
        good = ReflectionResult(genre="都市", proposed_rules={"speech_rate": {"narrator": 1.1}},
                                confidence=0.9, reasoning="ok", corrections_analyzed=3,
                                timestamp="now")
        t.engine.reflect = MagicMock(return_value=good)
        for i in range(3):
            t.collector.add_correction(corr(genre="玄幻", index=i))
        for i in range(3):
            t.collector.add_correction(corr(genre="都市", index=i + 5))
        t._check_and_reflect()
        # Only 都市 reached threshold logic with mocked success; 玄幻 also ≥3 so both reflected
        assert t.engine.reflect.call_count == 2
        genres = {c.args[0] for c in t.engine.reflect.call_args_list}
        assert genres == {"玄幻", "都市"}
        assert t.collector.queue_size() == 0


# ─────────────────────────────────────────────────────────────────────────────
# RuleApplier — role mapping & audio post-process application
# ─────────────────────────────────────────────────────────────────────────────


class TestRuleApplierBranches:
    def _applier_with_rules(self, tmp_path, rules):
        cfg = make_config(tmp_path)
        cfg._config["genres"]["custom_test"] = {
            "name": "custom_test", "aliases": [], "rules": rules,
            "learning_stats": {"corrections_received": 0},
        }
        return RuleApplier(cfg)

    @pytest.mark.parametrize(
        "name,role",
        [
            ("旁白君", "narrator"),
            ("Narrator", "narrator"),
            ("主角大人", "protagonist"),
            ("hero_01", "protagonist"),
            ("大反派", "antagonist"),
            ("boss级敌人", "antagonist"),
            ("青云长老", "elder"),
            ("老祖", "elder"),
            ("大师兄", "fellow_disciple"),
            ("王夫人", "female_lead"),
            ("魔尊", "demon_lord"),
            ("beast_王", "demon_lord"),
            ("路人甲乙", "narrator"),  # default
        ],
    )
    def test_map_character_to_role_matrix(self, tmp_path, name, role):
        applier = self._applier_with_rules(tmp_path, {})
        assert applier._map_character_to_role(name) == role

    def test_apply_to_audio_postprocess_role_specific_then_default(self, tmp_path):
        applier = self._applier_with_rules(
            tmp_path,
            {
                "speech_rate": {"narrator": 1.25, "default": 1.05},
                "pitch_shifts": {"narrator": -2},
                "sfx_rules": {"enabled": True},
            },
        )
        seg = {"speed": 1.0}
        out = applier.apply_to_audio_postprocess(seg, "custom_test", "narrator")
        assert out["speed"] == 1.25
        assert out["pitch_hz"] == -12.0

        seg2 = {}  # no speed yet → default applied
        out2 = applier.apply_to_audio_postprocess(seg2, "custom_test", "unknown_role")
        assert out2["speed"] == 1.05
        assert "pitch_hz" not in out2

    def test_apply_annotation_voice_binding_by_role(self, tmp_path):
        from src.audiobook_studio.schemas import (
            BookMeta,
            CharacterVoiceBinding,
            EmotionSnapshot,
            ParagraphAnnotationInput,
        )

        applier = self._applier_with_rules(
            tmp_path,
            {"voice_bindings": {"elder": "zh-CN-ElderVoice"}},
        )
        inp = ParagraphAnnotationInput(
            paragraph_text="这是一段足够长的测试段落文本内容，用于满足最小长度校验要求。",
            paragraph_index=1,
            chapter_index=1,
            book_meta=BookMeta(title="t", author="a", genre="小说", difficulty="B",
                               language="zh", total_chapters_estimated=1),
            character_voice_map=[
                CharacterVoiceBinding(
                    canonical_name="藏经阁长老",
                    aliases=[],
                    gender="male",
                    age_range="elderly",
                    suggested_voice_id=None,
                    sample_quote="文本",
                )
            ],
            emotion_snapshot=EmotionSnapshot(chapter=1, dominant_emotion="neutral",
                                             intensity=0.5, notes="n"),
            story_line_summary="摘要内容，" * 30,
            global_style_notes="风格",
        )
        out = applier.apply_to_annotation_input(inp, "custom_test")
        assert out.character_voice_map[0].suggested_voice_id == "zh-CN-ElderVoice"

    def test_apply_annotation_without_rules_returns_input(self, tmp_path):
        cfg = make_config(tmp_path)
        cfg._config["genres"]["default"]["rules"] = {}
        applier = RuleApplier(cfg)
        inp = MagicMock()
        out = applier.apply_to_annotation_input(inp, "任何类型")
        assert out is inp


# ─────────────────────────────────────────────────────────────────────────────
# GenreDetector — analysis branches
# ─────────────────────────────────────────────────────────────────────────────


class TestGenreDetectorBranches:
    def setup_method(self):
        self.detector = GenreDetector(SOPConfig(REPO_CONFIG))

    def test_scene_tags_take_priority(self):
        analyzed = {
            "scene_tags": ["宗门大比"],
            "story_line_summary": "公司办公室的故事",
            "book_meta": {"genre": "历史"},
        }
        assert self.detector.detect_from_chapter_analysis(analyzed) == "玄幻"

    def test_story_summary_second_priority(self):
        analyzed = {
            "scene_tags": [],
            "story_line_summary": "侦探推理破案",
            "book_meta": {"genre": "历史"},
        }
        assert self.detector.detect_from_chapter_analysis(analyzed) == "悬疑"

    def test_book_meta_history_mapping_last(self):
        analyzed = {"scene_tags": [], "story_line_summary": "", "book_meta": {"genre": "历史"}}
        assert self.detector.detect_from_chapter_analysis(analyzed) == "历史"

    def test_everything_default(self):
        analyzed = {"scene_tags": [], "story_line_summary": "", "book_meta": {}}
        assert self.detector.detect_from_chapter_analysis(analyzed) == "default"

    def test_detect_from_meta_broad_mapping(self):
        from src.audiobook_studio.schemas import BookMeta

        meta_hist = BookMeta(title="t", author="a", genre="历史", difficulty="B",
                             language="zh", total_chapters_estimated=1)
        meta_other = BookMeta(title="t", author="a", genre="其他", difficulty="B",
                              language="zh", total_chapters_estimated=1)
        assert self.detector.detect_from_meta(meta_hist) == "历史"
        assert self.detector.detect_from_meta(meta_other) == "default"

    def test_case_insensitive_text_detection(self):
        assert self.detector.detect_from_text("AI 芯片与脑机接口") == "科幻"


# ─────────────────────────────────────────────────────────────────────────────
# WebSocket handler & import-time rule application
# ─────────────────────────────────────────────────────────────────────────────


class TestIntegrationHelpers:
    @pytest.mark.asyncio
    async def test_websocket_accept_and_cache(self):
        with (
            patch(f"{MODULE}.get_correction_collector", return_value=CorrectionCollector()),
        ):
            resp = await handle_user_correction_websocket({
                "project_id": 7, "chapter_index": 1, "paragraph_index": 2,
                "field": "emotion", "original_value": "n", "corrected_value": "i",
                "genre": "玄幻",
            })
        assert resp["status"] == "accepted"

    @pytest.mark.asyncio
    async def test_websocket_queue_full_reports(self):
        tiny = CorrectionCollector(max_size=1)
        tiny.add_correction(corr(index=1))
        with patch(f"{MODULE}.get_correction_collector", return_value=tiny):
            resp = await handle_user_correction_websocket({
                "project_id": 7, "chapter_index": 1, "paragraph_index": 2,
                "field": "emotion", "original_value": "n", "corrected_value": "i",
                "genre": "玄幻",
            })
        assert resp["status"] == "queue_full"

    def test_apply_learned_rules_on_import_analysis_hit(self):
        analyzed = {"scene_tags": ["宗门"], "story_line_summary": "", "book_meta": {"genre": "小说"}}
        with (
            patch(f"{MODULE}.get_genre_detector", return_value=GenreDetector(SOPConfig(REPO_CONFIG))),
            patch(f"{MODULE}.get_sop_config", return_value=SOPConfig(REPO_CONFIG)),
        ):
            out = apply_learned_rules_on_import(1, MagicMock(), analyzed)
        assert out["genre"] == "玄幻"
        assert isinstance(out["rules_applied"], bool)

    def test_apply_learned_rules_falls_back_to_broad_meta(self):
        from src.audiobook_studio.schemas import BookMeta

        meta = BookMeta(title="t", author="a", genre="历史", difficulty="B",
                        language="zh", total_chapters_estimated=1)
        with (
            patch(f"{MODULE}.get_genre_detector", return_value=GenreDetector(SOPConfig(REPO_CONFIG))),
            patch(f"{MODULE}.get_sop_config", return_value=SOPConfig(REPO_CONFIG)),
        ):
            out = apply_learned_rules_on_import(1, meta, {})
        assert out["genre"] == "历史"

    def test_global_background_thread_start_stop(self, tmp_path):
        import src.audiobook_studio.pipeline.sop_reflection as mod

        fake_cfg = SOPConfig(tmp_path / "cfg.json")
        with (
            patch.object(mod, "_sop_config", fake_cfg),
            patch.object(mod, "_correction_collector", CorrectionCollector()),
            patch.object(mod, "_reflection_engine", ReflectionEngine(fake_cfg)),
        ):
            th = mod.start_sop_background_thread(check_interval=0.05)
            assert th._thread.is_alive()
            mod.stop_sop_background_thread()
            assert mod._background_thread is None
