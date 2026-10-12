"""Fix 2 接线（被中断后重跑）+ 单例门判定 example_passes_gate（文本主导）。

校准实测（live v43 × 24 真实金标）：正确输出的综合相似度 0.73-0.83 全部
低于 0.85 —— 被 changes_made 措辞差异与置信度校准拖垮，而产品文本相似度
0.84-1.00。门禁要回答的是「产品文本对不对」，故 stage 有产品文本字段时
单例判定锚定文本相似度，综合分保留为参考指标。
"""
from pathlib import Path

# ── 1) candidate_eval.py：example_passes_gate ──
p = Path("src/audiobook_studio/feedback/candidate_eval.py")
src = p.read_text(encoding="utf-8")
old = '''    total_w = sum(w for _, w in parts)
    return sum(s * w for s, w in parts) / total_w


class DeterministicJudge:'''
new = '''    total_w = sum(w for _, w in parts)
    return sum(s * w for s, w in parts) / total_w


def example_passes_gate(
    expected: Any, output: Any, stage: Optional[str] = None, threshold: float = 0.85
) -> bool:
    """单例金标门判定：stage 声明了产品文本字段时，以文本相似度 ≥ threshold 为准。

    为什么不用综合相似度过 0.85：2026-10 校准实测（live v43 × 24 条真实金标），
    正确输出的综合分被 ``changes_made`` 措辞差异（精确串 Jaccard≈0，如
    「删除冗余修饰」vs「冗余修饰删减」）与置信度校准拉到 0.73-0.83 全线
    不达标，而其产品文本相似度 0.84-1.00。门的问题形态是「产品文本对不对」，
    判定必须锚定产品本身；标签措辞与置信度只是佐证，已计入综合分供参考，
    不作硬门（否则门对正确输出恒假阴，对措辞复读机恒假阳）。无产品文本
    字段的 stage（judge/quality 等）维持综合分判定，行为不变。
    """
    exp: Dict[str, Any] = _to_dict(expected)
    out: Dict[str, Any] = _to_dict(output)
    for k in STAGE_PRIMARY_TEXT_FIELDS.get(stage or "", ()):
        if k in exp:
            return _text_similarity(exp[k], out.get(k, "")) >= threshold
    return score_output_vs_expected(exp, out, stage=stage) >= threshold


class DeterministicJudge:'''
assert src.count(old) == 1
src = src.replace(old, new)
p.write_text(src, encoding="utf-8")
print("candidate_eval.py OK")

# ── 2) promotion_gate.py：再导出新符号 ──
p = Path("src/audiobook_studio/feedback/promotion_gate.py")
src = p.read_text(encoding="utf-8")
old = """from .canary import (
    GOLDEN_TO_PIPELINE_STAGE,
    PIPELINE_STAGE_TO_PROMPT_DIR,
    SELF_ITERATION_MOCK_ENV,
    STAGE_TYPE,
    _convert_input_to_model,
    _get_required_input_fields,"""
new = """from .canary import (
    GOLDEN_TO_PIPELINE_STAGE,
    NON_PROMPT_DRIVEN_STAGES,
    PIPELINE_STAGE_TO_PROMPT_DIR,
    SELF_ITERATION_MOCK_ENV,
    STAGE_TYPE,
    _convert_input_to_model,
    _get_required_input_fields,
    check_input_compatibility,"""
assert src.count(old) == 1
src = src.replace(old, new)
p.write_text(src, encoding="utf-8")
print("promotion_gate.py OK")

# ── 3) integration.py：金丝雀契约预检 + 整段跳过 + 文本主导单例判定 ──
p = Path("src/audiobook_studio/feedback/integration.py")
src = p.read_text(encoding="utf-8")

old = "from .canary import STAGE_TYPE"
new = "from .canary import NON_PROMPT_DRIVEN_STAGES, STAGE_TYPE, check_input_compatibility"
assert src.count(old) == 1
src = src.replace(old, new)

old = """            # Map stage to pipeline stage
            pipeline_stage = _golden_to_pipeline_stage(stage)
            stage_type = STAGE_TYPE.get(pipeline_stage, "unknown")

            # Run validation for each example
            validation_scores: List[Dict[str, Any]] = []
            passed_count = 0
            failed_details: List[Dict[str, Any]] = []

            for i, example in enumerate(canary_examples):
                if "input" not in example or "expected_output" not in example:
                    continue

                input_data = example["input"]
                expected_output = example["expected_output"]
"""
new = """            # Map stage to pipeline stage
            pipeline_stage = _golden_to_pipeline_stage(stage)
            stage_type = STAGE_TYPE.get(pipeline_stage, "unknown")

            # 无 prompt 驱动的阶段（quality：ASR/WER 音频质检）结构上无法做
            # prompt 版本 A/B —— 显式跳过并标记原因，而非硬跑出假指标。
            if pipeline_stage in NON_PROMPT_DRIVEN_STAGES:
                results[stage] = {
                    "skipped": True,
                    "skipped_reason": (
                        f"{pipeline_stage} 阶段非 prompt 驱动（音频 ASR/WER 质检），无法做 prompt 版本 A/B"
                    ),
                    "canary_examples_tested": 0,
                    "pass_rate": None,
                }
                logger.info(f"[Canary] {stage}: skipped —— {results[stage]['skipped_reason']}")
                continue

            # Run validation for each example
            validation_scores: List[Dict[str, Any]] = []
            passed_count = 0
            failed_details: List[Dict[str, Any]] = []
            incompatible_count = 0
            incompat_reason = ""

            for i, example in enumerate(canary_examples):
                if "input" not in example or "expected_output" not in example:
                    continue

                input_data = example["input"]
                expected_output = example["expected_output"]

                # 金标输入与阶段契约不兼容：显式跳过并计数——这是数据/契约
                # 错配，不是「候选失败」，不得混入 pass_rate（2026-10 披露局限）。
                compatible, reason = check_input_compatibility(pipeline_stage, input_data)
                if not compatible:
                    incompatible_count += 1
                    incompat_reason = reason
                    continue
"""
assert src.count(old) == 1
src = src.replace(old, new)

old = """            # Aggregate results
            total = len(validation_scores)
            pass_rate = passed_count / total if total > 0 else 0.0"""
new = """            # 全部不兼容：整阶段显式跳过——不能把 0/0 误报成 pass_rate=0
            # 的「候选失败」，也不能带空内容烧真 LLM 产垃圾分。
            if not validation_scores and incompatible_count > 0:
                results[stage] = {
                    "skipped": True,
                    "skipped_reason": (
                        f"金丝雀输入与 {pipeline_stage} 阶段输入契约不兼容"
                        f"（{incompatible_count}/{len(canary_examples)} 例：{incompat_reason}），无法真实 A/B"
                    ),
                    "canary_examples_tested": 0,
                    "pass_rate": None,
                }
                logger.warning(f"[Canary] {stage}: skipped —— {results[stage]['skipped_reason']}")
                continue

            # Aggregate results
            total = len(validation_scores)
            pass_rate = passed_count / total if total > 0 else 0.0"""
assert src.count(old) == 1
src = src.replace(old, new)

old = """            results[stage] = {
                "canary_examples_tested": total,
                "passed_count": passed_count,"""
new = """            results[stage] = {
                "canary_examples_tested": total,
                "incompatible_examples_skipped": incompatible_count,
                "passed_count": passed_count,"""
assert src.count(old) == 1
src = src.replace(old, new)

# 单例判定改为文本主导（综合分照常记录为 similarity）
old = "                    from .candidate_eval import score_output_vs_expected"
new = "                    from .candidate_eval import example_passes_gate, score_output_vs_expected"
assert src.count(old) == 1
src = src.replace(old, new)

old = "similarity >= 0.85 and quality_ratio >= 1.02"
assert src.count(old) == 2, src.count(old)
src = src.replace(
    old,
    "example_passes_gate(expected_output, new_output, stage=stage) and quality_ratio >= 1.02",
)
p.write_text(src, encoding="utf-8")
print("integration.py OK")

# ── 4) promotion.py：不兼容显式计数 + 文本主导单例判定 ──
p = Path("src/audiobook_studio/feedback/promotion.py")
src = p.read_text(encoding="utf-8")

old = """    pipeline_stage = promotion_gate._golden_to_pipeline_stage(stage)
    passed_count = 0
    failed_details: List[str] = []
    valid_examples = 0

    for i, example in enumerate(examples):
        # Expect golden dataset format: {"input": {...}, "expected_output": {...}}
        if "input" not in example or "expected_output" not in example:
            logger.warning(f"Golden example {i} missing 'input' or 'expected_output' field")
            continue

        input_data = example["input"]
        expected_output = example["expected_output"]

        # Check if input has required fields for this pipeline stage
        required_fields = promotion_gate._get_required_input_fields(pipeline_stage)
        if not all(field in input_data for field in required_fields):
            logger.debug(f"Golden example {i} missing required fields for {pipeline_stage}: {required_fields}")
            continue
"""
new = """    pipeline_stage = promotion_gate._golden_to_pipeline_stage(stage)
    passed_count = 0
    failed_details: List[str] = []
    valid_examples = 0
    incompatible_examples = 0

    for i, example in enumerate(examples):
        # Expect golden dataset format: {"input": {...}, "expected_output": {...}}
        if "input" not in example or "expected_output" not in example:
            logger.warning(f"Golden example {i} missing 'input' or 'expected_output' field")
            continue

        input_data = example["input"]
        expected_output = example["expected_output"]

        # 输入与阶段契约不兼容（缺核心字段 / 模型转换失败）：显式计数后跳过。
        # 这是金标数据与阶段契约的错配，不是候选失败；fail-closed 语义不变，
        # 但 details 必须诚实标注原因，不能把基建错配标成「候选质量差」。
        compatible, incompat_reason = promotion_gate.check_input_compatibility(pipeline_stage, input_data)
        if not compatible:
            incompatible_examples += 1
            logger.debug(f"Golden example {i} incompatible for {pipeline_stage}: {incompat_reason}")
            continue
"""
assert src.count(old) == 1
src = src.replace(old, new)

old = """    if valid_examples == 0:
        return GateResult(
            name="黄金数据集通过率",
            passed=False,
            score=0.0,
            threshold=threshold,
            details=f"无有效测试用例 (共 {len(examples)} 个，缺少必需字段)",
        )"""
new = """    if valid_examples == 0:
        if incompatible_examples > 0:
            details = (
                f"金标输入与 {pipeline_stage} 阶段契约不兼容"
                f"（{incompatible_examples}/{len(examples)} 例），无法实证评测 —— fail-closed"
            )
        else:
            details = f"无有效测试用例 (共 {len(examples)} 个，缺少必需字段)"
        return GateResult(
            name="黄金数据集通过率",
            passed=False,
            score=0.0,
            threshold=threshold,
            details=details,
        )"""
assert src.count(old) == 1
src = src.replace(old, new)

old = """        details=(
            f"{passed_count}/{valid_examples} 用例通过 ({score * 100:.1f}% ≥ {threshold * 100:.0f}%)"
            + (f" | 失败: {'; '.join(failed_details[:3])}" if failed_details else "")
        ),"""
new = """        details=(
            f"{passed_count}/{valid_examples} 用例通过 ({score * 100:.1f}% ≥ {threshold * 100:.0f}%)"
            + (f" | 失败: {'; '.join(failed_details[:3])}" if failed_details else "")
            + (f" | 另有 {incompatible_examples} 例输入不兼容已跳过" if incompatible_examples else "")
        ),"""
assert src.count(old) == 1
src = src.replace(old, new)

old = """            from .candidate_eval import score_output_vs_expected

            similarity = score_output_vs_expected(expected_output, actual_output, stage=stage)

            if similarity >= 0.85:  # 85% similarity threshold for "pass"
                passed_count += 1"""
new = """            from .candidate_eval import example_passes_gate, score_output_vs_expected

            similarity = score_output_vs_expected(expected_output, actual_output, stage=stage)

            # 单例判定：产品文本字段 stage 以文本相似度为准（2026-10 校准后语义），
            # 综合相似度保留为参考指标记入 failed_details。
            if example_passes_gate(expected_output, actual_output, stage=stage):
                passed_count += 1"""
assert src.count(old) == 1
src = src.replace(old, new)
p.write_text(src, encoding="utf-8")
print("promotion.py OK")
