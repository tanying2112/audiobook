"""A1 — character→preset-voice assignment (no-GPU clone substitute) tests."""

from audiobook_studio.tts import voice_assignment as va
from audiobook_studio.tts.engine import VoiceInfo


def _pool():
    return [
        VoiceInfo(voice_id="zf_xiaoxiao", name="x", language="zh", gender="female", engine="kokoro"),
        VoiceInfo(voice_id="zm_yunjian", name="m", language="zh", gender="male", engine="kokoro"),
        VoiceInfo(voice_id="zh_CN-huayan-medium", name="h", language="zh-CN", gender="female", engine="piper"),
    ]


def test_narrator_reserved_and_excluded_from_collision():
    pool = _pool()
    plan = va.character_voice_plan(["旁白", "张三", "李四"], pool=pool, narrator="zh_CN-huayan-medium")
    assert plan["旁白"].voice_id == "zh_CN-huayan-medium"
    # Non-narrator characters get distinct non-narrator voices.
    assert plan["张三"].voice_id != "zh_CN-huayan-medium"
    assert plan["李四"].voice_id != "zh_CN-huayan-medium"
    assert va.all_distinct(plan)


def test_deterministic_assignment():
    chars = ["张三", "李四", "王五"]
    p1 = va.character_voice_plan(chars)
    p2 = va.character_voice_plan(chars)
    assert [p1[c].voice_id for c in chars] == [p2[c].voice_id for c in chars]


def test_distinct_per_character():
    chars = ["张三", "李四", "王五", "赵六", "钱七"]
    plan = va.character_voice_plan(chars)
    ids = [plan[c].voice_id for c in chars]
    assert len(set(ids)) == len(ids)  # all distinct within pool capacity


def test_override_takes_precedence():
    plan = va.character_voice_plan(["张三", "李四"], pool=_pool(), override={"张三": "zm_yunjian"})
    assert plan["张三"].voice_id == "zm_yunjian"


def test_language_filtering():
    # English-only pool should not be used for a zh-CN request unless nothing else.
    en_pool = [VoiceInfo(voice_id="en_f", name="f", language="en", gender="female", engine="kokoro")]
    plan = va.character_voice_plan(["张三"], language="zh-CN", pool=en_pool)
    # Falls back to the only available voice rather than crashing.
    assert plan["张三"] is not None


def test_real_default_pool_covers_zh():
    plan = va.character_voice_plan(["旁白", "角色A", "角色B"])
    assert plan["旁白"].voice_id == va.NARRATOR_DEFAULT
    assert va.all_distinct(plan)
