#!/usr/bin/env python3
"""Batch 2.3 冒烟: 断句缩写修复 + zh 韵律分级停顿.

覆盖:
  A. 英文缩写 (Mr./Mrs./Dr./St./Prof./Jr./vs.) 不再误切句
  B. CJK 收尾角括号 」』 随本句 (不再甩到下句开头)
  C. zh 标点分级停顿 (。！？→500ms, ；→300ms, 英文→220ms 不回归)
  D. 显式 override pause_after_ms 优先于分级默认
  E. v6 既有行为无回归 (引号边界/空输入/收尾空白吞并)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
PASS, FAIL = [], []


def check(name, fn):
    try:
        detail = fn()
        PASS.append(name)
        print(f"[PASS] {name}" + (f" — {detail}" if detail else ""), flush=True)
    except Exception as e:
        FAIL.append(name)
        print(f"[FAIL] {name} — {e}", flush=True)


def expect(cond, msg):
    if not cond:
        raise AssertionError(msg)


def t_split():
    from audiobook_studio.pipeline.synthesize import _split_sentences
    s = _split_sentences("Mr. Smith arrived. He spoke.")
    expect(s == ["Mr. Smith arrived.", "He spoke."], f"Mr. 误切: {s}")
    s = _split_sentences("Mrs. Jones met Dr. Watson. They left!")
    expect(s == ["Mrs. Jones met Dr. Watson.", "They left!"], f"Mrs./Dr. 误切: {s}")
    s = _split_sentences("St. Louis vs. Chicago played. It rained.")
    expect(s == ["St. Louis vs. Chicago played.", "It rained."], f"St./vs. 误切: {s}")
    s = _split_sentences("Prof. Lee greeted Ms. Chen. Jr. was there too.")
    expect(s == ["Prof. Lee greeted Ms. Chen.", "Jr. was there too."], f"Prof./Ms./Jr. 误切: {s}")
    # 残留 (设计取舍): 真以缩写收尾的句子并入下一句
    s = _split_sentences("We talked, etc. Then we left.")
    expect(s == ["We talked, etc. Then we left."], f"etc 残留行为变化: {s}")
    # 非缩写词不受影响 (大小写敏感: 小写 no. 不拦)
    s = _split_sentences("The answer is no. Next question!")
    expect(s == ["The answer is no.", "Next question!"], f"小写 no 被误拦: {s}")
    s = _split_sentences("Premier. Minister. Ordinary words.")
    expect(len(s) == 3, f"普通词被误拦: {s}")
    return "9 组切句全部符合预期"


def t_cjk_closers():
    from audiobook_studio.pipeline.synthesize import _split_sentences
    s = _split_sentences("他说：『你好。』然后走了。")
    expect(s == ["他说：『你好。』", "然后走了。"], f"』 未随本句: {s}")
    s = _split_sentences("引号句「去吗？」他问。")
    expect(s == ["引号句「去吗？」", "他问。"], f"」 未随本句: {s}")
    s = _split_sentences("第一句。第二句；半句。")
    expect(s == ["第一句。", "第二句；", "半句。"], f"zh 基本切分回归: {s}")
    return "」』收尾归属正确"


def t_pause_grading():
    from audiobook_studio.pipeline.synthesize import (
        _sentence_pause_default_ms, SENTENCE_GAP_DEFAULT_MS,
        ZH_SENTENCE_END_PAUSE_MS, ZH_SEMICOLON_PAUSE_MS,
    )
    expect(ZH_SENTENCE_END_PAUSE_MS == 500, "常量漂移")
    expect(ZH_SEMICOLON_PAUSE_MS == 300, "常量漂移")
    expect(SENTENCE_GAP_DEFAULT_MS == 220, "v6 英文默认被改动")
    f = _sentence_pause_default_ms
    expect(f("你好。") == 500, "。分级错误")
    expect(f("是吗？") == 500, "？分级错误")
    expect(f("好啊！") == 500, "！分级错误")
    expect(f("半句；") == 300, "；分级错误")
    expect(f("He spoke.") == 220, "英文句末应为 220")
    expect(f('He said "Go!"') == 220, "英文收尾引号应保持 220")
    expect(f("『你好。』") == 500, "』应剥除后判 。")
    expect(f("「去吗？」") == 500, "」应剥除后判 ？")
    expect(f("省略…") == 220, "省略号应落英文默认档")
    expect(f("无标点残句") == 220, "残句应落默认档")
    expect(f("") == 220, "空串应落默认档")
    expect(f("  你好。  ") == 500, "尾空白应剥除")
    return "12 组分级断言全过"


def t_override_precedence():
    from audiobook_studio.pipeline.synthesize import (
        _override_pause_ms, _sentence_pause_default_ms,
    )
    graded = _sentence_pause_default_ms("你好。")
    expect(_override_pause_ms({"pause_after_ms": 800}, graded) == 800, "显式 override 未优先")
    expect(_override_pause_ms({}, graded) == graded, "无 override 应用分级默认")
    expect(_override_pause_ms({"pause_after_ms": None}, graded) == graded, "None 应回退分级")
    expect(_override_pause_ms({"pause_after_ms": "750"}, graded) == 750, "字符串数字应可用")
    expect(_override_pause_ms({"pause_after_ms": "abc"}, graded) == graded, "坏值回退分级")
    expect(_override_pause_ms({"pause_after_ms": -5}, graded) == 0, "负值应 clamp 0")
    # 合成循环末句语义: 末句 default=0, 显式 override 仍生效
    expect(_override_pause_ms({}, 0) == 0, "末句默认应为 0")
    expect(_override_pause_ms({"pause_after_ms": 400}, 0) == 400, "末句显式 override 被吞")
    return "override > 分级默认 > 末句 0 优先级链正确"


def t_v6_regression():
    from audiobook_studio.pipeline.synthesize import _split_sentences
    s = _split_sentences('He said "Go!" Then.')
    expect(s == ['He said "Go!"', "Then."], f"v6 引号边界回归: {s}")
    expect(_split_sentences("") == [], "空输入回归")
    expect(_split_sentences("   ") == [], "纯空白回归")
    s = _split_sentences("One. Two.")
    expect(s == ["One.", "Two."], f"英文吞空白回归: {s}")
    expect("".join(x.replace(" ", "") for x in _split_sentences(
        "第一句。第二句；第三句！")) == "第一句。第二句；第三句！", "切分丢字符")
    return "v6 既有行为无回归"


for name, fn in [
    ("A 缩写不误切", t_split),
    ("B CJK 角括号收尾归属", t_cjk_closers),
    ("C zh 分级停顿", t_pause_grading),
    ("D override 优先级", t_override_precedence),
    ("E v6 无回归", t_v6_regression),
]:
    check(name, fn)

print("=" * 60)
print(f"汇总: {len(PASS)} passed, {len(FAIL)} failed")
sys.exit(0 if not FAIL else 1)
