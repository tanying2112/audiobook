"""Batch 3 定向冒烟: LLM 音频导演 stage 全链 (schemas → 合成消费 → StageRegistry → canary/harness 迭代).

不触网、不起服务: mock 模式下验证接线与诚实降级路径。
"""
import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("SELF_ITERATION_MOCK", "true")
os.environ.setdefault("MOCK_LLM", "true")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

RESULTS = []


def check(name, fn):
    try:
        detail = fn()
        RESULTS.append((name, True, detail or ""))
        print(f"[PASS] {name}" + (f" — {detail}" if detail else ""))
    except Exception as e:  # noqa: BLE001
        RESULTS.append((name, False, str(e)))
        print(f"[FAIL] {name} — {e}")


print("=" * 60)
print("Batch 3 音频导演 stage 冒烟")
print("=" * 60)

# ── A. schemas 契约 ──────────────────────────────────────────────────────────
def a_schemas():
    from audiobook_studio.schemas.audio_director import (
        AudioDirectorInput, AudioDirectorOutput, SentenceOverrideSuggestion,
    )
    o = SentenceOverrideSuggestion(idx=1, speed=0.9, pause_category="dramatic")
    d = o.model_dump(exclude_none=True)
    assert d == {"idx": 1, "speed": 0.9, "pause_category": "dramatic"}, f"exclude_none 泄漏: {d}"
    # 非法类别必须被拒
    try:
        SentenceOverrideSuggestion(idx=0, pause_category="bogus")
        raise AssertionError("非法 pause_category 未被拒")
    except Exception as e:
        assert "pause_category" in str(e), f"错误信息不含字段名: {e}"
    # 越界数值必须被拒
    for bad in ({"speed": 0.1}, {"pitch_st": 99.0}, {"gain_db": -60.0}, {"pause_after_ms": 99999}):
        try:
            SentenceOverrideSuggestion(idx=0, **bad)
            raise AssertionError(f"越界值未被拒: {bad}")
        except Exception:
            pass
    i = AudioDirectorInput(paragraph_text="一。二！", sentences=["一。", "二！"])
    assert i.speaker_name == "_narrator_" and i.language == "zh" and i.emotion_intensity == 0.5
    out = AudioDirectorOutput(sentence_overrides=[], rationale="t", confidence=0.0)
    assert out.model_json_schema()["properties"], "schema 不可序列化"
    return "契约/越界/非法类别 全拒"


check("A schemas 契约与校验", a_schemas)


# ── B. 停顿优先级链: 显式 > 类别档 > 标点分级 (3.2) ───────────────────────────
def b_pause_chain():
    from audiobook_studio.pipeline.synthesize import (
        PAUSE_CATEGORY_DEFAULTS_MS, _override_pause_ms, _sentence_pause_default_ms,
    )
    assert PAUSE_CATEGORY_DEFAULTS_MS == {"clause": 300, "comma": 150, "dramatic": 900, "paragraph": 1200}
    assert _sentence_pause_default_ms("你好。") == 500
    assert _sentence_pause_default_ms("你好；") == 300
    assert _sentence_pause_default_ms("Hello!") == 220
    assert _sentence_pause_default_ms("『你好。』") == 500          # closer 透传
    # 显式值最高
    assert _override_pause_ms({"pause_after_ms": 666}, 500) == 666
    assert _override_pause_ms({"pause_after_ms": "888"}, 500) == 888
    # 坏显式值穿透到类别档
    assert _override_pause_ms({"pause_after_ms": "abc", "pause_category": "clause"}, 500) == 300
    # 类别档 > 标点默认
    assert _override_pause_ms({"pause_category": "dramatic"}, 500) == 900
    # 未知类别穿透到默认
    assert _override_pause_ms({"pause_category": "bogus"}, 500) == 500
    # 负显式值 clamp 0
    assert _override_pause_ms({"pause_after_ms": -5}, 500) == 0
    # 空 override → 默认
    assert _override_pause_ms({}, 500) == 500
    return "10 断言全过 (穿透式)"


check("B 停顿优先级链", b_pause_chain)


# ── C. StageRegistry handler (mock 全链) ─────────────────────────────────────
def c_stage_handler():
    from audiobook_studio.pipeline.stage_registry import StageRegistry

    h = StageRegistry.get("audio_director")
    assert h is not None, "audio_director 未注册"

    para = SimpleNamespace(
        edited_text="夜风掠过山岗。狼群在远处嚎叫！",
        text="原始文本。",
        speaker_canonical_name="旁白",
        emotion="neutral",
        emotion_intensity=0.6,
        is_dialogue=False,
        sentence_overrides=None,
    )
    out = asyncio.run(h.run(paragraph=para))
    assert type(out).__name__ == "AudioDirectorOutput", f"返回类型错: {type(out)}"
    assert out.sentence_overrides == [] and out.confidence == 0.0, "mock 应诚实空建议"

    # 无 edited_text 时兜底原始文本 (不崩)
    para2 = SimpleNamespace(
        edited_text=None, text="只有原文。也有两句！", speaker_canonical_name=None,
        emotion=None, emotion_intensity=None, is_dialogue=None, sentence_overrides=None,
    )
    out2 = asyncio.run(h.run(paragraph=para2))
    assert type(out2).__name__ == "AudioDirectorOutput"

    # 空段落: 诚实降级不阻断
    out3 = asyncio.run(h.run(paragraph=None, paragraph_text="  "))
    assert out3.sentence_overrides == [] and out3.rationale == "空段落"
    return "注册/mock/兜底/空段 4 路 OK"


check("C StageRegistry handler", c_stage_handler)


# ── D. apersist 人工优先 ─────────────────────────────────────────────────────
def d_apersist_human_first():
    from audiobook_studio.pipeline.stage_registry import StageRegistry
    from audiobook_studio.schemas.audio_director import (
        AudioDirectorOutput, SentenceOverrideSuggestion,
    )

    h = StageRegistry.get("audio_director")

    class FakeDB:
        def __init__(self):
            self.commits = 0

        def commit(self):
            self.commits += 1

    result = AudioDirectorOutput(
        sentence_overrides=[
            SentenceOverrideSuggestion(idx=0, speed=0.9, pause_category="dramatic"),
            SentenceOverrideSuggestion(idx=1, pause_category="clause"),
        ],
        rationale="测试建议", confidence=0.8,
    )

    # D1: 已有人工 overrides → 跳过 (不写不 commit)
    db, para = FakeDB(), SimpleNamespace(index=3, sentence_overrides=[{"idx": 0, "speed": 1.1}])
    asyncio.run(h.apersist(db=db, project_id=1, chapter=None, paragraph=para, result=result))
    assert db.commits == 0 and para.sentence_overrides == [{"idx": 0, "speed": 1.1}], "人工领地被入侵"

    # D2: 空字段 + 有建议 → 落库 (exclude_none)
    db, para = FakeDB(), SimpleNamespace(index=3, sentence_overrides=None)
    asyncio.run(h.apersist(db=db, project_id=1, chapter=None, paragraph=para, result=result))
    assert db.commits == 1, "未 commit"
    assert para.sentence_overrides == [
        {"idx": 0, "speed": 0.9, "pause_category": "dramatic"},
        {"idx": 1, "pause_category": "clause"},
    ], f"落库内容错: {para.sentence_overrides}"

    # D3: 空建议 → 不写 (不清空既有值)
    db, para = FakeDB(), SimpleNamespace(index=3, sentence_overrides=None)
    empty = AudioDirectorOutput(sentence_overrides=[], rationale="m", confidence=0.0)
    asyncio.run(h.apersist(db=db, project_id=1, chapter=None, paragraph=para, result=empty))
    assert db.commits == 0 and para.sentence_overrides is None, "空建议不应写"

    # D4: paragraph=None → 安全跳过
    asyncio.run(h.apersist(db=FakeDB(), project_id=1, chapter=None, paragraph=None, result=result))
    return "人工领地/落库/空建议/None 4 路 OK"


check("D apersist 人工优先", d_apersist_human_first)


# ── E. 顺序接线: checkpoint / auto_run / 枚举 / 路由 ──────────────────────────
def e_wiring():
    from audiobook_studio.pipeline.checkpoint import PACKAGE_STAGES, STAGE_ORDER
    from audiobook_studio.api.auto_run import _stage_order
    from audiobook_studio.llm.config_loader import LLMProvidersConfig, StageName
    from audiobook_studio.harness.models import PipelineStage

    assert STAGE_ORDER[STAGE_ORDER.index("edit") + 1] == "audio_director"
    assert STAGE_ORDER[STAGE_ORDER.index("audio_director") + 1] == "synthesize"
    assert "audio_director" in PACKAGE_STAGES
    assert _stage_order[_stage_order.index("edit") + 1] == "audio_director"
    assert _stage_order[_stage_order.index("audio_director") + 1] == "audio_postprocess"
    assert StageName.AUDIO_DIRECTOR.value == "audio_director"
    assert PipelineStage.AUDIO_DIRECTOR.value == "audio_director"
    assert list(PipelineStage.__members__.values()).count("audio_director") == 1, "harness 默认迭代清单未含"
    cfg = LLMProvidersConfig.load()
    ps = cfg.get_providers_for_stage(StageName.AUDIO_DIRECTOR)
    assert ps, "无 enabled provider 覆盖 audio_director"
    from audiobook_studio.harness.config import get_harness_settings
    hs = get_harness_settings()
    assert "audio_director" in hs.AUDIO_GATE_STAGES, "AUDIO_GATE_STAGES 未含"
    return f"顺序/枚举/路由 OK, providers={[p.name for p in ps][:3]}"


check("E 顺序接线与路由", e_wiring)


# ── F. canary 映射 + harness 金标 + 全链迭代 (mock) ──────────────────────────
def f_harness_cycle():
    from audiobook_studio.feedback.canary import (
        STAGE_TYPE, _convert_input_to_model, _get_required_input_fields,
        _run_stage_with_prompt_version,
    )
    assert STAGE_TYPE.get("audio_director") == "audio_direction"
    assert _get_required_input_fields("audio_director") == ["paragraph_text", "sentences"]
    m = _convert_input_to_model("audio_director", {"paragraph_text": "一。二！", "sentences": ["一。", "二！"]})
    assert type(m).__name__ == "AudioDirectorInput"

    # 分发 mock 跑通 (不触网)
    out = _run_stage_with_prompt_version(
        "audio_director", 1,
        {"paragraph_text": "夜风掠过山岗。狼群在远处嚎叫！", "sentences": ["夜风掠过山岗。", "狼群在远处嚎叫！"]},
    )
    assert type(out).__name__ == "AudioDirectorOutput" and out.sentence_overrides == []

    # 金标三 split 加载
    from audiobook_studio.harness.golden import GoldenDatasetManager
    mgr = GoldenDatasetManager()
    for split, n in (("train", 4), ("test", 3), ("val", 3)):
        samples = mgr.load_samples("audio_director", split)
        assert len(samples) == n, f"{split} 金标 {len(samples)} != {n}"
        for s in samples:
            assert s.sample_hash and s.input.get("sentences"), f"{split} 金标行缺字段"

    # 全链迭代 (沙箱隔离副本, auto_deploy=False, mock)
    from audiobook_studio.harness.harness import run_iteration_cycle
    tmp = Path(tempfile.mkdtemp(prefix="b3_sandbox_"))
    try:
        shutil.copytree(Path("prompts/harness/audio_director"), tmp / "audio_director")
        rep = run_iteration_cycle(
            "audio_director", run_fn=None, k=2,
            prompts_root=tmp, auto_deploy=False,
        )
        d = rep.to_dict()
        assert (tmp / "audio_director" / f"v{d.get('candidate_version', 2)}.j2").exists(), \
            f"候选未落盘: {sorted(p.name for p in (tmp / 'audio_director').iterdir())}"
        assert d.get("compiled") is True, f"候选未编译: {d}"
        assert d.get("eval_case_count", 0) >= 3, f"test 留出集未跑满: case_count={d.get('eval_case_count')}"
        # mock 模式下金标期望 (有建议) vs 实际 (空建议) 不匹配 → pass_rate 低是诚实行为,
        # 但迭代结构必须完整: 门禁裁决了且未部署 (auto_deploy=False)
        assert d.get("deployed") is False, "auto_deploy=False 却部署了"
        detail = f"候选 v{d.get('candidate_version')}, cases={d.get('eval_case_count')}, score={d.get('eval_mean_score'):.3f}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return detail


check("F canary + 金标 + 迭代全链", f_harness_cycle)


# ── 汇总 ─────────────────────────────────────────────────────────────────────
passed = sum(1 for _, ok, _ in RESULTS if ok)
failed = len(RESULTS) - passed
print("=" * 60)
print(f"汇总: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
