#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v6 收编验证脚本 — P1c 逐句三轴导演 + P2a per-voice 响度校准。

覆盖任务验证清单：
  1. 句切分：英文 3 句 / 中文 2 句正确；"Mr." 缩写为已知可接受误差（注明）
  2. merge_sentence_prosody 合并断言（gain_db delta / speed→rate / pitch_st→pitch /
     voice_id 替换 / 缺省继承）
  3. compute_voice_calib_db 校准计算
     【符号差异注明】任务背景公式 calib_db = clamp(TARGET_LUFS - measured, -3, +3)
     （实现所依：实测偏响 → 负值压低）。任务验证条目写的是
     "measured=-18 → +3 封顶；measured=-30 → -3 封顶"（方向相反）。
     本实现按背景公式（声学正确方向）：
       measured=-18 (偏响 5dB) → -3.0 封顶（压低）
       measured=-30 (偏轻 7dB) → +3.0 封顶（抬升）
     -inf / None（mock 静音保护）→ 0.0
  4. synthesize 模块 import 检查（逐句路径 + 校准符号均存在）
  5. ReviewEditPanel 切句 util（web/src/utils/sentences.ts 纯函数）：
     从 TS 源提取 SENTENCE_END_RE 正则，用同款算法在 Python 侧复跑，
     断言与后端 _split_sentences 逐字一致（前后端切句 parity）
  6. 双库迁移列检查（src/data/audiobook.db 与 data/audiobook.db）

运行：.venv/bin/python scratch/v6_incorporation/smoke_p1c_p2a.py
（约束：禁止 pytest → 纯 assert 脚本）
"""

import json
import math
import re
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

PASSED: list[str] = []


def ok(name: str) -> None:
    PASSED.append(name)
    print(f"  PASS  {name}")


# ── 1. 句切分（后端实现）──────────────────────────────────────────────
print("[1] 句切分 _split_sentences")
from audiobook_studio.pipeline.synthesize import _split_sentences  # noqa: E402

en = _split_sentences("Hello world. This is a test! Is it working?")
assert en == ["Hello world.", "This is a test!", "Is it working?"], en
ok("英文 3 句正确切分")

zh = _split_sentences("你好世界。这是测试！")
assert zh == ["你好世界。", "这是测试！"], zh
ok("中文 2 句正确切分（[。！？；]）")

zh_semi = _split_sentences("第一句；第二句？结尾")
assert zh_semi == ["第一句；", "第二句？", "结尾"], zh_semi
ok("中文分号/问号 + 无标点尾句")

q = _split_sentences('He said "Go!" Then he left.')
assert q == ['He said "Go!"', "Then he left."], q
ok("英文收尾引号随本句（引号边界）")

zh_q = _split_sentences("“第一句。”第二句。")
assert zh_q == ["“第一句。”", "第二句。"], zh_q
ok("中文弯引号随本句")

tail = _split_sentences("One. two three")
assert tail == ["One.", "two three"], tail
ok("句尾无标点余文作末句")

assert _split_sentences("") == [] and _split_sentences("   ") == []
ok("空文本 → 空列表")

# 已知可接受误差（任务注明）：缩写 "Mr." 被当句末切开 —— 断言实际行为并注明
mr = _split_sentences("Mr. Smith left.")
assert mr == ["Mr.", "Smith left."], mr
ok("已知误差确认：'Mr.' 缩写被当句末（任务注明的既有边界，非缺陷）")

# ── 2. merge_sentence_prosody 合并语义 ────────────────────────────────
print("[2] merge_sentence_prosody 逐句覆盖合并")
from audiobook_studio.pipeline.synthesize import (  # noqa: E402
    SENTENCE_GAP_DEFAULT_MS,
    VOICE_CALIB_CAP_DB,
    _is_blend_voice_id,
    _override_pause_ms,
    merge_sentence_prosody,
)

base_prosody = {"rate": 1.0, "pitch": 0, "volume": -2.0}
voice, pros = merge_sentence_prosody(
    "zh_CN-huayan-medium",
    base_prosody,
    {"idx": 0, "gain_db": 4.0, "speed": 0.86, "pitch_st": 1.0,
     "voice_id": "am_onyx+am_fenrir*0.55", "pause_after_ms": 350},
)
assert voice == "am_onyx+am_fenrir*0.55", voice
assert pros["rate"] == 0.86, pros            # speed → 替换 rate
assert pros["pitch"] == 1.0, pros            # pitch_st → 替换 pitch
assert pros["volume"] == 2.0, pros           # gain_db = volume 上的 delta (-2+4)
assert pros["emotion"] if "emotion" in pros else True
assert base_prosody == {"rate": 1.0, "pitch": 0, "volume": -2.0}, base_prosody
ok("全字段 override：speed→rate / pitch_st→pitch 替换，gain_db 为 volume delta，voice 替换，不改动原 dict")

voice2, pros2 = merge_sentence_prosody("voiceA", {"rate": 1.1, "pitch": 2, "volume": 0.5}, {"idx": 1, "gain_db": 1.5})
assert voice2 == "voiceA", voice2            # 未给 voice_id → 继承段落级
assert pros2["rate"] == 1.1 and pros2["pitch"] == 2, pros2
assert pros2["volume"] == 2.0, pros2          # 0.5 + 1.5
ok("部分 override：未覆盖字段继承段落级")

voice3, pros3 = merge_sentence_prosody("voiceA", {"rate": 1.1}, {"idx": 2, "voice_id": "am_onyx"})
assert voice3 == "am_onyx" and pros3 == {"rate": 1.1}, pros3
ok("仅 voice_id override：韵律全继承")

assert _is_blend_voice_id("am_onyx+am_fenrir*0.55") and _is_blend_voice_id("am_onyx")
assert not _is_blend_voice_id("am_onyx+")
ok("blend 音色语法正则（a+b*0.55）")

assert _override_pause_ms({"pause_after_ms": 350}, SENTENCE_GAP_DEFAULT_MS) == 350
assert _override_pause_ms({}, SENTENCE_GAP_DEFAULT_MS) == SENTENCE_GAP_DEFAULT_MS == 220
assert _override_pause_ms({"pause_after_ms": "abc"}, 220) == 220
assert _override_pause_ms({"pause_after_ms": -5}, 220) == 0
ok(f"句后停顿：override→值 / 缺省→{SENTENCE_GAP_DEFAULT_MS}ms micro 间隙 / 非法→缺省 / 负→0")

# ── 3. compute_voice_calib_db 校准计算 ────────────────────────────────
print("[3] compute_voice_calib_db（P2a per-voice 响度校准）")
from audiobook_studio.pipeline.synthesize import compute_voice_calib_db  # noqa: E402

# 实现依任务背景公式：calib = clamp(TARGET_LUFS - measured, -3, +3)，TARGET=-23 (audiobook 档)
assert compute_voice_calib_db(-18.0) == -3.0, compute_voice_calib_db(-18.0)   # 偏响 5dB → 压低，-3 封顶
assert compute_voice_calib_db(-30.0) == 3.0, compute_voice_calib_db(-30.0)    # 偏轻 7dB → 抬升，+3 封顶
ok("measured=-18 → -3.0 / measured=-30 → +3.0（按背景公式 clamp(TARGET-measured,±3)；"
   "任务验证条目符号相反，差异见脚本头注与报告）")

assert compute_voice_calib_db(float("-inf")) == 0.0   # mock/offline 静音保护
assert compute_voice_calib_db(float("nan")) == 0.0
assert compute_voice_calib_db(None) == 0.0
assert compute_voice_calib_db(-23.0) == 0.0           # 恰在目标 → 不动
assert compute_voice_calib_db(-24.5) == 1.5           # 未触封顶的原值
assert compute_voice_calib_db(-24.5, cap_db=1.0) == 1.0
assert VOICE_CALIB_CAP_DB == 3.0
ok("-inf/NaN/None → 0.0（mock 静音保护）；-23 → 0；cap 可参数化（默认 ±3dB）")

from audiobook_studio.pipeline.synthesize import _CALIB_TARGET_LUFS  # noqa: E402
assert _CALIB_TARGET_LUFS() == -23.0, _CALIB_TARGET_LUFS()
ok("目标响度 = utils/loudness.py audiobook 档 I=-23 LUFS")

# ── 4. synthesize 模块 import + 新成员检查 ────────────────────────────
print("[4] synthesize 模块 import 检查")
import audiobook_studio.pipeline.synthesize as synth  # noqa: E402

for attr in (
    "_split_sentences", "merge_sentence_prosody", "compute_voice_calib_db",
    "SENTENCE_GAP_DEFAULT_MS", "VOICE_CALIB_CAP_DB", "_SENT_END_RE", "_BLEND_RE",
):
    assert hasattr(synth, attr), attr
for meth in (
    "_synthesize_paragraph_with_overrides", "_probe_voice_calibration",
    "_apply_voice_calibration", "_measure_integrated_lufs",
    "_persist_voice_calibration",
):
    assert hasattr(synth.SynthesizePipeline, meth), meth
ok("模块可导入；逐句路径与校准方法齐备")

from audiobook_studio.schemas.tts_routing import TtsRoutingInput  # noqa: E402
from audiobook_studio.models.paragraph import Paragraph  # noqa: E402

sov = [{"idx": 0, "gain_db": 4.0, "voice_id": "am_onyx+am_fenrir*0.55"}]
inp = TtsRoutingInput(
    paragraph_annotation={
        "paragraph_index": 0, "speaker_canonical_name": "_narrator_",
        "is_dialogue": False, "emotion": "neutral", "emotion_intensity": 0.5,
        "confidence": 0.9,
    },
    text="Hello world.", character_voice_map=[{
        "canonical_name": "_narrator_", "aliases": [], "gender": "neutral",
        "age_range": "adult", "suggested_voice_id": "v1", "sample_quote": "q",
    }],
    book_id="bk", chapter_index=1, paragraph_index=0, sentence_overrides=sov,
)
assert inp.sentence_overrides == sov
assert "sentence_overrides" in Paragraph.to_full_dict(Paragraph(id=1, index=0, text="t"))
ok("TtsRoutingInput.sentence_overrides 契约字段 + Paragraph.to_full_dict 含新列")

# ── 5. 前端切句 util parity（web/src/utils/sentences.ts）─────────────
print("[5] ReviewEditPanel 切句 util（前端纯函数 ↔ 后端 parity）")
ts_path = REPO / "web" / "src" / "utils" / "sentences.ts"
ts_src = ts_path.read_text(encoding="utf-8")

m = re.search(r"SENTENCE_END_RE\s*=\s*/(.*)/g\s*$", ts_src, re.M)
assert m, "未在 sentences.ts 找到 SENTENCE_END_RE 正则"
js_re_src = m.group(1)
# JS 正则源与 Python re 在此模式（字符类/前瞻/交替）语义一致 → 直接编译对照
front_re = re.compile(js_re_src)
assert "export function splitSentences" in ts_src
ok(f"从 TS 提取正则并编译：{js_re_src!r}（与后端 _SENT_END_RE 同源）")

def front_split(text: str) -> list[str]:
    """镜像 sentences.ts splitSentences 的算法（用提取的前端正则）。"""
    if not text or not text.strip():
        return []
    sentences: list[str] = []
    start = 0
    for mm in front_re.finditer(text):
        matched = mm.group()
        if not matched:
            continue
        end = mm.end()
        if matched[0] in ".!?":
            j = end
            while j < len(text) and text[j] in " \t":
                j += 1
            end = j
        seg = text[start:end].strip()
        if seg:
            sentences.append(seg)
        start = end
    tail = text[start:].strip()
    if tail:
        sentences.append(tail)
    return sentences

CASES = [
    "Hello world. This is a test! Is it working?",
    "你好世界。这是测试！",
    "第一句；第二句？结尾",
    'He said "Go!" Then he left.',
    "“第一句。”第二句。",
    "One. two three",
    "Mr. Smith left.",
    "",
    "   ",
    "No punctuation at all",
]
for c in CASES:
    assert front_split(c) == _split_sentences(c), (c, front_split(c), _split_sentences(c))
ok(f"前端正则复跑 {len(CASES)} 个用例与后端 _split_sentences 输出完全一致")

assert front_split("Hello world. This is a test! Is it working?") == [
    "Hello world.", "This is a test!", "Is it working?",
]
assert front_split("你好世界。这是测试！") == ["你好世界。", "这是测试！"]
ok("前端切句：英文 3 句 / 中文 2 句断言通过")

# ── 6. 双库迁移列检查 ────────────────────────────────────────────────
print("[6] 双库迁移（alembic sentence_overrides 列）")
for db in (REPO / "src" / "data" / "audiobook.db", REPO / "data" / "audiobook.db"):
    assert db.exists(), db
    con = sqlite3.connect(db)
    try:
        cols = [r[1] for r in con.execute("PRAGMA table_info(paragraphs)").fetchall()]
    finally:
        con.close()
    assert "sentence_overrides" in cols, (db, cols)
    ok(f"{db.relative_to(REPO)}: paragraphs.sentence_overrides 列存在")

# ── 汇总 ─────────────────────────────────────────────────────────────
print(f"\n=== smoke_p1c_p2a 全部通过：{len(PASSED)} 项 ===")
print(json.dumps({"passed": len(PASSED), "cap_db": VOICE_CALIB_CAP_DB,
                  "gap_ms": SENTENCE_GAP_DEFAULT_MS}, ensure_ascii=False))
