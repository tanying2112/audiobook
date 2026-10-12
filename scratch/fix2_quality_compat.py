"""Fix 2 收尾：quality 在 check_input_compatibility 中按「非 prompt 驱动」
诚实短路。

实证链：QualityCheckPipeline.run 的真实输入契约是
List[Tuple[audio_path, ParagraphAnnotation, TtsRoutingDecision, reference_text]]
（pipeline/quality_check.py:90-95），dict 金标输入根本无法驱动 —— 即使凑齐
audio_path/expected_text 也只是「字段名巧合」，元组契约依旧不满足。
此前该分支还把输出 schema QualityJudgment 当输入模型转换（既有披露缺陷）。

故对非 prompt 驱动阶段统一短路为「不兼容 + 原因」，不再进入字段检查/模型
转换；canary 侧已有同源整阶段跳过（integration._run_canary_validation），
此处保证任何调用路径都得到一致的诚实判定。
"""
from pathlib import Path

p = Path("src/audiobook_studio/feedback/canary.py")
src = p.read_text(encoding="utf-8")

old = '''    if not isinstance(input_data, dict):
        return False, f"input 不是 dict 而是 {type(input_data).__name__}"
    missing = [f for f in _get_required_input_fields(pipeline_stage) if f not in input_data]'''
new = '''    if pipeline_stage in NON_PROMPT_DRIVEN_STAGES:
        # 质检真实契约为 (audio_path, ParagraphAnnotation, TtsRoutingDecision,
        # reference_text) 元组（QualityCheckPipeline.run），dict 金标输入无法
        # 驱动；且该阶段为 ASR/WER 音频规则驱动，prompt A/B 实证无意义 ——
        # 与 integration._run_canary_validation 的整阶段跳过同源判定。
        return False, "非 prompt 驱动阶段（音频 ASR/WER 质检），金标 dict 输入无法驱动元组契约，无法做 prompt A/B 实证"
    if not isinstance(input_data, dict):
        return False, f"input 不是 dict 而是 {type(input_data).__name__}"
    missing = [f for f in _get_required_input_fields(pipeline_stage) if f not in input_data]'''
assert src.count(old) == 1
src = src.replace(old, new)
p.write_text(src, encoding="utf-8")
print("quality compat short-circuit OK")
