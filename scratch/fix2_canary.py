"""Fix 2：canary/金标路径的 stage 输入契约校验——不兼容显式跳过，而非误报失败。

披露局限 (2)：quality/analyze/annotate 金丝雀路径输入不兼容
（quality 的 golden input 是 {text} 而阶段契约是 {audio_path, expected_text}；
annotate 金标 story_line_summary 只有 6 字但 schema 要求 ≥100；
analyze/extract 金标缺 book_text/text 核心字段）。此前这些例子要么以
pydantic ValidationError 计入 failed_details（误标为「候选失败」），
要么带空内容跑真 LLM 产出垃圾比较分。现在：逐例先验契约，不兼容即
显式跳过并标记；全不兼容则整个 stage 标记 skipped。
"""
from pathlib import Path

# ── 1) canary.py：新增 check_input_compatibility ──
p = Path("src/audiobook_studio/feedback/canary.py")
src = p.read_text(encoding="utf-8")

old = '''def _get_required_input_fields(pipeline_stage: str) -> List[str]:
    """Get required input fields for a pipeline stage."""
    if pipeline_stage == "edit":
        return ["paragraph_text", "paragraph_annotation", "difficulty", "forbid_edit"]
    elif pipeline_stage == "annotate":
        return ["paragraph_text", "paragraph_index"]
    elif pipeline_stage == "analyze":
        return ["book_text", "book_meta"]
    elif pipeline_stage == "extract":
        return ["text"]
    elif pipeline_stage == "quality":
        return ["audio_path", "expected_text"]
    elif pipeline_stage == "synthesize":
        return ["text", "voice_id"]
    else:
        return []'''
new = '''def _get_required_input_fields(pipeline_stage: str) -> List[str]:
    """Get required input fields for a pipeline stage."""
    if pipeline_stage == "edit":
        return ["paragraph_text", "paragraph_annotation", "difficulty", "forbid_edit"]
    elif pipeline_stage == "annotate":
        return ["paragraph_text", "paragraph_index"]
    elif pipeline_stage == "analyze":
        return ["book_text", "book_meta"]
    elif pipeline_stage == "extract":
        return ["text"]
    elif pipeline_stage == "quality":
        return ["audio_path", "expected_text"]
    elif pipeline_stage == "synthesize":
        return ["text", "voice_id"]
    else:
        return []


def check_input_compatibility(pipeline_stage: str, input_data: Any) -> "tuple[bool, str]":
    """检查 golden 输入能否真实驱动该 pipeline 阶段（核心字段齐全 + 模型可转换）。

    返回 (compatible, reason)。不兼容的例子必须显式跳过而非：
    (a) 以 ValidationError 计入 failed_details —— 把「金标数据格式与阶段契约
    不匹配」误标成「候选失败」；
    (b) 带空内容跑真 LLM —— 既烧配额又产出垃圾比较分。
    典型不兼容（2026-10 披露）：quality 金标 input={text} 而契约是
    {audio_path, expected_text}；annotate 金标 story_line_summary 过短违反
    schema；analyze/extract 金标缺 book_text/text。
    """
    if not isinstance(input_data, dict):
        return False, f"input 不是 dict 而是 {type(input_data).__name__}"
    missing = [f for f in _get_required_input_fields(pipeline_stage) if f not in input_data]
    if missing:
        return False, f"缺少阶段必需字段 {missing}"
    try:
        _convert_input_to_model(pipeline_stage, dict(input_data))
    except Exception as e:  # noqa: BLE001
        first = str(e).splitlines()[0] if str(e) else type(e).__name__
        return False, f"输入模型转换失败: {first[:120]}"
    return True, ""


# 无 prompt 可换的阶段：quality 是 ASR/WER 音频质检（模型判分，非模板驱动），
# 对它做「换 prompt 版本 A/B」在结构上不成立，须整体跳过而非硬跑。
NON_PROMPT_DRIVEN_STAGES = frozenset({"quality"})'''
assert src.count(old) == 1
src = src.replace(old, new)

# typing 导入 tuple 注解样式 —— 用字符串注解即可，无需改 imports
p.write_text(src, encoding="utf-8")
print("canary.py OK")
